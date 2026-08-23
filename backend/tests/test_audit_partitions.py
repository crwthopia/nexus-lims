"""
audit_log_entry's monthly partitions have to exist before rows arrive.

Migration 0003 seeds the current month plus two and says a beat task keeps
them going "ahead of need thereafter". No such task existed. Nothing fails
when the seeded months run out -- rows land in audit_log_entry_default --
and the damage only surfaces later, when creating the partition that month
should have had is refused because the default already holds overlapping
rows. Harmless while nothing wrote to the table; dated from the moment
FR-E17-01 started routing every regulated write here.
"""

from datetime import date

import pytest
from django.db import connection

from apps.audit.partitions import ensure_partitions

pytestmark = pytest.mark.django_db


def partitions():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname FROM pg_class c "
            "JOIN pg_inherits i ON i.inhrelid = c.oid "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "WHERE p.relname = 'audit_log_entry' ORDER BY 1"
        )
        return [row[0] for row in cursor.fetchall()]


def insert_at(timestamp, entity_id=1):
    """A row at an explicit timestamp -- the column is auto_now_add via the ORM."""
    with connection.cursor() as cursor:
        cursor.execute(
            'INSERT INTO audit_log_entry '
            '(actor_type, entity_type, entity_id, field_changed, reason, "timestamp") '
            "VALUES ('system', 'Probe', %s, '', 'test', %s)",
            [entity_id, timestamp],
        )


def rows_in(table, **_):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table}")
        return cursor.fetchone()[0]


# --- Ordinary operation ----------------------------------------------------

def test_it_creates_the_months_that_are_missing():
    created, _ = ensure_partitions(months_ahead=6, today=date(2027, 3, 15))

    assert "audit_log_entry_2027_03" in created
    assert "audit_log_entry_2027_09" in created
    assert "audit_log_entry_2027_10" not in created, "reached past months_ahead"


def test_it_spans_a_year_boundary():
    created, _ = ensure_partitions(months_ahead=3, today=date(2027, 11, 20))

    assert "audit_log_entry_2027_12" in created
    assert "audit_log_entry_2028_01" in created
    assert "audit_log_entry_2028_02" in created


def test_running_it_twice_creates_nothing_the_second_time():
    """Scheduled daily, so being a no-op is the normal case, not an edge one."""
    ensure_partitions(months_ahead=4, today=date(2027, 6, 1))

    created, rescued = ensure_partitions(months_ahead=4, today=date(2027, 6, 1))

    assert created == []
    assert rescued == 0


def test_a_row_lands_in_its_own_partition_once_it_exists():
    ensure_partitions(months_ahead=2, today=date(2027, 5, 1))

    insert_at("2027-05-10 12:00:00+00")

    assert rows_in("audit_log_entry_2027_05") == 1


# --- The rescue path -------------------------------------------------------

def test_it_rescues_rows_that_already_fell_into_the_default():
    """
    The failure this exists to prevent. Postgres refuses to create a
    partition overlapping rows already in the default, so without the
    detach/move/reattach these months could never be partitioned at all.
    """
    insert_at("2027-07-04 09:00:00+00", entity_id=41)
    insert_at("2027-07-19 09:00:00+00", entity_id=42)
    assert rows_in("audit_log_entry_default") >= 2

    created, rescued = ensure_partitions(months_ahead=0, today=date(2027, 7, 1))

    assert "audit_log_entry_2027_07" in created
    assert rescued == 2
    assert rows_in("audit_log_entry_2027_07") == 2


def test_the_rescue_keeps_default_rows_for_other_months_where_they_are():
    insert_at("2027-07-04 09:00:00+00")
    insert_at("2028-11-04 09:00:00+00")  # far outside the range being created

    _, rescued = ensure_partitions(months_ahead=0, today=date(2027, 7, 1))

    assert rescued == 1
    assert rows_in("audit_log_entry_default") == 1


def test_the_rescued_row_is_still_readable_through_the_parent():
    """Moving rows between partitions must not lose them from the table."""
    insert_at("2027-07-04 09:00:00+00", entity_id=4242)

    ensure_partitions(months_ahead=0, today=date(2027, 7, 1))

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM audit_log_entry WHERE entity_id = 4242")
        assert cursor.fetchone()[0] == 1


# --- The dangerous failure -------------------------------------------------

def test_a_failure_mid_rescue_leaves_the_default_partition_attached(monkeypatch):
    """
    DETACH succeeding and ATTACH not would leave the table with no default
    partition, so every insert outside an explicit month starts erroring --
    a worse outage than the problem being fixed. The whole thing runs in one
    transaction so a partial run rolls back.
    """
    insert_at("2027-07-04 09:00:00+00")
    before = partitions()

    import apps.audit.partitions as module

    def boom(*args, **kwargs):
        raise RuntimeError("interrupted mid-rescue")

    # Patched at the *last* step, so the detach, the create and the row move
    # have all really happened by the time this raises. Patching the whole
    # rescue instead would mean the detach never ran and this test would
    # pass with or without the surrounding transaction.
    monkeypatch.setattr(module, "_reattach_default", boom)

    with pytest.raises(RuntimeError):
        ensure_partitions(months_ahead=0, today=date(2027, 7, 1))

    assert "audit_log_entry_default" in partitions()
    assert partitions() == before, "partition layout changed despite the failure"
    insert_at("2029-01-01 09:00:00+00")  # still accepted, i.e. default is live


# --- Wiring ----------------------------------------------------------------

def test_the_task_is_scheduled():
    from django.conf import settings

    tasks = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert "apps.audit.tasks.ensure_audit_partitions" in tasks


def test_the_task_uses_the_configured_lookahead(settings):
    from apps.audit.tasks import ensure_audit_partitions

    settings.AUDIT_PARTITION_MONTHS_AHEAD = 0
    result = ensure_audit_partitions()

    assert result["created"] == [], "current month should already be partitioned"
