"""
Convert audit_log_entry into a native PostgreSQL declarative range-partitioned
table, partitioned monthly on `timestamp` (Blueprint Section 2.1 item 5a,
closes Section 13 gap 11).

Rationale (from the blueprint): every create/update/delete on a regulated
entity writes an AuditLogEntry row (FR-E17-01), and rows cannot be deleted
(FR-E17-03, ISO/IEC 17025:2017 8.4.2), so this table only grows. Monthly
partitioning was locked in over yearly because small monthly partitions cost
little if volume is lower than expected, whereas splitting an already-massive
yearly partition later is a high-risk live-table migration.

Django's migration framework has no native representation for PARTITION BY,
so this is applied as raw SQL against the table Django already created in
0001_initial. ApsaraDB RDS for PostgreSQL (Blueprint Section 2.2) supports
native declarative partitioning; no extension is required, though NASAT may
opt to manage partition creation via pg_partman instead of the Celery beat
task referenced in Section 2.1 item 5a.

NOTE: this migration recreates the table as partitioned and therefore should
run immediately after 0001_initial/0002_seed_retention_policy, before any
production AuditLogEntry rows exist. If NASAT already has production data in
this table by the time this migration is applied, it must be adapted to a
data-preserving partition conversion (rename + reinsert) rather than this
drop-and-recreate approach.
"""

from django.db import migrations

CREATE_PARTITIONED_SQL = """
-- Rename the plain table Django created, then rebuild it as a partitioned
-- parent table with the same columns, reattaching data via a default
-- partition so no rows are lost if any already exist.
ALTER TABLE audit_log_entry RENAME TO audit_log_entry_legacy;

CREATE TABLE audit_log_entry (
    id BIGSERIAL,
    actor_id BIGINT NULL,
    actor_type VARCHAR(16) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    entity_id BIGINT NOT NULL,
    field_changed VARCHAR(128) NOT NULL DEFAULT '',
    old_value TEXT NULL,
    new_value TEXT NULL,
    reason TEXT NOT NULL DEFAULT '',
    "timestamp" TIMESTAMPTZ NOT NULL,
    e_signature_id BIGINT NULL REFERENCES e_signature(id) ON DELETE SET NULL,
    PRIMARY KEY (id, "timestamp")
) PARTITION BY RANGE ("timestamp");

CREATE INDEX audit_log_entry_entity_idx ON audit_log_entry (entity_type, entity_id);
CREATE INDEX audit_log_entry_timestamp_idx ON audit_log_entry ("timestamp");

-- Default partition catches any row outside explicitly created monthly
-- partitions (e.g. before the first scheduled partition-creation run).
CREATE TABLE audit_log_entry_default PARTITION OF audit_log_entry DEFAULT;

INSERT INTO audit_log_entry
SELECT id, actor_id, actor_type, entity_type, entity_id, field_changed, old_value, new_value, reason, "timestamp", e_signature_id
FROM audit_log_entry_legacy;

DROP TABLE audit_log_entry_legacy;

-- Seed the current and next 2 months of partitions; the Celery beat task
-- referenced in Blueprint Section 2.1 item 5a is responsible for creating
-- new monthly partitions ahead of need thereafter.
DO $$
DECLARE
    partition_start date := date_trunc('month', now());
    partition_end date;
    i int;
BEGIN
    FOR i IN 0..2 LOOP
        partition_end := partition_start + interval '1 month';
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS audit_log_entry_%s PARTITION OF audit_log_entry FOR VALUES FROM (%L) TO (%L)',
            to_char(partition_start, 'YYYY_MM'),
            partition_start,
            partition_end
        );
        partition_start := partition_end;
    END LOOP;
END $$;
"""

REVERSE_SQL = """
ALTER TABLE audit_log_entry RENAME TO audit_log_entry_partitioned_legacy;

CREATE TABLE audit_log_entry (
    id BIGSERIAL PRIMARY KEY,
    actor_id BIGINT NULL,
    actor_type VARCHAR(16) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    entity_id BIGINT NOT NULL,
    field_changed VARCHAR(128) NOT NULL DEFAULT '',
    old_value TEXT NULL,
    new_value TEXT NULL,
    reason TEXT NOT NULL DEFAULT '',
    "timestamp" TIMESTAMPTZ NOT NULL,
    e_signature_id BIGINT NULL REFERENCES e_signature(id) ON DELETE SET NULL
);

INSERT INTO audit_log_entry
SELECT id, actor_id, actor_type, entity_type, entity_id, field_changed, old_value, new_value, reason, "timestamp", e_signature_id
FROM audit_log_entry_partitioned_legacy;

DROP TABLE audit_log_entry_partitioned_legacy;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0002_seed_retention_policy"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_PARTITIONED_SQL, reverse_sql=REVERSE_SQL),
    ]
