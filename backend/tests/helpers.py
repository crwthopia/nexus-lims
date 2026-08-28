"""
reload() fetches a fresh instance instead of mutating one in place with
instance.refresh_from_db().

It exists for a bug that is now fixed: on a model with a django-fsm-2
protected=True field (Sample, TestRequest, TrainingSession, Enrollment),
FSMFieldDescriptor.__set__ raises AttributeError on any direct assignment
once the field name is already in instance.__dict__, and
Model.refresh_from_db() does exactly that direct setattr for every field.
All four models now mix in django_fsm.FSMModelMixin, which overrides
refresh_from_db() to skip protected fields, so refresh_from_db() works --
see tests/test_fsm_refresh_from_db.py. reload() is kept as a convenience
for tests that don't need to mutate the same instance in place.
"""


def reload(instance):
    return type(instance).objects.get(pk=instance.pk)


def deliver_queued_notifications():
    """
    Run every queued notification's send task inline, and return how many.

    Notifications are queued in the caller's transaction and dispatched by
    `transaction.on_commit` (apps/notifications/notify.py), so inside a test
    -- which never commits -- the row exists but the send never fires. That
    is the correct production behaviour and an awkward test fixture, so this
    stands in for the worker.

    It calls the real task against the real EMAIL_BACKEND, so a test using
    it still exercises message building, the confidentiality rules about
    what may appear in a body, and `mail.outbox`. Asserting only that a row
    was written would leave all of that untested.
    """
    from apps.notifications.models import NotificationRecord
    from apps.notifications.tasks import send_notification

    pending = list(
        NotificationRecord.objects.filter(status=NotificationRecord.Status.PENDING).values_list("pk", flat=True)
    )
    for pk in pending:
        send_notification(pk)
    return len(pending)
