"""
Retention sweep (Blueprint Section 7.4a, apps/audit/tasks.run_retention_sweep):
idempotency via the AuditLogEntry ledger, and the real OSS client path for
archive_to_cold_storage (requires a locally-running MinIO per README -- the
target key here is never actually uploaded, which archive_object treats as
"nothing to do", a legitimate success per apps/audit/oss.py, so this proves
the real S3-compatible call path runs without mocking boto3).
"""

import datetime

import pytest
from django.utils import timezone

from apps.audit.models import AuditLogEntry, RetentionPolicy
from apps.audit.tasks import run_retention_sweep
from apps.testing.models import TestResult
from tests.factories import CalibrationRecordFactory, StaffUserFactory, TestResultFactory

pytestmark = pytest.mark.django_db


def _set_policy(record_type, *, retention_days, action):
    policy = RetentionPolicy.objects.get(record_type=record_type)
    policy.retention_days = retention_days
    policy.action_after_expiry = action
    policy.is_active = True
    policy.save(update_fields=["retention_days", "action_after_expiry", "is_active"])
    return policy


def test_retention_sweep_locks_expired_calibration_records_idempotently():
    _set_policy(
        RetentionPolicy.RecordType.CALIBRATION_RECORD,
        retention_days=0,
        action=RetentionPolicy.ActionAfterExpiry.LOCK_RECORD,
    )
    old_record = CalibrationRecordFactory(performed_at=timezone.now() - datetime.timedelta(days=30))

    first_summary = run_retention_sweep()

    assert first_summary[RetentionPolicy.RecordType.CALIBRATION_RECORD] == 1
    assert AuditLogEntry.objects.filter(
        entity_type="CalibrationRecord", entity_id=old_record.id, field_changed="retention_locked",
    ).count() == 1

    second_summary = run_retention_sweep()

    assert second_summary[RetentionPolicy.RecordType.CALIBRATION_RECORD] == 0  # already processed, not reprocessed
    assert AuditLogEntry.objects.filter(
        entity_type="CalibrationRecord", entity_id=old_record.id, field_changed="retention_locked",
    ).count() == 1


def test_retention_sweep_ignores_records_still_within_the_retention_window():
    _set_policy(
        RetentionPolicy.RecordType.CALIBRATION_RECORD,
        retention_days=1825,
        action=RetentionPolicy.ActionAfterExpiry.LOCK_RECORD,
    )
    CalibrationRecordFactory(performed_at=timezone.now())

    summary = run_retention_sweep()

    assert summary[RetentionPolicy.RecordType.CALIBRATION_RECORD] == 0


def test_retention_sweep_archives_expired_raw_instrument_file_via_real_oss_client():
    """
    Exercises the real boto3-against-MinIO path (apps/audit/oss.py
    archive_object): the raw_file_id key has nothing actually uploaded
    behind it, which is documented as a legitimate "nothing to archive"
    success rather than a failure, so this proves the sweep's OSS call
    completes end to end without needing to seed a real object first.
    """
    _set_policy(
        RetentionPolicy.RecordType.RAW_INSTRUMENT_FILE,
        retention_days=0,
        action=RetentionPolicy.ActionAfterExpiry.ARCHIVE_TO_COLD_STORAGE,
    )
    old_result = TestResultFactory(entered_by=StaffUserFactory())
    TestResult.objects.filter(pk=old_result.pk).update(
        entered_at=timezone.now() - datetime.timedelta(days=30),
        raw_file_id="raw-instrument-exports/does-not-exist.csv",
    )

    summary = run_retention_sweep()

    assert summary[RetentionPolicy.RecordType.RAW_INSTRUMENT_FILE] == 1
    assert AuditLogEntry.objects.filter(
        entity_type="TestResult", entity_id=old_result.id, field_changed="retention_archived",
    ).exists()
