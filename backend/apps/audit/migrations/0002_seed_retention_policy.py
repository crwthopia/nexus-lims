"""
Data migration seeding RetentionPolicy defaults.

RESOLVED per NASAT architectural review (Blueprint Section 3.1a, closes
Section 13 gap 3): every record_type is seeded with retention_days=1825
(5 years) and action_after_expiry=archive_to_cold_storage as the audit-proof
default, reflecting typical 3-to-5-year accreditation assessment cycles per
ISO/IEC 17025:2017 8.4.2. NASAT's QA function may override individual rows
at any time as a configuration change, not a code change.
"""

from django.db import migrations

# NOTE: Historical model state reconstructed by Django's migration framework
# does not preserve custom inner classes (TextChoices) defined on the real
# model, so values are hardcoded here rather than referenced via
# RetentionPolicy.RecordType.choices / ActionAfterExpiry. Must stay in sync
# with audit.models.RetentionPolicy.
RECORD_TYPES = [
    "raw_instrument_file",
    "coa_report",
    "calibration_record",
    "training_record",
    "audit_log_entry",
]
ARCHIVE_TO_COLD_STORAGE = "archive_to_cold_storage"


def seed_retention_policy(apps, schema_editor):
    RetentionPolicy = apps.get_model("audit", "RetentionPolicy")
    for record_type in RECORD_TYPES:
        RetentionPolicy.objects.get_or_create(
            record_type=record_type,
            defaults={
                "retention_days": 1825,
                "action_after_expiry": ARCHIVE_TO_COLD_STORAGE,
                "is_active": True,
            },
        )


def unseed_retention_policy(apps, schema_editor):
    RetentionPolicy = apps.get_model("audit", "RetentionPolicy")
    RetentionPolicy.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_retention_policy, unseed_retention_policy),
    ]
