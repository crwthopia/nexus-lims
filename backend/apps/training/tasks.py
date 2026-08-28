"""
Automated training session capacity enforcement (Blueprint Section 3.6,
4.3, closes the remainder of Section 13 gap 7). Runs daily via Celery beat
(config/settings.py CELERY_BEAT_SCHEDULE): for each SCHEDULED
TrainingSession that has crossed its cancellation_threshold_days boundary,
if confirmed Enrollment count is below min_capacity, the session flips to
pending_reschedule, every affected Enrollment reschedules, a CreditNote is
issued per enrollment with money actually paid against it (funds stay tied
to the customer rather than a cash/bank refund), and a notification email
goes out (console backend in dev, same pattern as customer email
verification, apps/accounts/customer_auth.py).
"""

import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.billing.models import Invoice
from apps.notifications.models import NotificationRecord
from apps.notifications.notify import notify
from apps.training.models import CreditNote, Enrollment, TrainingSession

logger = logging.getLogger(__name__)


def _amount_paid(enrollment):
    """
    Sum of Invoice.amount for this enrollment's invoice(s) with paid or
    partially_paid status. Payment (apps/billing/models.py) has no
    per-payment amount field of its own -- only Invoice does -- so a
    partially-paid invoice is approximated here by its full invoiced
    amount rather than the (unrecorded) amount actually received. Phase 1
    payment reconciliation is manual (Blueprint Section 3.7); this is the
    best signal available without that schema gap being closed separately.
    """
    total = Invoice.objects.filter(
        enrollment=enrollment,
        status__in=[Invoice.Status.PAID, Invoice.Status.PARTIALLY_PAID],
    ).aggregate(total=Sum("amount"))["total"]
    return total or 0


@shared_task(name="apps.training.tasks.check_session_capacity")
def check_session_capacity():
    now = timezone.now()
    flagged = 0

    for session in TrainingSession.objects.filter(status=TrainingSession.Status.SCHEDULED):
        threshold_date = session.start_date - timezone.timedelta(days=session.cancellation_threshold_days)
        if now < threshold_date:
            continue  # not yet at this session's check point

        confirmed_count = session.enrollments.filter(status=Enrollment.Status.CONFIRMED).count()
        if confirmed_count >= session.min_capacity:
            continue  # healthy

        with transaction.atomic():
            session.flag_below_min_capacity()
            session.save()

            for enrollment in session.enrollments.filter(status=Enrollment.Status.CONFIRMED):
                amount = _amount_paid(enrollment)

                enrollment.reschedule()
                enrollment.save()

                if amount > 0:
                    CreditNote.objects.create(
                        customer=enrollment.customer,
                        source_enrollment=enrollment,
                        amount=amount,
                    )

                # Queued, not sent, and that matters twice over inside this
                # atomic block. Sending here meant an SMTP failure rolled back
                # the CreditNote rows written immediately above -- a mail
                # outage quietly cancelling credit notes -- and a rollback
                # *after* a successful send left customers holding an email
                # about a reschedule that did not happen. notify() writes a
                # row in this transaction and defers the send to on_commit, so
                # the message goes out if and only if the reschedule did.
                notify(
                    NotificationRecord.Kind.TRAINING_SESSION_RESCHEDULED,
                    enrollment.customer.email,
                    subject=f"NexusLIMS: {session.course.title} session rescheduled",
                    dedupe_key=f"training-rescheduled:{enrollment.id}:{session.start_date:%Y-%m-%d}",
                    entity=enrollment,
                )

        flagged += 1
        logger.info(
            "training capacity check: session #%s flagged pending_reschedule (%d/%d confirmed)",
            session.id, confirmed_count, session.min_capacity,
        )

    return {"sessions_flagged": flagged}
