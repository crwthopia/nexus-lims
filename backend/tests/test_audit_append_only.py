"""
FR-E17-02/FR-E17-03: the audit ledger is append-only, enforced by Postgres.

Deliberately at the database layer, in the style of test_row_level_security.py:
these go through `connection` rather than only the API, because the claim
being tested is not "no endpoint deletes an audit row" -- that was already
true, and was only ever an application-layer promise. The claim is that the
*database* refuses, so the ledger stays trustworthy against a future view,
a management command, a `manage.py shell` session, or SQL injection that
forgets the rule (ISO/IEC 17025:2017 8.4.2).

See apps/audit/migrations/0004_audit_log_append_only.py for what this does
not cover -- a superuser, and the owner re-granting to itself.
"""

import pytest
from django.db import DatabaseError, connection, transaction

from apps.audit.models import AuditLogEntry

pytestmark = pytest.mark.django_db


def _an_entry():
    return AuditLogEntry.objects.create(
        actor_id=1,
        actor_type=AuditLogEntry.ActorType.STAFF,
        entity_type="Sample",
        entity_id=1,
        field_changed="status",
        old_value="received",
        new_value="in_prep",
    )


def test_an_insert_is_still_allowed():
    """The ledger has to keep working: INSERT is all signals.py and the retention sweep ever do."""
    entry = _an_entry()

    assert AuditLogEntry.objects.filter(pk=entry.pk).exists()


def test_the_orm_cannot_update_an_entry():
    entry = _an_entry()

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            AuditLogEntry.objects.filter(pk=entry.pk).update(new_value="tampered")

    entry.refresh_from_db()
    assert entry.new_value == "in_prep"


def test_the_orm_cannot_delete_an_entry():
    entry = _an_entry()

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            AuditLogEntry.objects.filter(pk=entry.pk).delete()

    assert AuditLogEntry.objects.filter(pk=entry.pk).exists()


def test_raw_sql_cannot_delete_an_entry():
    """The ORM is not the boundary. Anything holding the app's credentials is refused too."""
    entry = _an_entry()

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM audit_log_entry WHERE id = %s", [entry.pk])

    assert AuditLogEntry.objects.filter(pk=entry.pk).exists()


def test_the_ledger_cannot_be_truncated():
    """TRUNCATE deletes every row without firing a row-level trigger, so it needs its own revoke."""
    entry = _an_entry()

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("TRUNCATE audit_log_entry")

    assert AuditLogEntry.objects.filter(pk=entry.pk).exists()


def test_every_partition_has_update_delete_and_truncate_revoked():
    """
    The invariant that keeps this true as partitions are added.

    audit_log_entry is monthly-partitioned, and Postgres checks DML
    privileges against the table actually named -- so `DELETE FROM
    audit_log_entry_2026_11` is checked against that partition, not the
    parent. Migration 0004 revokes on every partition existing when it runs,
    which it cannot do for partitions created later by the Blueprint Section
    2.1 item 5a task or by pg_partman.

    This test is how that stops being a comment nobody reads: the first
    partition-creation code that does not revoke fails here.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname,
                   has_table_privilege(current_user, c.oid, 'UPDATE'),
                   has_table_privilege(current_user, c.oid, 'DELETE'),
                   has_table_privilege(current_user, c.oid, 'TRUNCATE')
            FROM pg_class c
            JOIN pg_inherits i ON i.inhrelid = c.oid
            WHERE i.inhparent = 'audit_log_entry'::regclass
            ORDER BY c.relname
            """
        )
        writable = [row[0] for row in cursor.fetchall() if any(row[1:])]

    assert writable == [], (
        f"partitions of audit_log_entry still allow UPDATE/DELETE/TRUNCATE: {writable}. "
        "Whatever created them must REVOKE UPDATE, DELETE, TRUNCATE ... FROM CURRENT_USER, "
        "the way apps/audit/migrations/0004_audit_log_append_only.py does."
    )


def test_a_partition_created_after_the_migration_still_refuses_a_delete():
    """
    Proves the claim 0004 rests on: Postgres clones a row-level trigger from
    a partitioned parent onto partitions created afterwards, so a monthly
    partition made next year is covered without anyone remembering to do
    anything. The DDL rolls back with the test's transaction.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE audit_log_entry_append_only_probe
            PARTITION OF audit_log_entry FOR VALUES FROM ('1990-01-01') TO ('1990-02-01')
            """
        )
        cursor.execute(
            """
            INSERT INTO audit_log_entry (actor_type, entity_type, entity_id, field_changed, reason, "timestamp")
            VALUES ('system', 'Sample', 1, '', 'probe', '1990-01-15T00:00:00Z')
            """
        )

        with pytest.raises(DatabaseError, match="append-only"):
            with transaction.atomic():
                cursor.execute("DELETE FROM audit_log_entry_append_only_probe")
