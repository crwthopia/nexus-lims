"""
Message bodies, built at send time from the entity rather than stored.

Two reasons the body is derived here and not written down when the
notification is queued:

**Confidentiality.** A report-ready notice is addressed to a customer, and
ISO/IEC 17025:2017 4.2 makes the lab responsible for their information.
Storing the rendered body would copy it into a staff-readable table for no
benefit -- NotificationRecord answers "who was told what, and when" without
it.

**Staleness.** A queued message rendered an hour ago can describe a record
that has since been corrected. Deriving at send time means the message
matches the row it is about, or fails loudly because the row is gone.

Nothing here puts a *result* in an email. A customer is told a report is
ready and given a link into the Customer Portal, where the session, the
role checks and the RLS policies all still apply; email is not a channel
the lab controls once it has left. Staff messages name the record and link
to the Staff Console for the same reason -- an OOS value in a mailbox is an
uncontrolled copy of a regulated measurement.
"""

from django.conf import settings

from apps.notifications.models import NotificationRecord

Kind = NotificationRecord.Kind


# Customer-facing wording for the milestones a customer is told about. The
# lab's own status names ("in_testing", "approved") are internal vocabulary;
# a customer should not have to learn the FSM to read their email.
MILESTONE_WORDING = {
    "received": "has arrived at the laboratory",
    "in_testing": "is now being analysed",
    "approved": "has completed analysis and the results are approved",
    "disposed": "has been disposed of, ending the laboratory's custody",
}


class NotificationEntityGone(Exception):
    """The record a queued notification described no longer exists."""


def _staff_console_url(path):
    base = getattr(settings, "STAFF_CONSOLE_BASE_URL", "").rstrip("/")
    return f"{base}{path}" if base else path


def _portal_url(path):
    base = getattr(settings, "CUSTOMER_PORTAL_BASE_URL", "").rstrip("/")
    return f"{base}{path}" if base else path


def _entity(record, model):
    instance = model.objects.filter(pk=record.entity_id).first()
    if instance is None:
        raise NotificationEntityGone(
            f"{record.entity_type}#{record.entity_id} no longer exists; not sending {record.kind}"
        )
    return instance


# --- Staff -----------------------------------------------------------------

def _system_failure(record):
    from apps.audit.models import SystemFailure

    failure = _entity(record, SystemFailure)
    return (
        f"A system failure was recorded and needs a corrective action.\n\n"
        f"Component:        {failure.get_component_display()}\n"
        f"Severity:         {failure.get_severity_display()}\n"
        f"What failed:      {failure.summary}\n"
        f"Immediate action: {failure.get_immediate_action_display()}\n\n"
        f"The immediate action above is what the system did by itself. The corrective "
        f"action -- what stops it happening again -- has to be recorded by a person "
        f"before the failure can be closed (ISO/IEC 17025:2017 7.11.3(e)).\n\n"
        f"{_staff_console_url('/system-failures')}\n"
    )


def _open_failure_digest(record):
    from apps.audit.models import SystemFailure

    open_failures = SystemFailure.objects.exclude(status=SystemFailure.Status.CLOSED).order_by("-last_seen_at")
    lines = [
        f"  - [{f.get_severity_display()}] {f.get_component_display()}: {f.summary} "
        f"(x{f.occurrences}, last seen {f.last_seen_at:%Y-%m-%d %H:%M})"
        for f in open_failures[:50]
    ]
    remaining = max(open_failures.count() - 50, 0)
    if remaining:
        lines.append(f"  ...and {remaining} more.")

    return (
        f"System failures still open, with no corrective action recorded:\n\n"
        + "\n".join(lines)
        + f"\n\n{_staff_console_url('/system-failures')}\n"
    )


def _calibration_due(record):
    from apps.equipment.models import Instrument

    instrument = _entity(record, Instrument)
    return (
        f"{instrument.name} is due for calibration.\n\n"
        f"Instrument: {instrument.name} ({instrument.get_model_display()})\n"
        f"Due:        {instrument.calibration_due_date:%Y-%m-%d}\n"
        f"Status:     {instrument.get_status_display()}\n\n"
        f"An instrument past its calibration date should not be producing reportable "
        f"results (ISO/IEC 17025:2017 6.4). Record the calibration in the Staff Console "
        f"once it is done:\n\n"
        f"{_staff_console_url(f'/equipment/instruments/{instrument.id}')}\n"
    )


def _investigation_opened(record):
    from apps.investigations.models import Investigation

    investigation = _entity(record, Investigation)
    subject_of = (
        investigation.related_sample.unique_sample_code
        if investigation.related_sample
        else f"Test Result #{investigation.related_test_result_id}"
    )
    return (
        f"An investigation was opened and needs a root cause and CAPA.\n\n"
        f"Investigation: #{investigation.id} ({investigation.get_type_display()})\n"
        f"Concerning:    {subject_of}\n"
        f"Opened by:     {investigation.opened_by.display_name}\n\n"
        f"Nonconforming work has to be evaluated and, where needed, corrected "
        f"(ISO/IEC 17025:2017 7.10).\n\n"
        f"{_staff_console_url(f'/investigations/{investigation.id}')}\n"
    )


