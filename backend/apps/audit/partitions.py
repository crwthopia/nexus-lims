"""
Keeps audit_log_entry's monthly partitions ahead of need.

apps/audit/migrations/0003 built the table as a monthly range-partitioned
table and seeded the current month plus two, noting that "the Celery beat
task referenced in Blueprint Section 2.1 item 5a is responsible for
creating new monthly partitions ahead of need thereafter". That task did
not exist. Seeded partitions run out, and every row past them falls into
audit_log_entry_default.

Nothing fails when that happens, which is what makes it dangerous. The
default partition accepts the rows, and the damage only shows up when
somebody later tries to create the partition that month should have had:

    ERROR: updated partition constraint for default partition
    "audit_log_entry_default" would be violated by some row

Postgres will not create a partition whose range overlaps rows already
sitting in the default. Recovering means detaching the default, creating
the partition, moving the rows across, and reattaching -- which this module
does, rather than leaving an operator to discover the procedure under
pressure. It was a theoretical problem while nothing wrote to the table; it
became a dated one when FR-E17-01 started routing every write to a
regulated entity here.

The whole operation runs in one transaction. Postgres DDL is transactional,
and the failure mode otherwise is severe: DETACH succeeding and ATTACH not
leaves the table with no default partition at all, so any insert outside
the explicit monthly ranges starts erroring. Rolling back is the only safe
answer to a partial run.

DETACH PARTITION takes an ACCESS EXCLUSIVE lock on the parent for the
duration. DETACH ... CONCURRENTLY avoids that but cannot run inside a
transaction block, which would trade a brief blocking window for the
possibility of being left with no default partition. The lock is the better
trade here, and it is only taken on the recovery path -- the ordinary case,
where the default holds no rows for the month, is a plain CREATE.
"""

import logging
from datetime import date

from django.db import connection, transaction

logger = logging.getLogger(__name__)

PARENT_TABLE = "audit_log_entry"
DEFAULT_PARTITION = f"{PARENT_TABLE}_default"


def _month_starts(from_date, count):
    """`count` month-start dates beginning with the month `from_date` is in."""
    year, month = from_date.year, from_date.month
    for _ in range(count):
        yield date(year, month, 1)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _next_month(start):
    return date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)


def _partition_name(start):
    return f"{PARENT_TABLE}_{start.year}_{start.month:02d}"


def _exists(cursor, name):
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [name])
    return cursor.fetchone()[0]


def _default_holds_rows_in(cursor, start, end):
    cursor.execute(
        f'SELECT EXISTS (SELECT 1 FROM {DEFAULT_PARTITION} '
        f'WHERE "timestamp" >= %s AND "timestamp" < %s)',
        [start, end],
    )
    return cursor.fetchone()[0]


def _create_plain(cursor, name, start, end):
    cursor.execute(
        f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF {PARENT_TABLE} "
        f"FOR VALUES FROM (%s) TO (%s)",
        [start, end],
    )


def _detach_default(cursor):
    cursor.execute(f"ALTER TABLE {PARENT_TABLE} DETACH PARTITION {DEFAULT_PARTITION}")


def _reattach_default(cursor):
    cursor.execute(
        f"ALTER TABLE {PARENT_TABLE} ATTACH PARTITION {DEFAULT_PARTITION} DEFAULT"
    )


def _create_rescuing_default_rows(cursor, name, start, end):
    """
    The recovery path: rows for this month are already in the default.

    The four steps are separate named calls rather than one block of SQL so
    a test can fail the run partway through and assert the transaction put
    the default partition back -- the failure mode that matters here is not
    "this errored" but "this errored halfway".

    Identifiers are interpolated rather than parameterised because Postgres
    does not accept a parameter where a table name goes. Every one of them
    is built here from a date, never from input.
    """
    _detach_default(cursor)
    cursor.execute(
        f"CREATE TABLE {name} PARTITION OF {PARENT_TABLE} FOR VALUES FROM (%s) TO (%s)",
        [start, end],
    )
    cursor.execute(
        f'WITH moved AS ('
        f'    DELETE FROM {DEFAULT_PARTITION} '
        f'    WHERE "timestamp" >= %s AND "timestamp" < %s RETURNING *'
        f') INSERT INTO {PARENT_TABLE} SELECT * FROM moved',
        [start, end],
    )
    rescued = cursor.rowcount
    _reattach_default(cursor)
    return rescued


def ensure_partitions(months_ahead=3, today=None):
    """
    Creates any missing monthly partition from this month to `months_ahead`.

    Idempotent: a month that already has its partition is skipped, so this
    is safe to run as often as you like. Returns (created, rescued_rows).
    """
    today = today or date.today()
    created, rescued = [], 0

    with transaction.atomic(), connection.cursor() as cursor:
        for start in _month_starts(today, months_ahead + 1):
            name = _partition_name(start)
            if _exists(cursor, name):
                continue
            end = _next_month(start)

            if _default_holds_rows_in(cursor, start, end):
                moved = _create_rescuing_default_rows(cursor, name, start, end)
                rescued += moved
                logger.warning(
                    "audit partitions: created %s and rescued %d row(s) that had "
                    "already fallen into %s",
                    name, moved, DEFAULT_PARTITION,
                )
            else:
                _create_plain(cursor, name, start, end)
                logger.info("audit partitions: created %s", name)
            created.append(name)

    return created, rescued
