"""
Run migrations safely when several instances start at once.

Django's `migrate` is not safe to run concurrently. Two processes applying
the same migration race on the `django_migrations` bookkeeping insert and,
worse, on the DDL itself -- and this schema's migrations include partition
creation and RLS policy statements, where a partial double-apply is not
something you want to debug against a regulated database at deploy time.

A deployment normally solves this with a one-shot release task, and if the
platform offers one, use it: `deploy_migrate` is safe there too. This
command exists because the common case is a platform that only knows how to
start N identical containers, and in that shape every container races.

A Postgres session-level advisory lock serialises them. The first instance
to acquire it migrates; the rest wait, acquire it afterwards, find nothing
to apply, and exit. Session-level rather than transaction-level so it spans
the whole `migrate` call, and because Postgres releases it automatically if
the connection dies -- a container killed mid-migration therefore does not
wedge every future deploy behind a lock nobody holds.
"""

import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# Arbitrary but fixed. Advisory lock keys share one namespace per database,
# so this needs to be a value nothing else picks by accident rather than
# something readable like 1.
ADVISORY_LOCK_KEY = 8_147_205_361_004_772


class Command(BaseCommand):
    help = "Apply migrations under an advisory lock, safe to run from every instance at once."

    def add_arguments(self, parser):
        parser.add_argument(
            "--lock-timeout",
            type=int,
            default=300,
            help=(
                "Seconds to wait for another instance to finish migrating before giving up "
                "(default: 300). Exceeding it is an error, not a silent start: a container "
                "that gives up waiting and boots anyway would serve traffic against a schema "
                "it was not built for."
            ),
        )

    def handle(self, *args, **options):
        timeout = options["lock_timeout"]
        deadline = time.monotonic() + timeout
        waited = False

        with connection.cursor() as cursor:
            while True:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [ADVISORY_LOCK_KEY])
                if cursor.fetchone()[0]:
                    break
                if time.monotonic() >= deadline:
                    raise CommandError(
                        f"Timed out after {timeout}s waiting for another instance to finish "
                        f"migrating. Refusing to start against a schema this release may not "
                        f"match. Check whether a migration is stuck or a previous deploy died "
                        f"holding the lock."
                    )
                if not waited:
                    self.stdout.write("Another instance is migrating; waiting for the lock.")
                    waited = True
                time.sleep(2)

            self.stdout.write("Migration lock acquired.")
            try:
                call_command("migrate", "--noinput")
            finally:
                # Explicit rather than relying on the connection closing:
                # the process goes on to exec gunicorn on the same
                # connection pool, and a lock held for the life of a web
                # worker would block every later deploy.
                cursor.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])
                self.stdout.write("Migration lock released.")
