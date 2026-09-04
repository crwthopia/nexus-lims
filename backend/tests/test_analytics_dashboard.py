"""
The dashboard's aggregation.

The figures are easy; the honesty is the hard part, and that is what these
pin:

- **List value is priced at the rate in force on the day the work was
  requested**, not today's rate. A price rise in July must not retroactively
  revalue April's work -- which is the whole reason prices are versioned.
- **A request that cannot be attributed to one offering is counted, not
  dropped and not spread.** A method sold both standalone and inside a panel
  is genuinely ambiguous without order lines; quietly picking one would
  invent a number, and dropping it would understate the bench.
- **Queue depths are "now", not "in the window".** Counting open
  investigations over a past period means nothing.
"""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.analytics import services
from apps.catalogue.models import OfferingPrice
from apps.review.models import ApprovalAction
from apps.samples.models import Sample
from tests.factories import (
    InstrumentFactory,
    InvestigationFactory,
    SampleFactory,
    ServiceOfferingFactory,
    StaffUserFactory,
    TestMethodFactory,
    TestRequestFactory,
    TestResultFactory,
)

pytestmark = pytest.mark.django_db

EXCLUSIVE = OfferingPrice.VatTreatment.EXCLUSIVE
TODAY = datetime.date(2026, 9, 1)


def priced_offering(price="1000.00", *, effective_from=datetime.date(2026, 1, 1), methods=(), **kwargs):
    offering = ServiceOfferingFactory(**kwargs)
    if methods:
        offering.test_methods.set(methods)
    from apps.catalogue.services import set_price

    set_price(
        offering,
        amount=Decimal(price),
        vat_treatment=EXCLUSIVE,
        vat_rate_pct=Decimal("12.00"),
        effective_from=effective_from,
    )
    return offering


def request_on(day, method, **kwargs):
    """A TestRequest with created_at forced -- auto_now_add ignores the kwarg."""
    test_request = TestRequestFactory(test_method=method, **kwargs)
    stamp = timezone.make_aware(datetime.datetime.combine(day, datetime.time(9, 0)))
    type(test_request).objects.filter(pk=test_request.pk).update(created_at=stamp)
    return test_request


def dashboard(**kwargs):
    kwargs.setdefault("today", TODAY)
    kwargs.setdefault("date_from", datetime.date(2026, 6, 1))
    kwargs.setdefault("date_to", TODAY)
    return services.dashboard(**kwargs)


# --- attribution and pricing ----------------------------------------------


def test_it_ranks_offerings_by_request_count():
    bod, tss = TestMethodFactory(name="BOD"), TestMethodFactory(name="TSS")
    priced_offering(code="WQ-BOD5", methods=[bod])
    priced_offering(code="WQ-TSS", methods=[tss])
    for _ in range(3):
        request_on(datetime.date(2026, 7, 1), bod)
    request_on(datetime.date(2026, 7, 1), tss)

    leading = dashboard()["leading_analyses"]

    assert [(row["code"], row["request_count"]) for row in leading] == [("WQ-BOD5", 3), ("WQ-TSS", 1)]


