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

import datetime
import logging

from celery import shared_task
from django.utils import timezone

from apps.audit.failures import record_failure
from apps.audit.models import AuditLogEntry, RetentionPolicy, SystemFailure
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
    except OSSNotConfiguredError as exc:
        logger.warning(
            "retention: OSS not configured, cannot archive %s#%s this run (will retry next sweep)",
            entity_type, entity_id,
        )
        # Recorded rather than only logged (ISO/IEC 17025:2017 7.11.3(e)).
        # These two branches are the reason the register cannot rely on the
        # task_failure signal alone: they swallow the error deliberately so
        # the sweep carries on with the other records, which means the task
        # succeeds and task_failure never fires. A retention action that
        # silently did not happen is exactly what 7.11.3(e) is for.
        #
        # DEGRADED, not FAILED: the record is left unprocessed on purpose
        # and the next nightly sweep retries it -- see _already_processed.
        record_failure(
            SystemFailure.Component.OBJECT_STORAGE,
            "retention archival skipped: object storage is not configured",
            detail=f"{entity_type}#{entity_id}: {exc}",
            severity=SystemFailure.Severity.DEGRADED,
            immediate_action=SystemFailure.ImmediateAction.RETRY_SCHEDULED,
        )
        return False
    except Exception as exc:  # noqa: BLE001 -- recorded, then the sweep continues
        logger.exception("retention: failed to archive OSS object for %s#%s", entity_type, entity_id)
        record_failure(
            SystemFailure.Component.OBJECT_STORAGE,
            f"retention archival raised {type(exc).__name__}",
            detail=f"{entity_type}#{entity_id}: {exc}",
            severity=SystemFailure.Severity.DEGRADED,
            immediate_action=SystemFailure.ImmediateAction.RETRY_SCHEDULED,
        )
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


# --- Monthly partition creation (Blueprint Section 2.1 item 5a) ------------

PARTITION_PREFIX = "audit_log_entry_"
DEFAULT_PARTITION = "audit_log_entry_default"


def _next_month(day):
    return datetime.date(day.year + 1, 1, 1) if day.month == 12 else datetime.date(day.year, day.month + 1, 1)


def _months_from(first, count):
    """The first of `first`'s month, then the first of each following month."""
    start = first.replace(day=1)
    for _ in range(count):
        yield start
        start = _next_month(start)


