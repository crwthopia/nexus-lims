"""
The dashboard's aggregation, computed here rather than in the browser.

Every figure below is derived from records the lab already keeps -- test
requests, samples, approvals, results -- and priced from the catalogue's
rate card. Two consequences follow, and both are stated on the screen
rather than buried here:

**This is list-price value, not revenue.** An Order has no line items yet
and `Invoice.amount` is still a typed lump sum, so nothing in the database
says what was actually billed for a given analysis. What can be computed
honestly is work performed x the rate in force on the day it was requested
-- which is what a lab means by "what is this bench worth", and is not the
same as money received. Calling it revenue would be a lie of one word.

**Not every request can be attributed to an offering.** A TestMethod
reaches an offering through a many-to-many, so a method that belongs to no
active offering, or to several (BOD sold standalone *and* inside a
potability panel), cannot be attributed to one line of the rate card
without order lines to say which was sold. Those requests are counted and
reported separately instead of being silently dropped or spread evenly --
the count is the honest measure of how much of the catalogue mapping is
still to do.
"""

import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q

from apps.audit.models import SystemFailure
from apps.catalogue.models import OfferingPrice, ServiceOffering
from apps.equipment.models import Instrument
from apps.investigations.models import Investigation
from apps.review.models import ApprovalAction
from apps.samples.models import Sample, ServiceLine
from apps.testing.models import TestRequest, TestResult

DEFAULT_WINDOW_DAYS = 90


def resolve_window(date_from, date_to, *, today):
    """
    The window to report on, and the equal-length one before it.

    The comparison window is the immediately preceding period of the same
    length, so a 30-day view compares against the 30 days before it rather
    than against "last month" -- a fixed calendar comparison makes a
    seven-day view compare a week against a month.
    """
    end = date_to or today
    start = date_from or (end - datetime.timedelta(days=DEFAULT_WINDOW_DAYS - 1))
    if start > end:
        start, end = end, start
    length = (end - start).days + 1
    previous_end = start - datetime.timedelta(days=1)
    previous_start = previous_end - datetime.timedelta(days=length - 1)
    return (start, end), (previous_start, previous_end)


class Pricer:
    """
    Maps a TestMethod to the one offering that sells it, and prices that
    offering on a given day.

    Built once per request and held in memory: the catalogue is master data
    of a few hundred rows at most, and doing this per test request would be
    two queries per row.
    """

    def __init__(self):
        offerings = ServiceOffering.objects.filter(is_active=True).prefetch_related("test_methods", "prices")

        self.by_method: dict[int, list[ServiceOffering]] = defaultdict(list)
        for offering in offerings:
            for method in offering.test_methods.all():
                self.by_method[method.id].append(offering)

        self.prices: dict[int, list[OfferingPrice]] = {
            offering.id: list(offering.prices.all()) for offering in offerings
        }

    def offering_for(self, method_id):
        """
        The offering to credit, or a reason not to.

        Returns (offering, reason). `reason` is None when attribution
        succeeded, otherwise the name of the thing standing in the way --
        which the caller reports rather than hides.
        """
        candidates = self.by_method.get(method_id, [])
        if not candidates:
            return None, "no_offering"
        if len(candidates) > 1:
            return None, "ambiguous"
        return candidates[0], None

    def price_on(self, offering, on_date):
        for price in self.prices.get(offering.id, []):
            if price.effective_from <= on_date and (price.effective_to is None or on_date <= price.effective_to):
                return price
        return None


def _request_rows(start, end):
    """
    Test requests in the window, grouped by method and day.

    Grouped rather than listed because pricing is per-day (the rate in
    force when the work was requested), so the day cannot be collapsed --
    but the *rows* can: this is bounded by methods x days, not by requests.
    """
    return (
        TestRequest.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
        .values("test_method_id", "created_at__date")
        .annotate(count=Count("id"))
    )


