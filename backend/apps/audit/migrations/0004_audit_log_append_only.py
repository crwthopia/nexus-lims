"""
Enforce FR-E17-02/03 append-only in the database instead of by convention.

apps/audit/models.py has always said AuditLogEntry is append-only, and
qualified it honestly: "enforced in apps.audit.permissions / admin.py (not
representable as a pure model-layer constraint)". That is an application-layer
promise. It holds for as long as every future view, management command,
migration and `manage.py shell` session remembers to keep it -- and the whole
point of an audit ledger under ISO/IEC 17025:2017 8.4.2 is to be trustworthy
against exactly the case where something does not.

So the same move the RLS work already made twice: stop asking the application
to be careful, and let Postgres refuse. Two mechanisms, because on a
partitioned table neither one covers the whole surface:

  REVOKE UPDATE, DELETE, TRUNCATE
      Postgres checks DML privileges against the table actually named, so a
      statement routed through the partitioned parent is checked against the
      parent, and `DELETE FROM audit_log_entry_2026_08` is checked against
      that partition. Both are revoked -- the parent and every partition that
      exists when this runs. This is also the version an assessor can read:
      the application's database role holds INSERT and SELECT on the ledger
      and nothing else, which is one `\\dp` away from being demonstrated.

  BEFORE UPDATE OR DELETE ... FOR EACH ROW
      Postgres clones a row-level trigger from a partitioned parent onto
      every partition, including partitions created later. That is what
      covers the monthly partitions the Blueprint's Section 2.1 item 5a task
      (or pg_partman) will create after this migration, which the REVOKE
      above cannot reach because they do not exist yet.

The two overlap deliberately. Verified against PostgreSQL 16: with both in
place, UPDATE/DELETE/TRUNCATE are refused through the parent, directly
against an existing partition, and directly against a partition created
afterwards; INSERT is unaffected, which matters because that is all
apps/audit/signals.py and the retention sweep ever do.

WHAT THIS DOES NOT STOP, stated plainly so nobody mistakes it for more than
it is:

  - A superuser. Superusers bypass privilege checks entirely (the same
    reason infra/ provisions the app account as Normal rather than
    superuser, and the same reason the RLS policies needed FORCE).
  - The table's owner re-granting to itself. The application role owns these
    tables, so it can GRANT the privileges back and then disable the trigger.
    That is not a hole this migration can close: closing it means the
    application connecting as a role that does not own the schema, with
    migrations run by a separate DDL role. That is a deployment change
    (infra/ and docker-entrypoint.sh both assume one role today), not a
    schema change, and it is the right next step if NASAT wants the ledger
    hardened against a compromised application rather than against its own
    mistakes.

  - TRUNCATE of a partition created after this migration. TRUNCATE triggers
    are statement-level and Postgres does *not* clone them onto partitions
    the way it clones row-level triggers, so the parent's truncate trigger
    does not fire for `TRUNCATE audit_log_entry_2026_11` directly, and the
    REVOKE could not have covered a table that did not exist. Whatever
    creates monthly partitions must therefore revoke on each one as it
    creates it. That requirement is not left as a comment: 
    tests/test_audit_append_only.py asserts that *every* partition of
    audit_log_entry has UPDATE/DELETE/TRUNCATE revoked, so the first
    partition-creation code that forgets fails CI rather than shipping.

Blueprint Section 3.1 / Section 7.2; FR-E17-02 (append-only), FR-E17-03
(rows cannot be deleted); ISO/IEC 17025:2017 8.4.2.
"""

from django.db import migrations

APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION audit_log_entry_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION
        'audit_log_entry is append-only (FR-E17-02, ISO/IEC 17025:2017 8.4.2): % rejected on %',
        TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$fn$;

-- Row-level, so Postgres clones it onto every partition, including the
-- monthly partitions created after this migration runs.
CREATE TRIGGER audit_log_entry_append_only
    BEFORE UPDATE OR DELETE ON audit_log_entry
    FOR EACH ROW EXECUTE FUNCTION audit_log_entry_reject_mutation();

-- Statement-level, and therefore NOT cloned onto partitions -- it covers
-- TRUNCATE of the parent only. Partitions are covered by the REVOKE below
-- while they exist; see the module docstring for the ones that do not yet.
CREATE TRIGGER audit_log_entry_append_only_truncate
    BEFORE TRUNCATE ON audit_log_entry
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_entry_reject_mutation();

-- CURRENT_USER rather than a hardcoded role name: the application connects
-- as whatever POSTGRES_USER names (nasat_lims in dev and CI, the
-- alicloud_db_account in infra/main.tf), and migrations run as that same
-- role. If the runtime and DDL roles are ever split -- see the docstring --
-- this becomes an explicit REVOKE ... FROM <runtime role>.
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log_entry FROM CURRENT_USER;

DO $do$
DECLARE
    partition regclass;
BEGIN
    FOR partition IN
        SELECT inhrelid::regclass
        FROM pg_inherits
        WHERE inhparent = 'audit_log_entry'::regclass
    LOOP
        EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON %s FROM CURRENT_USER', partition);
    END LOOP;
END
$do$;
"""

REVERSE_SQL = """
DO $do$
DECLARE
    partition regclass;
BEGIN
    FOR partition IN
        SELECT inhrelid::regclass
        FROM pg_inherits
        WHERE inhparent = 'audit_log_entry'::regclass
    LOOP
        EXECUTE format('GRANT UPDATE, DELETE, TRUNCATE ON %s TO CURRENT_USER', partition);
    END LOOP;
END
$do$;

GRANT UPDATE, DELETE, TRUNCATE ON audit_log_entry TO CURRENT_USER;

DROP TRIGGER IF EXISTS audit_log_entry_append_only_truncate ON audit_log_entry;
DROP TRIGGER IF EXISTS audit_log_entry_append_only ON audit_log_entry;
DROP FUNCTION IF EXISTS audit_log_entry_reject_mutation();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0003_partition_audit_log_entry"),
    ]

    operations = [
        migrations.RunSQL(sql=APPEND_ONLY_SQL, reverse_sql=REVERSE_SQL),
    ]
