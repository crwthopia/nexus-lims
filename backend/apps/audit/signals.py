"""
Writes the AuditLogEntry rows FR-E17-01 requires.

The table, its monthly partitioning and its three actor types were all
built; nothing populated them. A staff edit, a customer self-enrolment and
a system-issued credit note produced zero rows between them, and the two
non-staff writes were also anonymous in django-simple-history, whose
history_user cannot be anything but a StaffUser.

Scope is the entities under ISO/IEC 17025: Sample, TestRequest, TestResult,
TestMethod, Report, CalibrationRecord, Investigation. Billing, training and
documents are tracked by simple-history but are not audited here yet --
deliberately, so the shape is proven on the regulated core before the write
volume is multiplied across everything.

Row shape follows the model's own fields: a create or a delete is one row
with `field_changed` empty, an update is one row per field that actually
changed. Unchanged fields are not written -- an audit log that records a
row per save regardless of whether anything moved buries the changes that
matter.

`pre_save` reads the previous row to diff against. That is one extra SELECT
per save on seven models, paid so that old_value is real rather than
reconstructed. simple-history's own records were the alternative, but they
are written by a receiver on the same signal, so relying on them here would
make correctness depend on receiver ordering.

Known limit, and the reason apps/reporting/tasks.py changed alongside this:
QuerySet.update() does not send signals, so anything written that way is
invisible both here and to simple-history. A report moving pending ->
generating -> ready left exactly one history row, recording only 'pending'.
Those three call sites now save() instead. Any future .update() on a model
in AUDITED_MODELS silently escapes this file; the test suite pins the
current call sites so a new one is a decision rather than an accident.
"""

from django.db.models.signals import post_delete, post_save, pre_save

from apps.audit.context import get_actor

# The regulated core. Adding a model here is all that is needed to audit it.
AUDITED_MODELS = [
    ("samples", "Sample"),
    ("testing", "TestRequest"),
    ("testing", "TestResult"),
    ("testing", "TestMethod"),
    ("reporting", "Report"),
    ("equipment", "CalibrationRecord"),
    ("investigations", "Investigation"),
]

# Fields whose churn says nothing about what a person did. auto_now/auto_now_add
# columns move on every save by definition, and the audit row carries its own
# timestamp.
_IGNORED_FIELDS = frozenset({"id", "created_at", "updated_at", "modified_at"})

_MAX_VALUE_LENGTH = 4000

# Set by pre_save, read by post_save. Keyed on the instance itself rather
# than stored globally so concurrent saves cannot read each other's snapshot.
_SNAPSHOT_ATTR = "_audit_previous_state"


def _serialise(value):
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= _MAX_VALUE_LENGTH else text[:_MAX_VALUE_LENGTH] + "..."


def _tracked_fields(instance):
    for field in instance._meta.concrete_fields:
        if field.name in _IGNORED_FIELDS or field.primary_key:
            continue
        yield field


def capture_previous_state(sender, instance, **kwargs):
    """Snapshot the stored row so post_save can say what actually changed."""
    if instance.pk is None:
        setattr(instance, _SNAPSHOT_ATTR, None)
        return
    try:
        stored = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        # A save with an explicit pk that does not exist yet is a create.
        setattr(instance, _SNAPSHOT_ATTR, None)
        return
    setattr(
        instance,
        _SNAPSHOT_ATTR,
        {f.attname: getattr(stored, f.attname) for f in _tracked_fields(stored)},
    )


def _write(entries):
    from apps.audit.models import AuditLogEntry

    if entries:
        AuditLogEntry.objects.bulk_create(entries)


def record_write(sender, instance, created, **kwargs):
    from apps.audit.models import AuditLogEntry

    actor = get_actor()
    entity_type = sender.__name__
    common = {
        "actor_id": actor.actor_id,
        "actor_type": actor.actor_type,
        "entity_type": entity_type,
        "entity_id": instance.pk,
    }

    if created:
        _write([AuditLogEntry(**common, field_changed="", reason="created")])
        return

    previous = getattr(instance, _SNAPSHOT_ATTR, None)
    if previous is None:
        # No snapshot means pre_save did not see this instance -- a
        # loaddata or a raw save. Record the write rather than dropping it.
        _write([AuditLogEntry(**common, field_changed="", reason="updated")])
        return

    entries = []
    for field in _tracked_fields(instance):
        before = previous.get(field.attname)
        after = getattr(instance, field.attname)
        if before == after:
            continue
        entries.append(
            AuditLogEntry(
                **common,
                field_changed=field.name,
                old_value=_serialise(before),
                new_value=_serialise(after),
                reason="updated",
            )
        )
    _write(entries)


def record_delete(sender, instance, **kwargs):
    from apps.audit.models import AuditLogEntry

    actor = get_actor()
    _write([
        AuditLogEntry(
            actor_id=actor.actor_id,
            actor_type=actor.actor_type,
            entity_type=sender.__name__,
            entity_id=instance.pk,
            field_changed="",
            reason="deleted",
        )
    ])


def connect():
    """Called from AuditConfig.ready()."""
    from django.apps import apps as django_apps

    for app_label, model_name in AUDITED_MODELS:
        model = django_apps.get_model(app_label, model_name)
        uid = f"audit_{app_label}_{model_name}"
        pre_save.connect(capture_previous_state, sender=model, dispatch_uid=uid + "_pre")
        post_save.connect(record_write, sender=model, dispatch_uid=uid + "_post")
        post_delete.connect(record_delete, sender=model, dispatch_uid=uid + "_del")