def _existing_partitions(cursor):
    cursor.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_inherits i ON i.inhrelid = c.oid
        WHERE i.inhparent = 'audit_log_entry'::regclass
        """
    )
    return {row[0] for row in cursor.fetchall()}


def _revoke_on(cursor, partition):
    """
    Take UPDATE/DELETE/TRUNCATE away from the application's own role.

    Applied to every partition on every run, not only the ones just created.
    A REVOKE on the partitioned parent does *not* reach a partition created
    afterwards -- verified against PostgreSQL, where a partition created after
    the parent was revoked still reports has_table_privilege(DELETE) = true --
    so each partition needs its own. A partition made by anything else
    (pg_partman, a DBA at 3am) would otherwise be a hole in the append-only
    ledger that nobody notices until an assessor asks.

    Doing it unconditionally makes this task the thing that *maintains* the
    invariant rather than merely not breaking it, and it is what keeps
    tests/test_audit_append_only.py passing as partitions come and go.

    The name is derived from a date this module formatted or read back from
    pg_class, never from user input, so it cannot carry an injection.
    """
    cursor.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON "{partition}" FROM CURRENT_USER')


@shared_task(name="apps.audit.tasks.create_audit_log_partitions")
def create_audit_log_partitions():
    """
    Create the monthly audit_log_entry partitions ahead of need, and keep the
    append-only revoke true for every partition that exists.

    Migration 0003 seeded the current month and the two after it, then said
    the Blueprint Section 2.1 item 5a beat task took over from there. No such
    task existed, so once those three months elapsed every audit row landed in
    `audit_log_entry_default` -- still working and still protected, but the
    partitioning was decorative and the default grew without bound.

    **Falling behind is not recoverable by this application**, which is why
    this runs daily rather than monthly. Two facts, both verified against
    PostgreSQL, combine badly:

      1. `CREATE TABLE ... PARTITION OF` fails outright if the default
         partition already holds a row belonging to the new range: "updated
         partition constraint for default partition would be violated by some
         row". The month cannot simply be created late.
      2. Moving those rows out of the default needs DELETE on it, which
         migration 0004 revoked from this very role. The rescue is a DBA
         operation under a superuser; the app cannot do it.

    So the failure mode is a trap -- fall behind by a month and the gap can
    only widen. Daily runs with three months of headroom give roughly ninety
    attempts before any partition is actually needed, and both a creation
    failure and any row found sitting in the default are recorded as system
    failures (7.11.3(e)) rather than logged and forgotten.
    """
    from django.conf import settings
    from django.db import connection, transaction

    first_of_month = timezone.localdate().replace(day=1)
    # +1 so AUDIT_PARTITION_MONTHS_AHEAD counts months *beyond* this one.
    wanted = list(_months_from(first_of_month, settings.AUDIT_PARTITION_MONTHS_AHEAD + 1))

    with connection.cursor() as cursor:
        existing = _existing_partitions(cursor)

    created, failed = [], []

    for start in wanted:
        name = f"{PARTITION_PREFIX}{start:%Y_%m}"
        if name in existing:
            continue
        try:
            # Its own transaction: one month that cannot be created must not
            # take the others down with it, and in Postgres a failed statement
            # aborts the whole transaction unless it is contained.
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    f'CREATE TABLE "{name}" PARTITION OF audit_log_entry FOR VALUES FROM (%s) TO (%s)',
                    [start, _next_month(start)],
                )
                _revoke_on(cursor, name)
            created.append(name)
            logger.info("audit partitions: created %s", name)
        except Exception as exc:  # noqa: BLE001 -- recorded, then the next month is tried
            failed.append(name)
            logger.exception("audit partitions: could not create %s", name)
            record_failure(
                SystemFailure.Component.DATABASE,
                "audit_log_entry monthly partition could not be created",
                detail=(
                    f"{name}: {exc}\n\n"
                    "If this says the default partition's constraint would be violated, rows for "
                    "that month are already in audit_log_entry_default and the partition can no "
                    "longer be created. Moving them needs DELETE on the default partition, which "
                    "migration 0004 revoked from the application role -- so this is a DBA "
                    "operation under a superuser, not something the application can repair."
                ),
                severity=SystemFailure.Severity.FAILED,
                immediate_action=SystemFailure.ImmediateAction.NONE,
            )

    # Re-assert the revoke across everything, including partitions that
    # already existed. See _revoke_on for why this is not redundant.
    with connection.cursor() as cursor:
        for partition in sorted(_existing_partitions(cursor)):
            _revoke_on(cursor, partition)

    _warn_if_rows_are_stranded_in_default()

    logger.info("audit partitions: %d created, %d failed", len(created), len(failed))
    return {"created": created, "failed": failed}


def _warn_if_rows_are_stranded_in_default():
    """
    Rows in the default partition mean this task fell behind at some point.

    Worth a system failure rather than a log line, because it is both
    invisible day to day and unfixable from here: those months can no longer
    be given a partition (fact 1 above), and the rows cannot be moved (fact
    2). The longer it goes unnoticed the more months are stranded.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM "{DEFAULT_PARTITION}"')  # noqa: S608 -- constant name
        stranded = cursor.fetchone()[0]

    if not stranded:
        return

    logger.warning("audit partitions: %d row(s) sitting in %s", stranded, DEFAULT_PARTITION)
    record_failure(
        SystemFailure.Component.DATABASE,
        "audit log rows have landed in the default partition",
        detail=(
            f"{stranded} row(s) are in {DEFAULT_PARTITION}, meaning monthly partition creation "
            "fell behind. Those months can no longer be partitioned while the rows sit there, and "
            "the rows cannot be moved by the application: migration 0004 revoked DELETE on the "
            "default partition. Recovery is a DBA operation under a superuser -- detach the "
            "default, move the rows into freshly created monthly partitions, reattach."
        ),
        severity=SystemFailure.Severity.FAILED,
        immediate_action=SystemFailure.ImmediateAction.NONE,
    )
