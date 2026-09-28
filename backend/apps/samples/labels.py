"""
Turning a sample into something you can stick on a bottle.

The pipeline is the report pipeline (Jinja2 template -> WeasyPrint -> PDF
bytes), reused rather than rebuilt, with two deliberate departures:

**Synchronous, not Celery.** A report renders in hundreds of milliseconds to
seconds and is retained, so it is worth a job and a poll. A label is one
small page and is printed by somebody standing at a receiving bench with a
cooler open in front of them. "Create a job, poll for it, then download"
is not a workflow anybody would use twice; they would write the code on
masking tape instead, which is the outcome this feature exists to prevent.

**Nothing is stored.** No Report row, no object-storage key, no retention.
A label is regenerated from the sample whenever it is wanted, so a stored
copy could only ever be a stale one -- and a *stale* label is worse than no
label, because it is a container confidently asserting something the record
no longer says. What is recorded is the print *event*
(apps.samples.models.LabelPrintEvent); the PDF is disposable.

Context is built explicitly here rather than by handing templates the ORM
objects, for the same reason apps/reporting/tasks.build_report_context does
it: a template that can follow arbitrary relations can issue queries, and a
document that renders differently depending on what was prefetched is not
one to put on a physical container.
"""

from django.conf import settings
from django.utils import timezone
from weasyprint import HTML

from apps.reporting.barcodes import code128_data_uri, qr_data_uri
from apps.reporting.rendering import LABEL_TEMPLATE_DIR, render_label_html
from apps.testing.holding_times import OUTSTANDING_STATUSES
from apps.testing.models import TestRequest

# How much of the label's width the barcode may occupy, after the page
# margin on both sides. Passed to the barcode so it can shrink to fit or
# refuse -- see apps/reporting/barcodes.py.
def _barcode_max_width_mm():
    return settings.LABEL_WIDTH_MM - 2 * settings.LABEL_MARGIN_MM


def _page_context():
    """The stock the labels are printed on, which is a printer property rather than a document one."""
    return {
        "page_size": f"{settings.LABEL_WIDTH_MM}mm {settings.LABEL_HEIGHT_MM}mm",
        "page_margin": f"{settings.LABEL_MARGIN_MM}mm",
    }


def _barcode_for(code):
    """
    The barcode and the exact size it must be drawn at.

    Both dimensions travel with the URI because the template has to pin
    both: everything apps/reporting/barcodes.py guarantees is a statement
    about the bar width in millimetres, and CSS that sets one axis lets the
    renderer scale the other -- which multiplies that bar width by the
    ratio and quietly takes it below what a scanner can read.
    """
    uri, width_mm, height_mm = code128_data_uri(
        code, max_width_mm=_barcode_max_width_mm(), height_mm=settings.LABEL_BARCODE_HEIGHT_MM,
    )
    return {
        "barcode_uri": uri,
        "barcode_width": f"{width_mm}mm",
        "barcode_height": f"{height_mm}mm",
    }


def earliest_deadline(sample):
    """
    The soonest holding-time deadline across the sample's outstanding work,
    as `(due_at, basis, expired)` -- basis being the raw
    TestRequest.DueBasis value, so callers can decide how loudly to say it.

    A container is one physical thing with several analyses queued against
    it, so the date that belongs on its side is the first one that bites --
    print the latest and the short-hold analysis is quietly lost.
    Completed and abandoned work is excluded: a deadline that has already
    been met is not a reason to keep a container flagged.
    """
    upcoming = [
        tr for tr in sample.test_requests.all()
        if tr.due_at is not None and tr.status in OUTSTANDING_STATUSES
    ]
    if not upcoming:
        return None, "", False

    soonest = min(upcoming, key=lambda tr: tr.due_at)
    return soonest.due_at, soonest.due_at_basis, soonest.due_at < timezone.now()


def _render(template_name, context, *, page_context=None):
    html = render_label_html(template_name, {**(page_context or _page_context()), **context})
    # base_url so a QA-authored template can reference a letterhead or a
    # hazard glyph by relative path once real artwork lands.
    return HTML(string=html, base_url=str(LABEL_TEMPLATE_DIR)).write_pdf()


def _container_entries(sample, *, copies=None):
    """One entry per physical container of `sample`."""
    total = copies or sample.container_count or 1
    barcode = _barcode_for(sample.unique_sample_code)
    due_at, due_basis, expired = earliest_deadline(sample)
    receipt = getattr(sample, "receipt", None)

    return [
        {
            **barcode,
            "sample": sample,
            "index": index,
            "total": total,
            "due_at": due_at,
            # Only the fallback is annotated. A deadline counted from
            # collection is the correct one and needs no note; one counted
            # from receipt is optimistic by however long the item spent in
            # transit, and that is worth a line on a 25mm label. Annotating
            # both wrapped the date onto a second line and pushed the
            # metadata onto a second page.
            "due_basis_note": (
                "from receipt" if due_basis == TestRequest.DueBasis.RECEIPT else ""
            ),
            "expired": expired,
            "preservation": sample.preservation_method,
            "storage_location": receipt.storage_location if receipt else "",
        }
        for index in range(1, total + 1)
    ]


def render_container_labels(samples, *, copies=None):
    """
    Container labels for one sample or many, as `(pdf_bytes, page_count)`.

    Takes a list rather than a single sample because booking in a delivery
    is the ordinary case and printing twelve labels one PDF at a time is
    not a thing anybody does twice -- so the bulk path is the only path,
    and a single sample is a batch of one. One WeasyPrint render for the
    whole batch, not a PDF merge: the pages are already pages of the same
    document.

    Page count defaults to each sample's `container_count`, because that is
    what the sample says arrived. Asking an operator to type "3" into a box
    that already knows the answer is how the wrong number gets typed.
    """
    entries = []
    for sample in samples:
        entries.extend(_container_entries(sample, copies=copies))

    title = (
        samples[0].unique_sample_code if len(samples) == 1
        else f"{len(samples)} samples"
    )
    return _render("container_label.html", {
        "labels": entries,
        "document_title": title,
    }), len(entries)