def _accumulate(rows, pricer):
    """Fold the grouped rows into per-offering, per-month and unattributed totals."""
    per_offering = defaultdict(lambda: {"count": 0, "net": Decimal("0.00")})
    per_month = defaultdict(lambda: {"count": 0, "net": Decimal("0.00")})
    unattributed = {"no_offering": 0, "ambiguous": 0, "unpriced": 0}
    total = {"count": 0, "net": Decimal("0.00")}

    for row in rows:
        day = row["created_at__date"]
        count = row["count"]
        month = day.strftime("%Y-%m")

        total["count"] += count
        per_month[month]["count"] += count

        offering, reason = pricer.offering_for(row["test_method_id"])
        if reason:
            unattributed[reason] += count
            continue

        price = pricer.price_on(offering, day)
        if price is None:
            # Attributable but not priced on the day the work was requested
            # -- an offering added before its rate was set, typically.
            unattributed["unpriced"] += count
            per_offering[offering.id]["count"] += count
            continue

        value = price.net_amount * count
        per_offering[offering.id]["count"] += count
        per_offering[offering.id]["net"] += value
        per_month[month]["net"] += value
        total["net"] += value

    return per_offering, per_month, unattributed, total


def _percentile(values, fraction):
    """
    Nearest-rank percentile on a sorted list, or None when there is nothing
    to take one of. Deliberately not interpolated: a turnaround figure is
    reported in days from a modest number of samples, and an interpolated
    p90 between two real samples is a number no sample ever had.
    """
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered) + 0.5) - 1))
    return ordered[index]


def _turnaround(start, end):
    """
    Days from a sample arriving to its approval, for samples approved in
    the window.

    Measured on the *approval* date rather than the arrival date because
    that is when the figure becomes knowable: bucketing by arrival would
    silently exclude everything still in progress and flatter the number.
    """
    approvals = (
        ApprovalAction.objects.filter(
            disposition=ApprovalAction.Disposition.APPROVED,
            created_at__date__gte=start,
            created_at__date__lte=end,
        )
        .select_related("sample")
        .values_list("sample__created_at", "created_at", "sample__service_line")
    )

    overall = []
    by_line = defaultdict(list)
    for received_at, approved_at, service_line in approvals:
        days = (approved_at - received_at).total_seconds() / 86400
        if days < 0:
            continue  # a back-dated fixture, not a lab that finished before it started
        overall.append(days)
        by_line[service_line].append(days)

    def summarise(values):
        return {
            "sample_count": len(values),
            "median_days": round(_percentile(values, 0.5), 1) if values else None,
            "p90_days": round(_percentile(values, 0.9), 1) if values else None,
        }

    return {
        **summarise(overall),
        "by_service_line": [
            {"service_line": line, **summarise(values)} for line, values in sorted(by_line.items())
        ],
    }


def _quality(start, end):
    results = TestResult.objects.filter(entered_at__date__gte=start, entered_at__date__lte=end).aggregate(
        total=Count("id"), out_of_spec=Count("id", filter=Q(is_out_of_spec=True))
    )
    total = results["total"] or 0
    return {
        "results_entered": total,
        "out_of_spec": results["out_of_spec"] or 0,
        "out_of_spec_pct": round(100 * results["out_of_spec"] / total, 1) if total else None,
        # These four are "right now", not "in the window": a queue depth is
        # a current state, and a count of it over a past period would mean
        # nothing. The screen labels them as such.
        "open_investigations": Investigation.objects.exclude(status=Investigation.Status.CLOSED).count(),
        "samples_awaiting_review": Sample.objects.filter(status=Sample.Status.UNDER_REVIEW).count(),
        "instruments_out_of_calibration": Instrument.objects.filter(
            status=Instrument.Status.OUT_OF_CALIBRATION
        ).count(),
        "open_system_failures": SystemFailure.objects.exclude(status=SystemFailure.Status.CLOSED).count(),
    }


def _totals(start, end, pricer):
    rows = _request_rows(start, end)
    per_offering, per_month, unattributed, total = _accumulate(rows, pricer)
    samples = Sample.objects.filter(created_at__date__gte=start, created_at__date__lte=end).count()
    return {
        "per_offering": per_offering,
        "per_month": per_month,
        "unattributed": unattributed,
        "test_requests": total["count"],
        "list_value_net": total["net"],
        "samples_received": samples,
    }


