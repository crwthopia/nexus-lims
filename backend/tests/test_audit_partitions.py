"""
Monthly partition creation for audit_log_entry (Blueprint Section 2.1 item 5a).

Migration 0003 seeded three months and deferred the rest to a beat task that
did not exist. This is that task, and the tests are shaped by the two
PostgreSQL facts that make falling behind unrecoverable:

  1. `CREATE TABLE ... PARTITION OF` fails if the default partition already
     holds a row belonging to the new range, so a month cannot be created
     late once rows for it have arrived.
  2. Moving those rows out needs DELETE on the default partition, which
     migration 0004 revoked from the application role.

Together those mean the task's real job is to never fall behind, and to be
loud when it has -- so most of what is tested here is headroom, idempotence,
and whether the alarm actually fires.

The append-only invariant is the other half: a REVOKE on the partitioned
parent does not reach a partition created afterwards, so every partition this
task touches has to be revoked individually or
tests/test_audit_append_only.py stops passing the moment a month rolls over.
"""

import datetime

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.audit.models import AuditLogEntry, SystemFailure
from apps.audit.tasks import (
    DEFAULT_PARTITION,
    _months_from,
    _next_month,
    create_audit_log_partitions,
)

pytestmark = pytest.mark.django_db


def _partitions():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_inherits i ON i.inhrelid = c.oid
            WHERE i.inhparent = 'audit_log_entry'::regclass
            ORDER BY c.relname
            """
        )
        return [row[0] for row in cursor.fetchall()]


def _writable_partitions():
    """Partitions the application role could still mutate -- should always be none."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_inherits i ON i.inhrelid = c.oid
            WHERE i.inhparent = 'audit_log_entry'::regclass
              AND (has_table_privilege(current_user, c.oid, 'UPDATE')
                OR has_table_privilege(current_user, c.oid, 'DELETE')
                OR has_table_privilege(current_user, c.oid, 'TRUNCATE'))
            ORDER BY c.relname
            """
        )
        return [row[0] for row in cursor.fetchall()]


def _insert_at(when, entity_id=1):
    """An audit row at an explicit timestamp; `timestamp` is auto_now_add via the ORM."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO audit_log_entry
                (actor_type, entity_type, entity_id, field_changed, old_value, new_value, reason, "timestamp")
            VALUES ('system', 'Sample', %s, 'status', NULL, 'received', '', %s)
            """,
            [entity_id, when],
        )


def _partition_name(day):
    return f"audit_log_entry_{day:%Y_%m}"


# --- Month arithmetic ------------------------------------------------------

def test_december_rolls_into_january():
    assert _next_month(datetime.date(2026, 12, 14)) == datetime.date(2027, 1, 1)


def test_months_from_starts_at_the_first_of_the_given_month():
    months = list(_months_from(datetime.date(2026, 11, 23), 3))

    assert months == [datetime.date(2026, 11, 1), datetime.date(2026, 12, 1), datetime.date(2027, 1, 1)]


# --- Creating ahead of need ------------------------------------------------

def test_it_creates_the_configured_months_of_headroom(settings):
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 5
    today = timezone.localdate()

    create_audit_log_partitions()

    partitions = _partitions()
    for start in _months_from(today, 6):
        assert _partition_name(start) in partitions


def test_running_it_twice_creates_nothing_the_second_time(settings):
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 4

    create_audit_log_partitions()
    second = create_audit_log_partitions()

    assert second["created"] == []
    assert second["failed"] == []


def test_it_leaves_the_partitions_migration_0003_already_made(settings):
    """The seeded months are not recreated, and not disturbed."""
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 3
    before = set(_partitions())

    create_audit_log_partitions()

    assert before <= set(_partitions())


# --- The append-only invariant, which is the point -------------------------

def test_every_partition_it_creates_is_revoked(settings):
    """
    A REVOKE on the parent does not reach a partition created later --
    verified directly against PostgreSQL. Without this the ledger silently
    becomes mutable the month a new partition appears.
    """
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 6

    create_audit_log_partitions()

    assert _writable_partitions() == []


def test_it_repairs_a_partition_somebody_else_created(settings):
    """
    pg_partman, or a DBA at 3am, makes a partition and does not revoke on it.
    The task re-asserts across everything rather than only what it created,
    so the hole closes on the next nightly run instead of waiting for an
    assessor to find it.
    """
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 1
    far_off = datetime.date(2031, 7, 1)
    name = _partition_name(far_off)
    with connection.cursor() as cursor:
        cursor.execute(
            f'CREATE TABLE "{name}" PARTITION OF audit_log_entry FOR VALUES FROM (%s) TO (%s)',
            [far_off, _next_month(far_off)],
        )
    assert name in _writable_partitions()

    create_audit_log_partitions()

    assert _writable_partitions() == []


def test_a_row_written_after_the_sweep_is_still_append_only(settings):
    """End to end: the new partition holds a real row, and refuses to give it up."""
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 4
    create_audit_log_partitions()
    next_quarter = list(_months_from(timezone.localdate(), 4))[-1]
    _insert_at(datetime.datetime.combine(next_quarter, datetime.time(12, 0), tzinfo=datetime.timezone.utc))

    with connection.cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM "{_partition_name(next_quarter)}"')
        assert cursor.fetchone()[0] == 1

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'DELETE FROM "{_partition_name(next_quarter)}"')


# --- Falling behind: the trap ----------------------------------------------

def test_a_month_already_stranded_in_the_default_cannot_be_created(settings):
    """
    Fact 1. Rows for a month with no partition go to the default, and after
    that the month can no longer be partitioned -- Postgres refuses because
    the default's constraint would be violated.
    """
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 6
    stranded_month = list(_months_from(timezone.localdate(), 6))[-1]
    _insert_at(datetime.datetime.combine(stranded_month, datetime.time(9, 0), tzinfo=datetime.timezone.utc))

    result = create_audit_log_partitions()

    assert _partition_name(stranded_month) in result["failed"]


def test_one_impossible_month_does_not_stop_the_others(settings):
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 6
    months = list(_months_from(timezone.localdate(), 7))
    stranded = months[-1]
    _insert_at(datetime.datetime.combine(stranded, datetime.time(9, 0), tzinfo=datetime.timezone.utc))

    result = create_audit_log_partitions()

    assert result["failed"] == [_partition_name(stranded)]
    for start in months[:-1]:
        assert _partition_name(start) in _partitions()


def test_a_failed_creation_is_recorded_as_a_system_failure(settings):
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 6
    stranded = list(_months_from(timezone.localdate(), 6))[-1]
    _insert_at(datetime.datetime.combine(stranded, datetime.time(9, 0), tzinfo=datetime.timezone.utc))

    create_audit_log_partitions()

    failure = SystemFailure.objects.get(summary="audit_log_entry monthly partition could not be created")
    assert failure.severity == SystemFailure.Severity.FAILED
    # The operator needs to know this is not something the app can repair.
    assert "DBA operation under a superuser" in failure.detail


def test_rows_sitting_in_the_default_raise_the_alarm(settings):
    """
    Fact 2. Invisible day to day, and unfixable from here, so it is a system
    failure rather than a log line nobody reads.
    """
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 1
    _insert_at(datetime.datetime(2033, 4, 4, 10, 0, tzinfo=datetime.timezone.utc))

    create_audit_log_partitions()

    failure = SystemFailure.objects.get(summary="audit log rows have landed in the default partition")
    assert "cannot be moved by the application" in failure.detail


def test_an_empty_default_partition_raises_nothing(settings):
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 2

    create_audit_log_partitions()

    assert not SystemFailure.objects.filter(
        summary="audit log rows have landed in the default partition"
    ).exists()


def test_ordinary_audit_writes_are_unaffected(settings):
    """The ledger keeps working while all this happens around it."""
    settings.AUDIT_PARTITION_MONTHS_AHEAD = 3
    create_audit_log_partitions()

    entry = AuditLogEntry.objects.create(
        actor_id=None,
        actor_type=AuditLogEntry.ActorType.SYSTEM,
        entity_type="Sample",
        entity_id=99,
        field_changed="status",
        new_value="received",
    )

    assert AuditLogEntry.objects.filter(pk=entry.pk).exists()
    assert _writable_partitions() == []
