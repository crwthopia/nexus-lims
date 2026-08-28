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


# Statuses a customer is never told about automatically, whatever
# CUSTOMER_NOTIFIED_SAMPLE_STATUSES is set to. These are nonconforming work
# (ISO/IEC 17025:2017 7.10), and the clause asks the laboratory to *evaluate*
# it and decide whether the customer needs notifying. An automatic "your
# sample failed" fires before anybody has evaluated anything: it pre-empts a
# judgement the lab is required to make, and it is the email you can never
# take back.
#
# In code rather than in settings on purpose. Widening the configured
# milestone list in a deployment must not be able to switch on automatic bad
# news by accident.
NEVER_AUTO_NOTIFIED = frozenset({"under_investigation", "rejected", "retest_pending"})


def notify_sample_progress(sample):
    """
    Tell a customer their sample reached a milestone they care about.

    Called from apps/samples/views._run_transition, which every Sample
    transition runs through -- so this sees all ten of them and filters,
    rather than ten call sites each remembering to notify.

    Above SAMPLE_PROGRESS_DIGEST_THRESHOLD samples on the order, nothing is
    sent here: a 30-sample water order would otherwise be 30 emails per
    milestone, 90 for the job. Those orders are picked up once a day by
    send_sample_progress_digests instead.
    """
    from django.conf import settings as django_settings

    status = sample.status

    if status in NEVER_AUTO_NOTIFIED:
        return []
    if status not in django_settings.CUSTOMER_NOTIFIED_SAMPLE_STATUSES:
        return []

    order = sample.order
    if order is None or order.customer is None:
        # Walk-in samples are registered without an Order (the FK is nullable
        # for exactly that case), so there is no customer to tell. Not a
        # failure, and deliberately not noisy -- it is the normal shape for
        # over-the-counter work.
        logger.debug("sample %s has no order/customer to notify", sample.pk)
        return []

    if order.samples.count() > django_settings.SAMPLE_PROGRESS_DIGEST_THRESHOLD:
        return []  # digested daily instead; see send_sample_progress_digests

    return notify_each(
        NotificationRecord.Kind.SAMPLE_PROGRESS,
        [order.customer.email],
        subject=f"NexusLIMS: sample {sample.unique_sample_code} {_milestone_phrase(status)}",
        # Keyed on the milestone, so a retest re-entering in_testing stays
        # quiet: the customer already knows testing is happening, and being
        # told twice reads as a mistake rather than as news.
        dedupe_key=f"sample-progress:{sample.pk}:{status}",
        entity=sample,
        context={"status": status},
    )


def _milestone_phrase(status):
    from apps.notifications.messages import MILESTONE_WORDING

    return MILESTONE_WORDING.get(status, "moved to a new stage")


@shared_task(name="apps.notifications.tasks.send_sample_progress_digests")
def send_sample_progress_digests():
    """
    One email per order per milestone per day, for orders too big to mail
    per sample.

    Reads the audit ledger rather than re-deriving "what changed today" from
    the samples themselves: apps/audit/signals.py already writes a row per
    status change with the new value on it, and a Sample sitting in
    `in_testing` cannot tell you whether it arrived there today or last week.
    That is the same reason the retention sweep reads the ledger for its own
    idempotency -- the ledger is the record of what happened, and everything
    else is the record of what is.
    """
    from django.conf import settings as django_settings

    from apps.audit.models import AuditLogEntry
    from apps.samples.models import Order, Sample

    since = timezone.now() - timezone.timedelta(days=1)
    milestones = [
        s for s in django_settings.CUSTOMER_NOTIFIED_SAMPLE_STATUSES if s not in NEVER_AUTO_NOTIFIED
    ]

    changes = AuditLogEntry.objects.filter(
        entity_type="Sample", field_changed="status", new_value__in=milestones, timestamp__gte=since,
    ).values_list("entity_id", "new_value")

    # (order, status) -> how many of that order's samples reached it today.
    grouped = {}
    sample_orders = dict(
        Sample.objects.filter(pk__in={sample_id for sample_id, _ in changes})
        .values_list("pk", "order_id")
    )
    for sample_id, status in changes:
        order_id = sample_orders.get(sample_id)
        if order_id:
            grouped.setdefault((order_id, status), set()).add(sample_id)

    today = timezone.localdate()
    queued = 0

    for (order_id, status), sample_ids in grouped.items():
        order = Order.objects.select_related("customer").filter(pk=order_id).first()
        if order is None or order.customer is None:
            continue
        if order.samples.count() <= django_settings.SAMPLE_PROGRESS_DIGEST_THRESHOLD:
            continue  # small orders were already mailed per sample, as they happened

        queued += len(
            notify_each(
                NotificationRecord.Kind.SAMPLE_PROGRESS_DIGEST,
                [order.customer.email],
                subject=(
                    f"NexusLIMS: {len(sample_ids)} sample(s) on order #{order.id} "
                    f"{_milestone_phrase(status)}"
                ),
                dedupe_key=f"sample-progress-digest:{order.id}:{status}:{today:%Y-%m-%d}",
                entity=order,
                context={"status": status, "count": len(sample_ids)},
            )
        )

    logger.info("sample progress digests: %d group(s), %d queued", len(grouped), queued)
    return {"groups": len(grouped), "queued": queued}


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
    "notify_sample_progress",
    "retry_stalled_notifications",
    "send_sample_progress_digests",
    "send_open_failure_digest",
    "sweep_calibration_due",
]
