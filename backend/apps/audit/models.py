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
