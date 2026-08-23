"""
RLS session context for code that runs outside an HTTP request.

Every RLS policy in this project (apps/samples/migrations/0002, 0003,
apps/reporting/migrations/0003, and the billing/training policies added
alongside this module) is written against two Postgres session variables,
`rls.is_staff` and `rls.customer_id`. On a request,
apps.accounts.middleware.RLSContextMiddleware sets them before any view
code runs. Nothing set them anywhere else.

That was not a cosmetic gap. An unset custom GUC makes
`current_setting('rls.is_staff', true)` return NULL, so the staff-bypass
policy evaluates to NULL rather than true, and `customer_id =
current_setting('rls.customer_id', true)::bigint` is NULL as well. Both
fail closed, which is the right default and the wrong outcome here: a
Celery worker holds a connection nothing ever configures, so every
RLS-protected table looks empty to it. `generate_report_pdf` fetches its
Report by primary key and raised `Report.DoesNotExist` for rows that
plainly existed -- meaning no Certificate of Analysis could be produced by
a worker at all.

Setting the variable to the empty string is worse than leaving it unset:
`''::bigint` raises `invalid input syntax for type bigint` and takes down
the whole query rather than returning nothing. Hence '0' below, the same
sentinel the middleware uses -- a value that parses and can never match a
real id.

Background work runs with staff-equivalent visibility. A retention sweep or
a capacity check acts on behalf of the lab across every customer, which is
what the staff-bypass policy already describes; introducing a third
`rls.is_system` flag would mean rewriting every existing policy to check it
for no gain in what is actually reachable. The distinction that matters --
who is accountable for a change -- is recorded by django-simple-history's
`get_history_user`, not by this flag.
"""

from contextlib import contextmanager

from django.db import connection

# '0' rather than '' for customer_id: see the module docstring. An unset or
# empty value is not a safe "no customer" -- one denies silently, the other
# raises mid-query.
_SYSTEM_CONTEXT = ("true", "0")
_ANONYMOUS_CONTEXT = ("false", "0")


def _set_context(is_staff, customer_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('rls.is_staff', %s, false), "
            "set_config('rls.customer_id', %s, false)",
            [is_staff, customer_id],
        )


def apply_system_rls_context():
    """Give the current connection staff-equivalent visibility."""
    _set_context(*_SYSTEM_CONTEXT)


@contextmanager
def system_rls_context():
    """
    Run a block with staff-equivalent visibility, then deny again.

    For management commands and shell work. Tasks do not need it: the
    task_prerun handler below covers every task automatically, so a new
    task cannot forget to opt in -- the same reason the request side is a
    middleware rather than a decorator each view applies.

    Restores the default-deny context rather than whatever was set before,
    because there is no earlier context to restore to off-request: the
    connection either had this applied or had nothing at all.
    """
    apply_system_rls_context()
    try:
        yield
    finally:
        _set_context(*_ANONYMOUS_CONTEXT)
