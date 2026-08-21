"""
Automated retention enforcement (Blueprint Section 7.4a). Runs daily via
Celery beat (config/settings.py CELERY_BEAT_SCHEDULE), sweeping records
governed by each active RetentionPolicy for expiry and applying
action_after_expiry.

Idempotency: rather than a separate "is this record locked/archived" table,
the existing AuditLogEntry ledger doubles as both the action log and the
idempotency marker. Before acting on a record, the sweep checks for a prior
AuditLogEntry with field_changed=f"retention_{action}" against that
(entity_type, entity_id); if one exists, a previous run already processed
it and it's skipped. This also means "is this record locked" is answerable
with the same query any future view-layer write-guard would use:

    AuditLogEntry.objects.filter(
        entity_type=..., entity_id=..., field_changed="retention_locked"
    ).exists()

Object storage: archive_to_cold_storage calls the real OSS client
(apps/audit/oss.py, boto3 against OSS's S3-compatible API -- see
config/settings.py OSS_* for the local-MinIO-vs-real-Alibaba-OSS swap
mechanics). If OSS isn't configured or the call fails unexpectedly, the
record is *not* marked processed, so the next daily run retries it rather
than silently losing the archival action.
"""

import logging

from celery import shared_task
from django.utils import timezone

from apps.audit.models import AuditLogEntry, RetentionPolicy
from apps.audit.oss import OSSNotConfiguredError, archive_object

logger = logging.getLogger(__name__)

ACTION_LABELS = {
    RetentionPolicy.ActionAfterExpiry.ARCHIVE_TO_COLD_STORAGE: "retention_archived",
    RetentionPolicy.ActionAfterExpiry.LOCK_RECORD: "retention_locked",
    # Deliberately NOT "retention_anonymized": _anonymize() strips nothing
    # under the current schema, and a ledger entry claiming otherwise is a
    # false record in the one system whose purpose is being trustworthy.
    # When a record type does carry PII, the label becomes
    # "retention_anonymized" and every row marked with this one is
    # reprocessed automatically -- _already_processed() matches on the
    # label, so a change of label is a change of what counts as done.
    RetentionPolicy.ActionAfterExpiry.ANONYMIZE: "retention_anonymize_no_pii",
}


def _expired_records(record_type, cutoff):
    """Yields (entity_type, entity_id) for records of record_type past cutoff (their relevant date <= cutoff)."""
    if record_type == RetentionPolicy.RecordType.RAW_INSTRUMENT_FILE:
        from apps.testing.models import TestResult

        qs = TestResult.objects.exclude(raw_file_id__isnull=True).exclude(raw_file_id="").filter(entered_at__lte=cutoff)
        return [("TestResult", pk) for pk in qs.values_list("id", flat=True)]

    if record_type == RetentionPolicy.RecordType.COA_REPORT:
        from apps.reporting.models import Report

        qs = Report.objects.filter(generated_at__lte=cutoff)
        return [("Report", pk) for pk in qs.values_list("id", flat=True)]

    if record_type == RetentionPolicy.RecordType.CALIBRATION_RECORD:
        from apps.equipment.models import CalibrationRecord

        qs = CalibrationRecord.objects.filter(performed_at__lte=cutoff)
        return [("CalibrationRecord", pk) for pk in qs.values_list("id", flat=True)]

    if record_type == RetentionPolicy.RecordType.TRAINING_RECORD:
        from apps.training.models import Enrollment

        qs = Enrollment.objects.filter(created_at__lte=cutoff)
        return [("Enrollment", pk) for pk in qs.values_list("id", flat=True)]

    if record_type == RetentionPolicy.RecordType.AUDIT_LOG_ENTRY:
        qs = AuditLogEntry.objects.filter(timestamp__lte=cutoff)
        return [("AuditLogEntry", pk) for pk in qs.values_list("id", flat=True)]

    return []


def _object_key_for(entity_type, entity_id):
    """Only TestResult.raw_file_id and Report.file_id reference an actual OSS object key."""
    if entity_type == "TestResult":
        from apps.testing.models import TestResult

        return TestResult.objects.filter(pk=entity_id).values_list("raw_file_id", flat=True).first()

    if entity_type == "Report":
        from apps.reporting.models import Report

        return Report.objects.filter(pk=entity_id).values_list("file_id", flat=True).first()

    return None