def _result_out_of_spec(record):
    from apps.testing.models import TestResult

    result = _entity(record, TestResult)
    # The value itself is deliberately absent -- see the module docstring.
    return (
        f"A test result was flagged out of specification on entry (FR-C3-08).\n\n"
        f"Test Result: #{result.id}\n"
        f"Method:      {result.test_request.test_method.name}\n"
        f"Sample:      {result.test_request.sample.unique_sample_code}\n"
        f"Entered by:  {result.entered_by.display_name if result.entered_by else 'system'}\n\n"
        f"The measured value is not reproduced here; open the result in the Staff "
        f"Console to review it and decide whether an investigation is warranted "
        f"(ISO/IEC 17025:2017 7.10).\n\n"
        f"{_staff_console_url(f'/test-requests/{result.test_request_id}')}\n"
    )


# --- Customer --------------------------------------------------------------

def _sample_progress(record):
    from apps.samples.models import Sample

    sample = _entity(record, Sample)
    # The milestone as it was when this was queued, not as the sample is now
    # -- a sample can move twice before a worker picks the row up, and the
    # message has to match the subject it was sent under.
    status = record.context.get("status", sample.status)
    milestone = MILESTONE_WORDING.get(status, "moved to a new stage")

    return (
        f"Your sample {sample.unique_sample_code} {milestone}.\n\n"
        f"Sample:    {sample.unique_sample_code}\n"
        + (f"Your reference: {sample.client_reference}\n" if sample.client_reference else "")
        + f"\nYou can follow its progress in the NexusLIMS Customer Portal:\n\n"
        f"{_portal_url('/samples')}\n\n"
        f"Results are not included in this message and are never sent by email. "
        f"They are released through your account once the report is issued.\n"
    )


def _sample_progress_digest(record):
    from apps.samples.models import Order

    order = _entity(record, Order)
    status = record.context.get("status", "")
    count = record.context.get("count", 0)
    total = order.samples.count()
    milestone = MILESTONE_WORDING.get(status, "moved to a new stage")

    return (
        f"{count} of the {total} samples on order #{order.id} {milestone}.\n\n"
        f"Order:        #{order.id} ({order.get_service_line_display()})\n"
        f"Milestone:    {milestone}\n"
        f"Samples:      {count} of {total}\n\n"
        f"Per-sample detail is in the NexusLIMS Customer Portal:\n\n"
        f"{_portal_url('/samples')}\n\n"
        f"Results are not included in this message and are never sent by email. "
        f"They are released through your account once the report is issued.\n"
    )


def _report_ready(record):
    from apps.reporting.models import Report

    report = _entity(record, Report)
    return (
        f"Your {report.get_report_type_display()} is ready.\n\n"
        f"Sign in to the NexusLIMS Customer Portal to download it:\n\n"
        f"{_portal_url('/reports')}\n\n"
        f"The document is not attached to this email. It is available only through "
        f"your account, which is how it stays yours.\n"
    )


def _training_session_rescheduled(record):
    from apps.training.models import CreditNote, Enrollment

    enrollment = _entity(record, Enrollment)
    session = enrollment.session
    credit_note = CreditNote.objects.filter(source_enrollment=enrollment).first()

    return (
        f"The {session.course.title} session scheduled for {session.start_date:%Y-%m-%d} "
        f"did not meet the minimum enrollment requirement and has been rescheduled.\n\n"
        + (
            f"A credit note for {credit_note.amount} has been issued to your account, "
            f"redeemable against a future session.\n"
            if credit_note
            else "No payment was recorded against your enrollment, so no credit note was issued.\n"
        )
        + f"\n{_portal_url('/enrollments')}\n"
    )


def _customer_email_verification(record):
    from apps.accounts.customer_auth import generate_email_verification_token
    from apps.accounts.models import CustomerUser

    customer = _entity(record, CustomerUser)
    token = generate_email_verification_token(customer)
    hours = settings.CUSTOMER_EMAIL_VERIFICATION_MAX_AGE_SECONDS // 3600
    return (
        f"Welcome to NexusLIMS. Verify your email to activate your account:\n\n"
        f"{_portal_url(f'/verify-email?token={token}')}\n\n"
        f"(Raw token, valid {hours}h: {token})\n"
    )


def _customer_duplicate_registration(record):
    return (
        "Somebody just tried to create a NexusLIMS account with this email address, "
        "which already has one.\n\n"
        "If that was you, log in instead -- there is nothing to do here. If it was not, "
        "your account is unaffected and no action is required, but consider changing "
        "your password if you reuse it elsewhere.\n"
    )


BODY_BUILDERS = {
    Kind.SYSTEM_FAILURE: _system_failure,
    Kind.OPEN_FAILURE_DIGEST: _open_failure_digest,
    Kind.CALIBRATION_DUE: _calibration_due,
    Kind.INVESTIGATION_OPENED: _investigation_opened,
    Kind.RESULT_OUT_OF_SPEC: _result_out_of_spec,
    Kind.SAMPLE_PROGRESS: _sample_progress,
    Kind.SAMPLE_PROGRESS_DIGEST: _sample_progress_digest,
    Kind.REPORT_READY: _report_ready,
    Kind.TRAINING_SESSION_RESCHEDULED: _training_session_rescheduled,
    Kind.CUSTOMER_EMAIL_VERIFICATION: _customer_email_verification,
    Kind.CUSTOMER_DUPLICATE_REGISTRATION: _customer_duplicate_registration,
}


def build_body(record):
    """
    The body for `record`, or KeyError for a kind with no builder.

    A missing builder is deliberately not a silent empty email: a kind added
    to the enum without a message is a bug, and an empty notification is
    worse than a loud failure -- tests/test_notifications.py pins that every
    Kind has one.
    """
    return BODY_BUILDERS[record.kind](record)
