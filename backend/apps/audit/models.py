"""
Audit and Retention entities (Blueprint Section 3.1 AuditLogEntry, Section
3.1a RetentionPolicy, Section 7.2, Section 7.4a).

AuditLogEntry is append-only (FR-E17-02), enforced in Postgres rather than
by convention: migration 0004 revokes UPDATE/DELETE/TRUNCATE from the
application's database role and adds a row-level trigger that refuses both,
so the ORM, raw SQL, a management command and SQL injection are all denied
alike. apps.audit.permissions / admin.py still withhold it at the API layer,
which is now the outer of two rings rather than the only one.

What that does not cover -- a superuser, and the table's owner re-granting
to itself -- is set out in migration 0004's docstring, along with the
deployment change that would. tests/test_audit_append_only.py verifies the
whole surface, including partitions created after the migration ran.

AuditLogEntry.timestamp is partitioned monthly at the database layer via
native PostgreSQL declarative range partitioning (Blueprint Section 2.1
item 5a, closes Section 13 gap 11). Django's migration framework does not
model partitioning directly, so the partitioned-table DDL is applied via a
RunSQL migration (0002_partition_audit_log_entry.py) rather than through
ordinary model Meta options.
"""

from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user


class AuditLogEntry(models.Model):
    class ActorType(models.TextChoices):
        STAFF = "staff", "Staff"
        CUSTOMER = "customer", "Customer"
        SYSTEM = "system", "System"

    id = models.BigAutoField(primary_key=True)
    actor_id = models.BigIntegerField(null=True, blank=True)
    actor_type = models.CharField(max_length=16, choices=ActorType.choices)
    entity_type = models.CharField(max_length=64)
    entity_id = models.BigIntegerField()
    field_changed = models.CharField(max_length=128, blank=True)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    reason = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    e_signature = models.ForeignKey(
        "accounts.ESignature", null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_log_entries",
    )

    class Meta:
        db_table = "audit_log_entry"
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["timestamp"]),
        ]
        ordering = ["-timestamp"]

    def __str__(self):
        return f"AuditLogEntry #{self.id}: {self.entity_type}#{self.entity_id} @ {self.timestamp:%Y-%m-%d %H:%M}"