def _months_in(start, end):
    """Every month the window touches, so a quiet month is a zero rather than a gap."""
    months = []
    cursor = start.replace(day=1)
    while cursor <= end:
        months.append(cursor.strftime("%Y-%m"))
        cursor = (cursor.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return months


def dashboard(*, date_from=None, date_to=None, today=None, leading_limit=8, rank="volume"):
    """
    `rank` picks which measure orders the leading analyses, because the two
    answers are genuinely different and a lab needs both: the panel run
    three hundred times is what fills the bench, and the characterisation
    run forty times at ten times the price is what pays for it. Ranking by
    one and showing the other silently would make the *set* wrong -- an
    offering can miss the top eight by count and still be the second-most
    valuable thing the lab sells -- so the ordering and the fold into
    "other" move together.
    """
    today = today or datetime.date.today()
    (start, end), (previous_start, previous_end) = resolve_window(date_from, date_to, today=today)

    pricer = Pricer()
    current = _totals(start, end, pricer)
    previous = _totals(previous_start, previous_end, pricer)

    offerings = {
        offering.id: offering
        for offering in ServiceOffering.objects.filter(id__in=current["per_offering"].keys())
    }
    rows = [
        {
            "offering_id": offering_id,
            "code": offerings[offering_id].code,
            "name": offerings[offering_id].name,
            "service_line": offerings[offering_id].service_line,
            "request_count": totals["count"],
            "list_value_net": str(totals["net"].quantize(Decimal("0.01"))),
        }
        for offering_id, totals in current["per_offering"].items()
    ]
    if rank == "value":
        leading = sorted(rows, key=lambda row: (-Decimal(row["list_value_net"]), row["code"]))
    else:
        leading = sorted(rows, key=lambda row: (-row["request_count"], row["code"]))

    mix = (
        Sample.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
        .values("service_line")
        .annotate(sample_count=Count("id"))
        .order_by("-sample_count")
    )

    return {
        "rank": rank,
        "window": {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "days": (end - start).days + 1,
            "previous_from": previous_start.isoformat(),
            "previous_to": previous_end.isoformat(),
        },
        "totals": {
            "samples_received": current["samples_received"],
            "test_requests": current["test_requests"],
            "list_value_net": str(current["list_value_net"].quantize(Decimal("0.01"))),
            "currency": "PHP",
        },
        "previous_totals": {
            "samples_received": previous["samples_received"],
            "test_requests": previous["test_requests"],
            "list_value_net": str(previous["list_value_net"].quantize(Decimal("0.01"))),
        },
        # Truncated for the chart, with the remainder folded into one row
        # rather than a ninth colour -- see the dashboard screen.
        "leading_analyses": leading[:leading_limit],
        "leading_analyses_other": {
            "offering_count": max(0, len(leading) - leading_limit),
            "request_count": sum(row["request_count"] for row in leading[leading_limit:]),
            "list_value_net": str(
                sum(
                    (Decimal(row["list_value_net"]) for row in leading[leading_limit:]),
                    Decimal("0.00"),
                ).quantize(Decimal("0.01"))
            ),
        },
        "unattributed_requests": current["unattributed"],
        "service_line_mix": [
            {
                "service_line": row["service_line"],
                "label": dict(ServiceLine.choices).get(row["service_line"], row["service_line"]),
                "sample_count": row["sample_count"],
            }
            for row in mix
        ],
        "monthly": [
            {
                "month": month,
                "request_count": current["per_month"].get(month, {}).get("count", 0),
                "list_value_net": str(
                    current["per_month"].get(month, {}).get("net", Decimal("0.00")).quantize(Decimal("0.01"))
                ),
            }
            for month in _months_in(start, end)
        ],
        "turnaround": _turnaround(start, end),
        "quality": _quality(start, end),
    }
