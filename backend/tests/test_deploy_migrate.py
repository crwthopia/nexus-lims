"""
Migrations applied under an advisory lock.

Django's `migrate` is not concurrency-safe, and a platform that starts N
identical containers races all N of them through it. Two processes applying
the same migration collide on the `django_migrations` insert and on the DDL
itself -- and this schema's migrations create partitions and RLS policies,
where a partial double-apply is a bad thing to be debugging against a
regulated database during a deploy.

The lock is session-level rather than transaction-level for two reasons:
it has to span the whole `migrate` call, and Postgres drops it
automatically when the connection dies, so a container killed mid-migration
does not wedge every later deploy behind a lock nobody holds.
"""

import threading
import time

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections

from apps.common.management.commands.deploy_migrate import ADVISORY_LOCK_KEY

# Deliberately NOT transaction=True.
#
# An advisory lock belongs to a *connection*, not to a transaction, so a
# second thread on its own connection contends for it perfectly well inside
# pytest-django's default wrap-and-roll-back mode. Turning on transactional
# mode buys nothing here and costs a great deal: it truncates every table
# afterwards without restoring rows created by data migrations, so
# apps/accounts/migrations/0003_seed_roles.py's Role rows vanish and thirty
# unrelated tests later fail with Role.DoesNotExist -- a failure that looks
# like a bug in whatever ran next and is really a bug in this file.
pytestmark = pytest.mark.django_db


def _lock_is_held():
    """Whether anyone holds the migration lock, asked from a fresh connection."""
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND "
            "((classid::bigint << 32) | objid::bigint) = %s",
            [ADVISORY_LOCK_KEY],
        )
        return cursor.fetchone()[0] > 0


def test_it_applies_migrations_and_releases_the_lock():
    call_command("deploy_migrate")

    # The release matters as much as the acquire: this process goes on to
    # exec gunicorn, and a lock held for the life of a web worker would
    # block every future deploy.
    assert not _lock_is_held()


def test_the_lock_is_released_even_when_migrate_fails(monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("migration blew up")

    monkeypatch.setattr(
        "apps.common.management.commands.deploy_migrate.call_command", explode
    )

    with pytest.raises(RuntimeError, match="migration blew up"):
        call_command("deploy_migrate")

    # Without the finally, one failed migration would leave the lock held
    # and every subsequent deploy would hang until the timeout.
    assert not _lock_is_held()


def test_a_second_instance_waits_rather_than_migrating_concurrently():
    """The whole point: two instances starting at once must serialise."""
    started = threading.Event()
    release = threading.Event()

    def hold_the_lock():
        holder = connections.create_connection("default")
        try:
            with holder.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(%s)", [ADVISORY_LOCK_KEY])
                started.set()
                release.wait(timeout=30)
                cursor.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])
        finally:
            holder.close()

    holder_thread = threading.Thread(target=hold_the_lock)
    holder_thread.start()
    try:
        assert started.wait(timeout=10), "the holder never took the lock"

        # Now race it. This must block rather than migrate alongside.
        def run_migrate():
            call_command("deploy_migrate", lock_timeout=30)

        migrator = threading.Thread(target=run_migrate)
        migrator.start()

        # Still blocked while the other instance holds the lock.
        time.sleep(2)
        assert migrator.is_alive(), "the second instance did not wait for the lock"

        release.set()
        migrator.join(timeout=30)
        assert not migrator.is_alive(), "the second instance never acquired the lock"
    finally:
        release.set()
        holder_thread.join(timeout=10)

    assert not _lock_is_held()


def test_it_refuses_to_start_rather_than_giving_up_and_booting():
    """
    A timeout is an error, not a shrug.

    Booting anyway would serve traffic against a schema this release was
    not built for, which is worse than failing to start: the deployment
    looks successful and the errors appear later, somewhere else.
    """
    started = threading.Event()
    release = threading.Event()

    def hold_the_lock():
        holder = connections.create_connection("default")
        try:
            with holder.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(%s)", [ADVISORY_LOCK_KEY])
                started.set()
                release.wait(timeout=30)
                cursor.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])
        finally:
            holder.close()

    holder_thread = threading.Thread(target=hold_the_lock)
    holder_thread.start()
    try:
        assert started.wait(timeout=10)

        with pytest.raises(CommandError, match="Timed out"):
            call_command("deploy_migrate", lock_timeout=3)
    finally:
        release.set()
        holder_thread.join(timeout=10)


def test_the_lock_key_is_not_a_value_something_else_would_pick():
    # Advisory keys share one namespace per database. A readable constant
    # like 1 or 42 is exactly what an unrelated library would also choose.
    assert ADVISORY_LOCK_KEY > 1_000_000_000
    assert connection.vendor == "postgresql"