class RetentionPolicy(models.Model):
    """
    Blueprint Section 3.1a. RESOLVED default seed (closes Section 13 gap 3):
    retention_days=1825 (5 years), action_after_expiry=archive_to_cold_storage,
    seeded uniformly across all record_type values at deployment via a data
    migration (see migrations/0002_seed_retention_policy.py).
    """

    class RecordType(models.TextChoices):
        RAW_INSTRUMENT_FILE = "raw_instrument_file", "Raw Instrument File"
        COA_REPORT = "coa_report", "COA / Report"
        CALIBRATION_RECORD = "calibration_record", "Calibration Record"
        TRAINING_RECORD = "training_record", "Training Record"
        AUDIT_LOG_ENTRY = "audit_log_entry", "Audit Log Entry"

    class ActionAfterExpiry(models.TextChoices):
        ARCHIVE_TO_COLD_STORAGE = "archive_to_cold_storage", "Archive to Cold Storage"
        LOCK_RECORD = "lock_record", "Lock Record"
        ANONYMIZE = "anonymize", "Anonymize"

    id = models.BigAutoField(primary_key=True)
    record_type = models.CharField(max_length=32, choices=RecordType.choices, unique=True)
    retention_days = models.PositiveIntegerField(default=1825, help_text="5-year default per ISO/IEC 17025:2017 8.4.2.")
    action_after_expiry = models.CharField(
        max_length=32, choices=ActionAfterExpiry.choices, default=ActionAfterExpiry.ARCHIVE_TO_COLD_STORAGE,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "retention_policy"
        ordering = ["record_type"]

    def __str__(self):
        return f"{self.get_record_type_display()}: {self.retention_days}d -> {self.get_action_after_expiry_display()}"


class SystemFailure(models.Model):
    """
    The register ISO/IEC 17025:2017 7.11.3(e) requires: system failures, and
    the immediate and corrective actions taken.

    Grounded in the clause directly rather than in a Blueprint FR -- the
    Blueprint does not name this entity, and 17025 is one of the groundings
    this project accepts (see the root README). Before it, the failures the
    system already detected went to `logger` and nowhere else: stdout in a
    container, on ephemeral storage, gone at the next restart. An assessor
    asking "show me last quarter's system failures and what you did about
    them" could not be answered, and neither could the more useful internal
    question of whether the same thing keeps happening.

    Three columns carry the clause, and they are deliberately separate:

      immediate_action  what the system did by itself, at the moment of
                        failure -- retried, marked the report failed, took
                        the instance out of rotation. Written by the
                        recorder, never by a person.
      corrective_action what a person did so it stops happening. Empty until
                        somebody fills it in, which is the point: an open
                        row with no corrective action is a visible piece of
                        outstanding work rather than a silence.
      investigation     the existing CAPA record (7.10 / 8.7), when the
                        failure warranted one. A link rather than a second
                        parallel CAPA workflow -- Investigation already
                        carries root_cause, capa_actions and a closure.

    Deduplication, and why it stops at `open`: a failing dependency produces
    one failure per probe, and a load balancer probes every few seconds. One
    row per occurrence would mean thousands of rows for one outage, which
    buries the register it is supposed to populate. So a repeat of an
    already-open failure bumps `occurrences` and `last_seen_at` instead of
    inserting.

    But only while the row is open. Once somebody has acknowledged or closed
    a failure, the next occurrence opens a *new* row rather than quietly
    joining the closed one -- a recurrence after a corrective action is the
    single most important thing this table can tell you, and coalescing it
    into the closed row would hide exactly that.

    The counter bump is a QuerySet.update(), which sends no signals and so
    writes no history row. That is deliberate and is the one case where the
    caveat in apps/audit/signals.py is being used on purpose: `occurrences`
    moving from 41 to 42 during an outage is not a change anybody needs
    attributed. Everything a person does -- acknowledging, closing, writing
    the corrective action -- goes through save() and is recorded by
    HistoricalRecords with the staff member who did it.

    Rows cannot be deleted (migration 0005 revokes DELETE and TRUNCATE from
    the application's role, the same way 0004 does for the audit ledger).
    UPDATE is deliberately *not* revoked: the corrective action is written
    after the fact, so this table has to stay writable in a way the audit
    ledger does not.
    """

    class Component(models.TextChoices):
        REPORT_GENERATION = "report_generation", "Report generation"
        RETENTION_SWEEP = "retention_sweep", "Retention sweep"
        OBJECT_STORAGE = "object_storage", "Object storage"
        DATABASE = "database", "Database"
        TASK_BROKER = "task_broker", "Task broker"
        SCHEDULED_TASK = "scheduled_task", "Scheduled task"
        API_REQUEST = "api_request", "API request"
        EMAIL = "email", "Email delivery"

    class Severity(models.TextChoices):
        # The distinction an operator reads first: did the work eventually
        # happen anyway, or is something now missing?
        DEGRADED = "degraded", "Degraded (the operation will be retried)"
        FAILED = "failed", "Failed (the operation did not complete)"

    class ImmediateAction(models.TextChoices):
        RETRY_SCHEDULED = "retry_scheduled", "Left unprocessed for the next run to retry"
        MARKED_FAILED = "marked_failed", "Recorded as failed on the affected record"
        REQUEST_REJECTED = "request_rejected", "The request was rejected with an error"
        REMOVED_FROM_ROTATION = "removed_from_rotation", "The instance reported itself not ready"
        NONE = "none", "None taken automatically"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        CLOSED = "closed", "Closed"

    id = models.BigAutoField(primary_key=True)
    # sha256 of component + summary. Stored rather than recomputed so the
    # dedup lookup is an index hit on a fixed-width column, and so changing
    # how the fingerprint is derived cannot silently re-coalesce old rows.
    fingerprint = models.CharField(max_length=64)
    component = models.CharField(max_length=32, choices=Component.choices)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.FAILED)
    summary = models.CharField(max_length=255, help_text="One line, stable across occurrences -- it is half the fingerprint.")
    detail = models.TextField(blank=True, help_text="Traceback or dependency error, for the operator rather than the assessor.")
    immediate_action = models.CharField(
        max_length=32, choices=ImmediateAction.choices, default=ImmediateAction.NONE,
        help_text="What the system did by itself. Written by the recorder, never by a person.",
    )

    occurrences = models.PositiveIntegerField(default=1)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField()

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    acknowledged_by = models.ForeignKey(
        "accounts.StaffUser", null=True, blank=True, on_delete=models.PROTECT, related_name="acknowledged_system_failures",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    corrective_action = models.TextField(blank=True, help_text="What a person did so it stops happening (ISO/IEC 17025:2017 7.11.3(e)).")
    investigation = models.ForeignKey(
        "investigations.Investigation", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="system_failures",
        help_text="The CAPA record opened for this failure, when it warranted one.",
    )
    closed_by = models.ForeignKey(
        "accounts.StaffUser", null=True, blank=True, on_delete=models.PROTECT, related_name="closed_system_failures",
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "system_failure"
        indexes = [
            # The dedup lookup: fingerprint plus status, because only open
            # rows are candidates to coalesce into.
            models.Index(fields=["fingerprint", "status"]),
            models.Index(fields=["status", "-last_seen_at"]),
            models.Index(fields=["component"]),
        ]
        ordering = ["-last_seen_at"]

    def __str__(self):
        return f"SystemFailure #{self.id}: {self.get_component_display()} -- {self.summary} (x{self.occurrences})"