def test_work_is_valued_at_the_rate_in_force_when_it_was_requested():
    """A July rise must not revalue April's work -- the point of versioned prices."""
    from apps.catalogue.services import set_price

    method = TestMethodFactory()
    offering = priced_offering("1000.00", effective_from=datetime.date(2026, 1, 1), methods=[method])
    set_price(
        offering, amount=Decimal("2000.00"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("12.00"),
        effective_from=datetime.date(2026, 8, 1),
    )
    request_on(datetime.date(2026, 7, 15), method)  # at 1,000
    request_on(datetime.date(2026, 8, 15), method)  # at 2,000

    result = dashboard()

    assert result["totals"]["list_value_net"] == "3000.00"


def test_the_value_is_net_of_vat_however_the_rate_was_quoted():
    """1,120 inclusive is 1,000 of work, the same as 1,000 exclusive."""
    from apps.catalogue.services import set_price

    method = TestMethodFactory()
    offering = ServiceOfferingFactory()
    offering.test_methods.set([method])
    set_price(
        offering, amount=Decimal("1120.00"), vat_treatment=OfferingPrice.VatTreatment.INCLUSIVE,
        vat_rate_pct=Decimal("12.00"), effective_from=datetime.date(2026, 1, 1),
    )
    request_on(datetime.date(2026, 7, 1), method)

    assert dashboard()["totals"]["list_value_net"] == "1000.00"


def test_a_method_in_no_offering_is_reported_rather_than_dropped():
    orphan = TestMethodFactory(name="Unmapped")
    request_on(datetime.date(2026, 7, 1), orphan)

    result = dashboard()

    assert result["totals"]["test_requests"] == 1
    assert result["unattributed_requests"]["no_offering"] == 1
    assert result["leading_analyses"] == []
    assert result["totals"]["list_value_net"] == "0.00"


def test_a_method_sold_two_ways_is_ambiguous_rather_than_guessed():
    """BOD standalone and BOD inside a panel: without order lines, nothing says which was sold."""
    bod = TestMethodFactory(name="BOD")
    priced_offering(code="WQ-BOD5", methods=[bod])
    priced_offering(code="WQ-POT", methods=[bod])
    request_on(datetime.date(2026, 7, 1), bod)

    result = dashboard()

    assert result["unattributed_requests"]["ambiguous"] == 1
    assert result["leading_analyses"] == []


def test_an_attributable_but_unpriced_request_still_counts_toward_volume():
    method = TestMethodFactory()
    offering = ServiceOfferingFactory(code="WQ-NEW")
    offering.test_methods.set([method])  # no price ever set
    request_on(datetime.date(2026, 7, 1), method)

    result = dashboard()

    assert result["unattributed_requests"]["unpriced"] == 1
    assert [(row["code"], row["request_count"], row["list_value_net"]) for row in result["leading_analyses"]] == [
        ("WQ-NEW", 1, "0.00")
    ]


def test_a_withdrawn_offering_stops_attracting_new_work():
    method = TestMethodFactory()
    priced_offering(code="WQ-OLD", methods=[method], is_active=False)
    request_on(datetime.date(2026, 7, 1), method)

    assert dashboard()["unattributed_requests"]["no_offering"] == 1


def test_the_tail_is_folded_into_one_row_rather_than_a_ninth_colour():
    for index in range(10):
        method = TestMethodFactory(name=f"M{index}")
        priced_offering(code=f"WQ-{index:03d}", methods=[method])
        request_on(datetime.date(2026, 7, 1), method)

    result = dashboard()

    assert len(result["leading_analyses"]) == 8
    assert result["leading_analyses_other"]["offering_count"] == 2
    assert result["leading_analyses_other"]["request_count"] == 2


# --- windows ---------------------------------------------------------------


def test_the_comparison_window_is_the_period_immediately_before():
    (start, end), (previous_start, previous_end) = services.resolve_window(
        datetime.date(2026, 8, 1), datetime.date(2026, 8, 30), today=TODAY
    )

    assert (end - start).days == (previous_end - previous_start).days
    assert previous_end == datetime.date(2026, 7, 31)
    assert previous_start == datetime.date(2026, 7, 2)


def test_work_outside_the_window_is_excluded_and_counted_in_the_previous_one():
    method = TestMethodFactory()
    priced_offering(methods=[method])
    request_on(datetime.date(2026, 7, 1), method)
    request_on(datetime.date(2026, 5, 1), method)

    result = dashboard(date_from=datetime.date(2026, 6, 1), date_to=datetime.date(2026, 7, 31))

    assert result["totals"]["test_requests"] == 1
    assert result["previous_totals"]["test_requests"] == 1


def test_a_quiet_month_is_a_zero_rather_than_a_gap():
    method = TestMethodFactory()
    priced_offering(methods=[method])
    request_on(datetime.date(2026, 8, 3), method)

    months = dashboard()["monthly"]

    assert [row["month"] for row in months] == ["2026-06", "2026-07", "2026-08", "2026-09"]
    assert [row["request_count"] for row in months] == [0, 0, 1, 0]


# --- turnaround and quality ------------------------------------------------


def test_turnaround_measures_arrival_to_approval():
    sample = SampleFactory(status=Sample.Status.UNDER_REVIEW)
    Sample.objects.filter(pk=sample.pk).update(
        created_at=timezone.make_aware(datetime.datetime(2026, 7, 1, 8, 0))
    )
    approval = ApprovalAction.objects.create(
        sample=sample, approver=StaffUserFactory(roles=["approver"]), disposition=ApprovalAction.Disposition.APPROVED
    )
    ApprovalAction.objects.filter(pk=approval.pk).update(
        created_at=timezone.make_aware(datetime.datetime(2026, 7, 5, 8, 0))
    )

    turnaround = dashboard()["turnaround"]

    assert turnaround["sample_count"] == 1
    assert turnaround["median_days"] == 4.0
    assert turnaround["by_service_line"][0]["service_line"] == sample.service_line


def test_turnaround_is_none_rather_than_zero_when_nothing_was_approved():
    assert dashboard()["turnaround"]["median_days"] is None


def test_the_out_of_spec_rate_is_none_rather_than_zero_when_nothing_was_measured():
    assert dashboard()["quality"]["out_of_spec_pct"] is None


def test_the_out_of_spec_rate_is_a_share_of_results_entered():
    method = TestMethodFactory()
    test_request = TestRequestFactory(test_method=method)
    TestResultFactory(test_request=test_request, is_out_of_spec=True)
    for _ in range(3):
        TestResultFactory(test_request=test_request, is_out_of_spec=False)

    quality = dashboard(date_from=datetime.date(2026, 1, 1), date_to=datetime.date(2027, 1, 1))["quality"]

    assert (quality["results_entered"], quality["out_of_spec"], quality["out_of_spec_pct"]) == (4, 1, 25.0)


def test_queue_depths_are_current_state_not_window_totals():
    """An investigation opened last year is still open today, and that is the point."""
    InvestigationFactory(status="open")
    SampleFactory(status=Sample.Status.UNDER_REVIEW)
    InstrumentFactory(status="out_of_calibration")

    quality = dashboard(date_from=datetime.date(2026, 8, 1), date_to=datetime.date(2026, 8, 2))["quality"]

    assert quality["open_investigations"] == 1
    assert quality["samples_awaiting_review"] == 1
    assert quality["instruments_out_of_calibration"] == 1


# --- endpoint --------------------------------------------------------------


def test_the_endpoint_needs_a_session(api_client):
    assert api_client.get("/api/v1/analytics/dashboard/").status_code in (401, 403)


def test_any_staff_member_can_read_it(login_as_staff):
    client = login_as_staff(StaffUserFactory(roles=["analyst"]))

    response = client.get("/api/v1/analytics/dashboard/")

    assert response.status_code == 200
    assert response.data["window"]["days"] == services.DEFAULT_WINDOW_DAYS


def test_a_malformed_date_is_a_400_not_a_500(login_as_staff):
    client = login_as_staff(StaffUserFactory())

    response = client.get("/api/v1/analytics/dashboard/?from=last-tuesday")

    assert response.status_code == 400
    assert "from" in response.data


# --- ranking ---------------------------------------------------------------


def _volume_and_value_fixture():
    """
    Two offerings with opposite standings: one run often at a low rate, one
    run rarely at a high one. Which is "leading" depends entirely on the
    question, which is why the endpoint takes a rank.
    """
    cheap_method, dear_method = TestMethodFactory(name="BOD"), TestMethodFactory(name="SEM")
    priced_offering("100.00", code="WQ-CHEAP", methods=[cheap_method])
    priced_offering("10000.00", code="FA-DEAR", methods=[dear_method])
    for _ in range(10):
        request_on(datetime.date(2026, 7, 1), cheap_method)  # 10 x 100 = 1,000
    request_on(datetime.date(2026, 7, 1), dear_method)  # 1 x 10,000


def test_ranking_by_volume_leads_with_the_busy_offering():
    _volume_and_value_fixture()

    leading = dashboard(rank="volume")["leading_analyses"]

    assert [row["code"] for row in leading] == ["WQ-CHEAP", "FA-DEAR"]


def test_ranking_by_value_leads_with_the_valuable_one():
    _volume_and_value_fixture()

    leading = dashboard(rank="value")["leading_analyses"]

    assert [row["code"] for row in leading] == ["FA-DEAR", "WQ-CHEAP"]


def test_the_fold_into_other_follows_the_ranking():
    """
    An offering can miss the top by count and still be the most valuable
    thing on the card -- so the tail has to be computed against whichever
    measure is ranking, not always against volume.
    """
    busy = TestMethodFactory(name="Busy")
    priced_offering("1.00", code="WQ-BUSY", methods=[busy])
    for _ in range(50):
        request_on(datetime.date(2026, 7, 1), busy)
    for index in range(8):
        method = TestMethodFactory(name=f"Dear {index}")
        priced_offering("5000.00", code=f"FA-{index:03d}", methods=[method])
        request_on(datetime.date(2026, 7, 1), method)

    by_value = dashboard(rank="value")

    assert [row["code"] for row in by_value["leading_analyses"]] == [f"FA-{i:03d}" for i in range(8)]
    assert by_value["leading_analyses_other"]["request_count"] == 50


def test_a_misspelled_rank_shows_the_default_view_rather_than_an_error(login_as_staff):
    client = login_as_staff(StaffUserFactory())

    response = client.get("/api/v1/analytics/dashboard/?rank=nonsense")

    assert response.status_code == 200
    assert response.data["rank"] == "volume"
