"""
Sending, and the two sweeps that decide there is something to send.

`send_notification` is the only place in the codebase that touches SMTP. A
failure here is a Celery task failure, which means `config/celery.py`'s
`task_failure` receiver records it in the SystemFailure register without
this module doing anything -- see the EMAIL component note there for why
that loop is safe.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.notifications.messages import NotificationEntityGone, build_body
from apps.notifications.models import NotificationRecord
from apps.notifications.notify import notify, notify_each, staff_emails_for_roles

logger = logging.getLogger(__name__)


@shared_task(name="apps.notifications.tasks.send_notification")
def send_notification(record_id):
    """
    Deliver one queued notification.

    Re-delivery is a no-op rather than a second email: Celery gives
    at-least-once delivery, so a task that succeeded and lost its ack would
    otherwise send twice. Checking the row is what makes that safe, and it
    is the same reason the row exists before the send rather than after.
    """
    record = NotificationRecord.objects.get(pk=record_id)

    if record.status == NotificationRecord.Status.SENT:
        logger.info("notification %s already sent at %s; not resending", record.pk, record.sent_at)
        return "already-sent"

    try:
        body = build_body(record)
    except NotificationEntityGone as exc:
        # The record it described is gone. Not an error: a notification about
        # a deleted row is one nobody should receive, and raising here would
        # retry forever against something that is not coming back.
        record.status = NotificationRecord.Status.FAILED
        record.failure_reason = str(exc)
        record.save(update_fields=["status", "failure_reason"])
        logger.warning("notification %s: %s", record.pk, exc)
        return "entity-gone"

    try:
        send_mail(
            subject=record.subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[record.recipient],
        )
    except Exception as exc:
        # Recorded on the row *and* re-raised, the same contract
        # apps/reporting/tasks.generate_report_pdf uses: the row is what the
        # register reads, and the exception is what makes it a task failure
        # and therefore a SystemFailure.
        record.status = NotificationRecord.Status.FAILED
        record.failure_reason = f"{type(exc).__name__}: {exc}"[:2000]
        record.save(update_fields=["status", "failure_reason"])
        logger.exception("notification %s failed to send", record.pk)
        raise

    record.status = NotificationRecord.Status.SENT
    record.sent_at = timezone.now()
    record.failure_reason = ""
    record.save(update_fields=["status", "sent_at", "failure_reason"])
    return "sent"


@shared_task(name="apps.notifications.tasks.sweep_calibration_due")
def sweep_calibration_due():
    """
    Chase instruments whose calibration is due (ISO/IEC 17025:2017 6.4).

    Runs nightly, which is only tolerable because of the dedupe key: without
    one this would mail the same custodian about the same instrument every
    night until somebody calibrated it, and the message would stop being
    read inside a week.

    The key includes the due date, so a *re-scheduled* calibration is a new
    notification rather than one suppressed by the old row. That is the
    behaviour you want -- the thing being chased has genuinely changed.

    Falls back to every Instrument Custodian when an instrument has no
    custodian set. An uncalibrated instrument with nobody named against it
    is more in need of a message, not less.
    """
    from apps.accounts.models import Role
    from apps.equipment.models import Instrument

    horizon = timezone.localdate() + timezone.timedelta(days=settings.CALIBRATION_DUE_WARNING_DAYS)
    due = (
        Instrument.objects.exclude(status=Instrument.Status.RETIRED)
        .exclude(calibration_due_date__isnull=True)
        .filter(calibration_due_date__lte=horizon)
        .select_related("custodian")
    )

    queued = 0
    for instrument in due:
        recipients = (
            [instrument.custodian.email]
            if instrument.custodian and instrument.custodian.is_active
            else staff_emails_for_roles(Role.RoleName.INSTRUMENT_CUSTODIAN)
        )
        if not recipients:
            logger.warning(
                "calibration sweep: instrument #%s is due %s but no custodian and no "
                "Instrument Custodian role holder exists to tell",
                instrument.id, instrument.calibration_due_date,
            )
            continue

        overdue = instrument.calibration_due_date < timezone.localdate()
        queued += len(
            notify_each(
                NotificationRecord.Kind.CALIBRATION_DUE,
                recipients,
                subject=(
                    f"NexusLIMS: {instrument.name} calibration "
                    f"{'is OVERDUE' if overdue else 'is due'} ({instrument.calibration_due_date:%Y-%m-%d})"
                ),
                dedupe_key=f"calibration-due:{instrument.id}:{instrument.calibration_due_date:%Y-%m-%d}",
                entity=instrument,
            )
        )

    logger.info("calibration sweep: %d instrument(s) due, %d notification(s) queued", due.count(), queued)
    return {"due": due.count(), "queued": queued}


@shared_task(name="apps.notifications.tasks.send_open_failure_digest")
def send_open_failure_digest():
    """
    A daily list of system failures still lacking a corrective action.

    The immediate alert (apps/audit/failures.py) fires only for `failed`
    severity, because a `degraded` dependency that retried successfully is
    not worth waking somebody for. This is where those show up instead --
    once a day, in one message, still open.

    Keyed on the date so one digest goes out per day no matter how often the
    task is run, and skipped entirely when nothing is open: a digest that
    arrives every morning saying "nothing" trains people to delete it
    unread, and then they delete the one that mattered.
    """
    from apps.accounts.models import Role
    from apps.audit.models import SystemFailure

    open_count = SystemFailure.objects.exclude(status=SystemFailure.Status.CLOSED).count()
    if not open_count:
        logger.info("open failure digest: nothing open, not sending")
        return {"open": 0, "queued": 0}

    recipients = staff_emails_for_roles(Role.RoleName.QA_OFFICER, Role.RoleName.LAB_SUPERVISOR)
    if not recipients:
        logger.warning("open failure digest: %d open but no QA Officer or Lab Supervisor to tell", open_count)
        return {"open": open_count, "queued": 0}

    today = timezone.localdate()
    queued = len(
        notify_each(
            NotificationRecord.Kind.OPEN_FAILURE_DIGEST,
            recipients,
            subject=f"NexusLIMS: {open_count} system failure(s) still open",
            dedupe_key=f"open-failure-digest:{today:%Y-%m-%d}",
        )
    )
    return {"open": open_count, "queued": queued}


def notify_system_failure(failure):
    """
    Immediate alert for a newly recorded system failure.

    Called from apps/audit/failures.record_failure on the *create* path only
    -- never on the coalescing path. That boundary is the whole reason the
    register deduplicates: a failing dependency probed every few seconds
    would otherwise be an email every few seconds, all night, and the alert
    that mattered would be somewhere in the middle of it.
    """
    from apps.accounts.models import Role
    from apps.audit.models import SystemFailure

    if failure.severity != SystemFailure.Severity.FAILED:
        # Degraded means it will be retried. It goes in the daily digest.
        return []

    if failure.component == SystemFailure.Component.EMAIL:
        # You cannot email somebody to tell them email is broken. The
        # attempt would fail, record another EMAIL failure, and try to email
        # about that -- deduplication would stop the loop after a hop or
        # two, but a loop that terminates by accident is not a design.
        # An email outage surfaces through /readyz and the digest instead.
        logger.warning("not emailing about an email failure: %s", failure.summary)
        return []

    recipients = staff_emails_for_roles(Role.RoleName.QA_OFFICER, Role.RoleName.LAB_SUPERVISOR)
    if not recipients:
        logger.warning("system failure %s recorded but no QA Officer or Lab Supervisor to tell", failure.pk)
        return []

    return notify_each(
        NotificationRecord.Kind.SYSTEM_FAILURE,
        recipients,
        subject=f"NexusLIMS: system failure in {failure.get_component_display()}",
        dedupe_key=f"system-failure:{failure.pk}",
        entity=failure,
    )


@shared_task(name="apps.notifications.tasks.retry_stalled_notifications")
def retry_stalled_notifications():
    """
    Re-enqueue notifications that were written but never handed to a worker.

    The recovery half of the guard in apps/notifications/notify._enqueue: if
    the broker was down at commit time the row exists and nothing is coming
    for it. Without this, a five-minute Redis blip would silently swallow
    every verification email queued during it -- the customers would simply
    never hear back, and nothing would say so.

    Safe to run against rows a worker is already holding, because
    `send_notification` checks the row before sending and returns
    "already-sent" for one that is done.
    """
    cutoff = timezone.now() - timezone.timedelta(minutes=settings.NOTIFICATION_STALL_MINUTES)
    stalled = NotificationRecord.objects.filter(
        status=NotificationRecord.Status.PENDING, created_at__lte=cutoff,
    ).values_list("pk", flat=True)

    requeued = 0
    for pk in list(stalled):
        try:
            send_notification.delay(pk)
            requeued += 1
        except Exception:
            logger.exception("notification %s could not be re-enqueued; still pending", pk)
            break  # the broker is still down; the next run will try again

    if requeued:
        logger.warning("re-enqueued %d stalled notification(s)", requeued)
    return {"requeued": requeued}


__all__ = [
    "notify",
    "notify_each",
    "notify_system_failure",
    "send_notification",
    "retry_stalled_notifications",
    "send_open_failure_digest",
    "sweep_calibration_due",
]
