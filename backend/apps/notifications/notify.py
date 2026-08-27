"""
The one way anything in this codebase sends email.

Before this, two modules called `django.core.mail.send_mail` inline and
both were in the wrong place for it:

  - `apps/accounts/customer_auth.py` sent the verification message from
    inside the registration request, so SMTP latency was in the user's
    request and an SMTP failure was a 500 on an account that had already
    been created.
  - `apps/training/tasks.py` sent inside `transaction.atomic()`, which is
    worse in two directions: a mail failure rolled back the CreditNote rows
    the same block had just written, and a rollback *after* a successful
    send left customers holding an email about a reschedule that did not
    happen. You cannot unsend.

So: `notify()` writes a row and returns. Nothing goes over the network
until the surrounding transaction commits, and the send itself is a Celery
task -- the same shape `apps/reporting/tasks.enqueue_generation` already
uses, and for the same reason.

`notify()` deliberately does *not* swallow exceptions the way
`apps/audit/failures.record_failure` does. That asymmetry is intentional:
recording a failure is a side observation that must never make things
worse, while queueing a notification is a local database insert inside the
caller's own transaction. If it cannot happen, the caller's transaction is
already broken and should fail with it. The network call -- the part that
genuinely can fail on its own -- is in the task, where a failure is caught,
recorded on the row, and surfaced through the 7.11.3(e) register.
"""

import logging

from django.db import IntegrityError, transaction

from apps.notifications.models import NotificationRecord

logger = logging.getLogger(__name__)


def staff_emails_for_roles(*role_names):
    """
    Active staff holding any of `role_names`.

    Resolved from roles rather than a configured address list so that adding
    a QA Officer in the admin is all it takes to put them on the distribution
    -- a hardcoded list is one staff change away from mailing somebody who
    left, and nobody remembers to update it.
    """
    from apps.accounts.models import StaffUser

    return sorted(
        StaffUser.objects.filter(roles__name__in=role_names, is_active=True)
        .values_list("email", flat=True)
        .distinct()
    )


def notify(kind, recipient, subject, *, dedupe_key, entity=None):
    """
    Queue one notification. Returns the NotificationRecord, or None if
    `dedupe_key` has already been used.

    The uniqueness of `dedupe_key` is enforced by the database, not by a
    prior SELECT, because the callers that need it most are periodic sweeps
    -- and beat firing while somebody triggers the same task by hand is
    exactly the race a check-then-insert loses. Returning None rather than
    raising lets a sweep treat "already sent" as the ordinary case it is.
    """
    entity_type = entity.__class__.__name__ if entity is not None else ""
    entity_id = entity.pk if entity is not None else None

    try:
        with transaction.atomic():
            record = NotificationRecord.objects.create(
                kind=kind,
                recipient=recipient,
                subject=subject[:255],
                entity_type=entity_type,
                entity_id=entity_id,
                dedupe_key=dedupe_key[:255],
            )
    except IntegrityError:
        # Nested in its own atomic block above so this does not poison the
        # caller's transaction: in Postgres a failed statement aborts the
        # whole transaction unless it is contained in a savepoint.
        logger.debug("notification %s already queued for %s", kind, dedupe_key)
        return None

    # After commit, always. A worker that picks the task up before the row
    # is visible fails with DoesNotExist -- the classic Celery-with-Django
    # race, and one that only shows up under load.
    transaction.on_commit(lambda: _enqueue(record.pk))
    return record


def notify_each(kind, recipients, subject, *, dedupe_key, entity=None):
    """
    Same notification to several people, one row each.

    A row per recipient rather than one row with a recipient list: the
    register has to answer "was *this person* told", and one failed address
    in a list would otherwise mark the whole notification failed for
    everybody who did receive it.
    """
    return [
        record
        for recipient in recipients
        if (record := notify(kind, recipient, subject, dedupe_key=f"{dedupe_key}:{recipient}", entity=entity))
    ]


def _enqueue(record_id):
    """
    Hand the row to a worker, and survive not being able to.

    Moving the send out of the request removed SMTP from the request path but
    put the *broker* there instead: `.delay()` is a Redis round trip, and
    `transaction.on_commit` runs it inline once the transaction commits. With
    Redis down, an unguarded `.delay()` would 500 a registration for exactly
    the reason the inline `send_mail` used to -- a different dependency, the
    same bug.

    So a broker failure leaves the row PENDING and returns. Nothing is lost:
    `retry_stalled_notifications` re-enqueues anything still pending once the
    broker is back, and /readyz already reports Redis being down. Deliberately
    not recorded as a SystemFailure here -- a broker outage would be recorded,
    the alert about it would be queued, queueing would fail here, and the
    only thing stopping that loop would be fingerprint deduplication. A loop
    that terminates by accident is not a design.
    """
    from apps.notifications.tasks import send_notification

    try:
        send_notification.delay(record_id)
    except Exception:
        logger.exception(
            "could not enqueue notification %s; it stays pending for retry_stalled_notifications",
            record_id,
        )
