"""
The system failure register ISO/IEC 17025:2017 7.11.3(e) requires, plus the
one privilege change that keeps it a register.

DELETE and TRUNCATE are revoked from the application's database role, the
same way migration 0004 does for the audit ledger and for the same reason: a
record of failures that the thing producing the failures can tidy away is
not evidence of anything.

UPDATE is deliberately *not* revoked, which is the difference between this
table and audit_log_entry. The corrective action is written after the fact,
sometimes weeks after, so this table has to stay writable -- and what makes
it trustworthy instead is HistoricalRecords, which records who changed what
and when. The ledger gets immutability; the register gets attribution.
Applying the ledger's rule here would make the clause impossible to satisfy.

Unlike audit_log_entry, system_failure is not partitioned, so a single
REVOKE covers it -- there are no partitions to loop over and none will be
created later.
"""

import django.db.models.deletion
import simple_history.models
from django.conf import settings
from django.db import migrations, models


# See the module docstring: DELETE/TRUNCATE only. UPDATE stays granted
# because the corrective action is written later, and HistoricalRecords is
# what makes that writable column trustworthy.
REVOKE_SQL = """
REVOKE DELETE, TRUNCATE ON system_failure FROM CURRENT_USER;
"""

RESTORE_SQL = """
GRANT DELETE, TRUNCATE ON system_failure TO CURRENT_USER;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0004_audit_log_append_only"),
        ("investigations", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricalSystemFailure",
            fields=[
                ("id", models.BigIntegerField(blank=True, db_index=True)),
                ("fingerprint", models.CharField(max_length=64)),
                (
                    "component",
                    models.CharField(
                        choices=[
                            ("report_generation", "Report generation"),
                            ("retention_sweep", "Retention sweep"),
                            ("object_storage", "Object storage"),
                            ("database", "Database"),
                            ("task_broker", "Task broker"),
                            ("scheduled_task", "Scheduled task"),
                            ("api_request", "API request"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("degraded", "Degraded (the operation will be retried)"),
                            ("failed", "Failed (the operation did not complete)"),
                        ],
                        default="failed",
                        max_length=16,
                    ),
                ),
                (
                    "summary",
                    models.CharField(
                        help_text="One line, stable across occurrences -- it is half the fingerprint.",
                        max_length=255,
                    ),
                ),
                (
                    "detail",
                    models.TextField(
                        blank=True,
                        help_text="Traceback or dependency error, for the operator rather than the assessor.",
                    ),
                ),
                (
                    "immediate_action",
                    models.CharField(
                        choices=[
                            (
                                "retry_scheduled",
                                "Left unprocessed for the next run to retry",
                            ),
                            (
                                "marked_failed",
                                "Recorded as failed on the affected record",
                            ),
                            (
                                "request_rejected",
                                "The request was rejected with an error",
                            ),
                            (
                                "removed_from_rotation",
                                "The instance reported itself not ready",
                            ),
                            ("none", "None taken automatically"),
                        ],
                        default="none",
                        help_text="What the system did by itself. Written by the recorder, never by a person.",
                        max_length=32,
                    ),
                ),
                ("occurrences", models.PositiveIntegerField(default=1)),
                ("first_seen_at", models.DateTimeField(blank=True, editable=False)),
                ("last_seen_at", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("acknowledged", "Acknowledged"),
                            ("closed", "Closed"),
                        ],
                        default="open",
                        max_length=16,
                    ),
                ),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                (
                    "corrective_action",
                    models.TextField(
                        blank=True,
                        help_text="What a person did so it stops happening (ISO/IEC 17025:2017 7.11.3(e)).",
                    ),
                ),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "acknowledged_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "closed_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "investigation",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        help_text="The CAPA record opened for this failure, when it warranted one.",
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="investigations.investigation",
                    ),
                ),
            ],
            options={
                "verbose_name": "historical system failure",
                "verbose_name_plural": "historical system failures",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="SystemFailure",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("fingerprint", models.CharField(max_length=64)),
                (
                    "component",
                    models.CharField(
                        choices=[
                            ("report_generation", "Report generation"),
                            ("retention_sweep", "Retention sweep"),
                            ("object_storage", "Object storage"),
                            ("database", "Database"),
                            ("task_broker", "Task broker"),
                            ("scheduled_task", "Scheduled task"),
                            ("api_request", "API request"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("degraded", "Degraded (the operation will be retried)"),
                            ("failed", "Failed (the operation did not complete)"),
                        ],
                        default="failed",
                        max_length=16,
                    ),
                ),
                (
                    "summary",
                    models.CharField(
                        help_text="One line, stable across occurrences -- it is half the fingerprint.",
                        max_length=255,
                    ),
                ),
                (
                    "detail",
                    models.TextField(
                        blank=True,
                        help_text="Traceback or dependency error, for the operator rather than the assessor.",
                    ),
                ),
                (
                    "immediate_action",
                    models.CharField(
                        choices=[
                            (
                                "retry_scheduled",
                                "Left unprocessed for the next run to retry",
                            ),
                            (
                                "marked_failed",
                                "Recorded as failed on the affected record",
                            ),
                            (
                                "request_rejected",
                                "The request was rejected with an error",
                            ),
                            (
                                "removed_from_rotation",
                                "The instance reported itself not ready",
                            ),
                            ("none", "None taken automatically"),
                        ],
                        default="none",
                        help_text="What the system did by itself. Written by the recorder, never by a person.",
                        max_length=32,
                    ),
                ),
                ("occurrences", models.PositiveIntegerField(default=1)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("acknowledged", "Acknowledged"),
                            ("closed", "Closed"),
                        ],
                        default="open",
                        max_length=16,
                    ),
                ),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                (
                    "corrective_action",
                    models.TextField(
                        blank=True,
                        help_text="What a person did so it stops happening (ISO/IEC 17025:2017 7.11.3(e)).",
                    ),
                ),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "acknowledged_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="acknowledged_system_failures",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "closed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="closed_system_failures",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "investigation",
                    models.ForeignKey(
                        blank=True,
                        help_text="The CAPA record opened for this failure, when it warranted one.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="system_failures",
                        to="investigations.investigation",
                    ),
                ),
            ],
            options={
                "db_table": "system_failure",
                "ordering": ["-last_seen_at"],
                "indexes": [
                    models.Index(
                        fields=["fingerprint", "status"],
                        name="system_fail_fingerp_1bb27d_idx",
                    ),
                    models.Index(
                        fields=["status", "-last_seen_at"],
                        name="system_fail_status_49c382_idx",
                    ),
                    models.Index(
                        fields=["component"], name="system_fail_compone_1eeded_idx"
                    ),
                ],
            },
        ),
        migrations.RunSQL(sql=REVOKE_SQL, reverse_sql=RESTORE_SQL),
    ]
