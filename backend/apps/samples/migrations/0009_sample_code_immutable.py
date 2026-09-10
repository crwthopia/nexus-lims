"""
Make `sample.unique_sample_code` immutable in Postgres, not just in the
serializer.

ISO/IEC 17025:2017 7.4.2 requires a system of identification that is
retained for the life of the item in the laboratory, and that ensures items
are never confused physically or when referred to in records. The moment a
code is printed on a container, the database row and the physical object
are two copies of one fact -- and only one of them can be edited.

The same reasoning as apps/audit/migrations/0004: the ORM is not the only
thing that issues UPDATEs. A serializer's `read_only_fields` is invisible
to a management command, a data migration, a psql session, or a future
endpoint written by somebody who did not read this file. A BEFORE UPDATE
trigger is visible to all of them.

Scope, stated plainly so nobody assumes more than is here:

  - INSERT is untouched. Allocation is apps/samples/identity.py's job.
  - A superuser can still drop the trigger. So can this table's owner. That
    is the same residual exposure the audit log's append-only migration
    documents, and the same deployment change (a separate owner role) would
    close both.
  - `historicalsample` is deliberately not covered: it is the record of
    what the code *was*, and simple-history writes a new row rather than
    editing one.

DELETE is likewise untouched -- an item booked in by mistake is deleted,
not renamed, and the history row survives it.
"""

from django.db import migrations

FORBID_CODE_CHANGE_SQL = """
CREATE OR REPLACE FUNCTION sample_code_is_immutable() RETURNS trigger AS $$
BEGIN
    IF NEW.unique_sample_code IS DISTINCT FROM OLD.unique_sample_code THEN
        RAISE EXCEPTION
            'sample.unique_sample_code is immutable (ISO/IEC 17025:2017 7.4.2): '
            'attempted to change % to % on sample %',
            OLD.unique_sample_code, NEW.unique_sample_code, OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sample_code_immutable
    BEFORE UPDATE ON sample
    FOR EACH ROW
    EXECUTE FUNCTION sample_code_is_immutable();
"""

ALLOW_CODE_CHANGE_SQL = """
DROP TRIGGER IF EXISTS sample_code_immutable ON sample;
DROP FUNCTION IF EXISTS sample_code_is_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0008_backfill_custody_event_occurred_at"),
    ]

    operations = [
        migrations.RunSQL(sql=FORBID_CODE_CHANGE_SQL, reverse_sql=ALLOW_CODE_CHANGE_SQL),
    ]