def _move_to_cold_storage_tier(entity_type, entity_id):
    """
    Calls the real OSS client (apps/audit/oss.py) for the two record types
    that reference an actual object key. Returns True if the record should
    be considered processed (archived, or had no object key to begin with
    -- CalibrationRecord/Enrollment have no OSS object, so this is a
    legitimate no-op for them, not a failure). Returns False only when OSS
    is unreachable/unconfigured or the call fails unexpectedly, so the
    caller skips marking it processed and a future sweep retries.
    """
    key = _object_key_for(entity_type, entity_id)
    if not key:
        logger.info("retention: %s#%s has no OSS object key to archive", entity_type, entity_id)
        return True

    try:
        return archive_object(key)
    except OSSNotConfiguredError:
        logger.warning(
            "retention: OSS not configured, cannot archive %s#%s this run (will retry next sweep)",
            entity_type, entity_id,
        )
        return False
    except Exception:
        logger.exception("retention: failed to archive OSS object for %s#%s", entity_type, entity_id)
        return False


def _anonymize(entity_type, entity_id):
    """
    Strips PII where the record type carries any (Blueprint Section 7.4a,
    RA 10173 data minimization), returning True if anything was actually
    stripped -- the same contract as _move_to_cold_storage_tier, so the
    caller can record what happened rather than what was attempted.

    Always False today. None of the five RetentionPolicy record types carry
    PII fields on themselves under the current schema: it lives on
    CustomerUser, which is not itself a retention-governed record type, and
    an expired Enrollment does not mean that customer is gone. Reaching
    across to mutate a possibly-still-active customer's profile from a
    per-record sweep would be worse than doing nothing.

    Closing this properly needs a decision the schema cannot make -- what
    "last activity" means for a customer, and how long after it their
    identity should persist. ISO/IEC 17025's five-year clock governs
    records; RA 10173 governs people, and they are not the same clock. See
    the Known gaps section of the root README.
    """
    logger.info("retention: %s#%s has no PII fields to strip under the current schema", entity_type, entity_id)
    return False


def _already_processed(entity_type, entity_id, label):
    return AuditLogEntry.objects.filter(entity_type=entity_type, entity_id=entity_id, field_changed=label).exists()


@shared_task(name="apps.audit.tasks.run_retention_sweep")
def run_retention_sweep():
    """Returns a per-record_type count of newly-processed records, for observability in task results/logs."""
    now = timezone.now()
    summary = {}

    for policy in RetentionPolicy.objects.filter(is_active=True):
        cutoff = now - timezone.timedelta(days=policy.retention_days)
        label = ACTION_LABELS[policy.action_after_expiry]
        processed = 0

        for entity_type, entity_id in _expired_records(policy.record_type, cutoff):
            if _already_processed(entity_type, entity_id, label):
                continue

            if policy.action_after_expiry == RetentionPolicy.ActionAfterExpiry.ARCHIVE_TO_COLD_STORAGE:
                if not _move_to_cold_storage_tier(entity_type, entity_id):
                    continue  # OSS call failed; leave unprocessed for the next sweep to retry
                reason = f"RetentionPolicy({policy.record_type}, {policy.retention_days}d): archived to cold storage."
            elif policy.action_after_expiry == RetentionPolicy.ActionAfterExpiry.LOCK_RECORD:
                reason = f"RetentionPolicy({policy.record_type}, {policy.retention_days}d): locked, no further modification permitted."
            else:  # ANONYMIZE
                if _anonymize(entity_type, entity_id):
                    reason = f"RetentionPolicy({policy.record_type}, {policy.retention_days}d): PII stripped."
                else:
                    # Logged rather than skipped silently, so the sweep's own
                    # record shows the policy was applied and found nothing --
                    # an absent entry is indistinguishable from a sweep that
                    # never ran.
                    reason = (
                        f"RetentionPolicy({policy.record_type}, {policy.retention_days}d): "
                        f"no PII on this record type under the current schema; nothing stripped."
                    )

            AuditLogEntry.objects.create(
                actor_id=None,
                actor_type=AuditLogEntry.ActorType.SYSTEM,
                entity_type=entity_type,
                entity_id=entity_id,
                field_changed=label,
                reason=reason,
            )
            processed += 1

        summary[policy.record_type] = processed
        logger.info("retention sweep: %s -> %s (%d newly processed)", policy.record_type, policy.action_after_expiry, processed)

    return summary