def render_worksheet_labels(test_request, *, copies=1):
    """
    A label for the portion taken to run one analysis.

    The barcode still carries the *parent* sample code: results, review and
    the report all hang off the sample, so scanning an aliquot has to land
    on the same record a container scan does (ISO/IEC 17025:2017 7.4.2 on
    subdivision). The suffix distinguishing the tubes is for the person
    holding them, and is derived from the test request id rather than
    stored -- it identifies the analysis, which already has an identity.
    """
    sample = test_request.sample
    analyst = test_request.assigned_analyst
    instrument = test_request.assigned_instrument

    return _render("worksheet_label.html", {
        **_barcode_for(sample.unique_sample_code),
        "sample": sample,
        "test_method": test_request.test_method,
        "aliquot_suffix": f"/{test_request.id}",
        "copies": range(copies),
        "due_at": test_request.due_at,
        "expired": test_request.is_overdue,
        "analyst": analyst.display_name if analyst else "Unassigned",
        "instrument": instrument.name if instrument else "",
    }), copies


def _analyses_for(sample):
    """
    The sample's analyses in the order they have to be run.

    Sorted by deadline, soonest first, with undated work last -- the same
    order the testing queue uses (apps/testing/views.py `_QUEUE_ORDER`), so
    the sheet on the bench and the screen beside it never disagree about
    what to do next. Priority is not a factor here: this sheet covers one
    order, and every sample on it shares the customer's urgency.
    """
    def sort_key(tr):
        return (tr.due_at is None, tr.due_at or timezone.now(), tr.id)

    return [
        {
            "name": tr.test_method.name,
            "method_reference": tr.test_method.method_reference,
            "due_at": tr.due_at,
            "expired": tr.is_overdue,
            "analyst": tr.assigned_analyst.display_name if tr.assigned_analyst else "",
        }
        for tr in sorted(sample.test_requests.all(), key=sort_key)
    ]


def _sample_entry(sample):
    receipt = getattr(sample, "receipt", None)
    return {
        "sample": sample,
        "priority_label": sample.get_priority_display(),
        "analyses": _analyses_for(sample),
        "deviations": receipt.deviation_reasons if receipt else [],
        "consultation_outcome": receipt.consultation_outcome if receipt else "",
        "disclaimer_text": receipt.disclaimer_text if receipt and receipt.report_disclaimer_required else "",
    }


def render_job_order(order, *, printed_by):
    """
    The A4 sheet that travels with the work: what was ordered, what
    condition it arrived in, and somewhere for the courier and the receiving
    officer to sign.

    Printed rather than only stored because the two signatures are the point
    -- a custody handover happens at a counter, between people, and asking a
    courier to authenticate to a web application to acknowledge it is not a
    process any laboratory runs.
    """
    samples = list(
        order.samples.select_related("receipt")
        .prefetch_related("test_requests__test_method", "test_requests__assigned_analyst")
        .order_by("unique_sample_code")
    )

    console = getattr(settings, "STAFF_CONSOLE_BASE_URL", "").rstrip("/")
    qr_uri = qr_data_uri(f"{console}/orders/{order.id}") if console else ""

    return _render("job_order.html", {
        "order_reference": f"#{order.id}",
        "customer": order.customer.email if order.customer else "—",
        "service_line": order.get_service_line_display(),
        "sample_count": len(samples),
        "samples": [_sample_entry(sample) for sample in samples],
        "printed_at": timezone.now(),
        "printed_by": printed_by.display_name,
        "qr_uri": qr_uri,
    # page_context is empty: the job order is A4, fixed in the template,
    # and has no business inheriting the label stock's page size.
    }, page_context={})


class ReprintNeedsReason(Exception):
    """A label for this target has been printed before, and no reason was given."""


def record_print(*, kind, printed_by, copies, reason="", sample=None, order=None, test_request=None):
    """
    Write the LabelPrintEvent for a print that just happened, deciding for
    itself whether it was a reprint.

    `is_reprint` is looked up here rather than accepted from the caller,
    because the whole value of the field is that it cannot be opted out of:
    a client that could declare its own print a first print could produce
    unexplained duplicate identities indefinitely, which is precisely what
    ISO/IEC 17025:2017 7.4.2 is written to stop.

    A reprint without a reason raises rather than storing an empty string.
    The CHECK constraint would catch it too, as an IntegrityError quoting a
    constraint name at somebody holding a label printer; this makes it a
    400 that says what is wanted and why.
    """
    from apps.samples.models import LabelPrintEvent

    target = {"sample": sample, "order": order, "test_request": test_request}
    is_reprint = LabelPrintEvent.objects.filter(
        kind=kind, **{k: v for k, v in target.items() if v is not None}
    ).exists()

    if is_reprint and not reason.strip():
        raise ReprintNeedsReason(
            f"A {LabelPrintEvent.Kind(kind).label.lower()} has already been printed for this item. "
            "Re-printing needs a reason: two containers carrying the same identity, or a container "
            "whose label disagrees with the record, is what ISO/IEC 17025:2017 7.4.2 exists to prevent."
        )

    return LabelPrintEvent.objects.create(
        kind=kind,
        printed_by=printed_by,
        copies=copies,
        reason=reason.strip(),
        is_reprint=is_reprint,
        **target,
    )
