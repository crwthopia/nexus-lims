"""
Report PDF generation (Blueprint Section 2.1a).

The decoupled pipeline the Report model has always pointed at: render the
Jinja2 template selected by report_type (apps/reporting/rendering.py), hand
the HTML to WeasyPrint, put the resulting bytes in object storage, and record
the key on Report.file_id.

Asynchronous rather than inline in the POST handler. A COA renders in
hundreds of milliseconds for a small sample and seconds for one with many
results, and holding a request open for that is how a report screen becomes
the slowest page in the application. The client creates a Report, gets back
`pending`, and polls -- or opens the download endpoint, which reports the
job's state rather than blocking.
"""

import logging

from celery import shared_task
from django.db import transaction
from weasyprint import HTML

from apps.audit.oss import upload_object
from apps.reporting.models import Report
from apps.reporting.rendering import TEMPLATE_DIR, ReportTemplateMissing, render_report_html

logger = logging.getLogger(__name__)


def build_report_context(report):
    """
    The context every report template is rendered against.

    This is the contract a QA-authored template writes to, so it is built
    explicitly here rather than by handing templates the ORM objects: a
    template that can follow arbitrary relations can issue queries, and a
    document that renders differently depending on what is prefetched is not
    something to put a QA signature on.
    """
    sample = report.sample
    order = report.order

    results = []
    if sample is not None:
        # One pass over the sample's results, ordered so the document is
        # stable between regenerations of the same report.
        for test_request in sample.test_requests.select_related("test_method").order_by("id"):
            for result in test_request.results.select_related("entered_by").order_by("id"):
                limits = test_request.test_method.specification_limits or {}
                results.append(
                    {
                        "analyte": result.analyte,
                        "method": test_request.test_method.name,
                        "method_reference": test_request.test_method.method_reference,
                        "value": result.value,
                        "unit": result.unit,
                        "spec": _describe_limits(limits),
                        "is_out_of_spec": result.is_out_of_spec,
                        "analyst": getattr(result.entered_by, "display_name", ""),
                    }
                )

    reviewed_by = "—"
    approved_by = "—"
    if sample is not None:
        review = sample.review_actions.select_related("reviewer").order_by("-created_at").first()
        approval = sample.approval_actions.select_related("approver").order_by("-created_at").first()
        if review is not None:
            reviewed_by = review.reviewer.display_name
        if approval is not None:
            approved_by = approval.approver.display_name

    return {
        "report": report,
        "sample": sample,
        "order": order,
        "results": results,
        "reviewed_by": reviewed_by,
        "approved_by": approved_by,
        "customer": getattr(getattr(order, "customer", None), "email", None),
        "generated_by": report.generated_by.display_name,
    }


def _describe_limits(limits):
    """Renders a TestMethod.specification_limits JSON blob as one cell of text."""
    if not limits:
        return ""
    low, high = limits.get("min"), limits.get("max")
    if low is not None and high is not None:
        return f"{low} – {high}"
    if high is not None:
        return f"≤ {high}"
    if low is not None:
        return f"≥ {low}"
    return ", ".join(f"{k}: {v}" for k, v in limits.items())


def object_key_for(report):
    """
    Deterministic per report *version*, so regenerating a report at the same
    version overwrites rather than orphaning objects in the bucket, while a
    corrected report (a new row with an incremented version, FR-E17-01/03)
    lands at its own key and never overwrites the document already issued.
    """
    return f"reports/{report.report_type}/{report.id}-v{report.version}.pdf"


@shared_task(name="apps.reporting.tasks.generate_report_pdf")
def generate_report_pdf(report_id):
    """
    Renders and stores the PDF for `report_id`. Returns the OSS key.

    Failure is recorded on the row (status=failed, failure_reason) *and*
    re-raised: the row is what the Reports screen reads, and the exception is
    what makes the failure visible in Celery's own results and monitoring.
    Swallowing it would leave a report stuck at `generating` with nothing
    anywhere saying why.
    """
    report = Report.objects.select_related("sample", "order", "generated_by").get(pk=report_id)

    # save(update_fields=...) rather than QuerySet.update(): .update() sends
    # no signals, so these transitions were invisible to both the audit log
    # (apps/audit/signals.py) and simple-history -- a report went pending ->
    # generating -> ready and left exactly one history row, recording only
    # 'pending'. update_fields keeps the narrow write .update() gave us, so a
    # concurrent change to another column is still not clobbered.
    report.status = Report.Status.GENERATING
    report.failure_reason = ""
    report.save(update_fields=["status", "failure_reason"])

    try:
        html = render_report_html(report, build_report_context(report))
        # base_url lets a template reference a local asset (a letterhead, a
        # signature block) by relative path once QA supplies real ones.
        pdf_bytes = HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf()
        key = upload_object(object_key_for(report), pdf_bytes, content_type="application/pdf")
    except ReportTemplateMissing as exc:
        _mark_failed(report, str(exc))
        logger.error("report %s: %s", report.pk, exc)
        raise
    except Exception as exc:  # noqa: BLE001 -- recorded on the row, then re-raised
        _mark_failed(report, f"{type(exc).__name__}: {exc}")
        logger.exception("report %s failed to generate", report.pk)
        raise

    report.file_id = key
    report.status = Report.Status.READY
    report.failure_reason = ""
    report.save(update_fields=["file_id", "status", "failure_reason"])
    logger.info("report %s ready at %s (%d bytes)", report.pk, key, len(pdf_bytes))
    return key


def _mark_failed(report, reason):
    report.status = Report.Status.FAILED
    report.failure_reason = reason[:2000]
    report.save(update_fields=["status", "failure_reason"])


def enqueue_generation(report):
    """
    Dispatches generation after the creating transaction commits.

    Without on_commit the worker can pick the task up before the Report row is
    visible to it and fail with DoesNotExist -- the classic Celery-with-Django
    race, and one that only shows up under load.
    """
    transaction.on_commit(lambda: generate_report_pdf.delay(report.pk))
