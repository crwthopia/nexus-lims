"""
RLS session-variable middleware (Blueprint Section 2.1 item 3b). The RLS
policies on order/sample (apps/samples/migrations/0002_row_level_security.py,
0003_force_row_level_security.py) are only meaningful if the Postgres
session variables they check via current_setting(...) are set on every
request before any view code queries the database -- Django's ORM does not
do this on its own.

Values are set with set_config(name, value, is_local=false), i.e. scoped to
the current database connection/session rather than the current SQL
transaction. This is deliberate: Django opens a fresh connection per
request by default (DATABASES.CONN_MAX_AGE=0, config/settings.py), so a
connection-scoped setting is already effectively request-scoped; and if
CONN_MAX_AGE is later raised to reuse connections across requests, this
middleware still overwrites both values at the very start of every request,
before any other code on the request touches order/sample, so a later
request can never observe values a prior request left behind. Using
is_local=true instead would silently break this: outside an explicit
surrounding transaction (Django's default is autocommit per statement),
a transaction-local set_config resets before the next statement even runs.

- Staff-authenticated requests (any authenticated StaffUser -- currently the
  only Django-authenticatable user class; Entra ID/django-auth-adfs will
  populate request.user the same way once wired) set rls.is_staff = 'true',
  matched by the staff_full_access_* policies. This reads request.user,
  which Django's AuthenticationMiddleware (earlier in MIDDLEWARE) populates
  from the `_auth_user_id` session key -- entirely separate from the
  customer_user_id key below.
- Customer-authenticated requests set rls.customer_id to the CustomerUser's
  id, read directly from request.session["customer_user_id"] (set by
  CustomerLoginView, apps/accounts/customer_views.py). This is read straight
  off the session rather than off request.user because customer identity is
  only resolved to request.user later, inside DRF's per-view authentication
  (CustomerSessionAuthentication) -- which runs after this middleware, not
  before it -- so request.session is the one signal both stages agree on.
  Falls back to '0' (a sentinel that can never match a real bigint id)
  rather than an empty string, since current_setting(...)::bigint would
  raise on '' and take down every order/sample query for the request,
  staff included.
- Unauthenticated requests get both cleared to their default-deny values;
  DRF's permission layer should already have rejected the request before
  this matters, but the DB-level default is deny, not "whatever was set
  by whichever request last used this connection."
"""

from django.db import connection


class RLSContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_staff_authenticated = bool(
            getattr(request, "user", None) and request.user.is_authenticated
        )
        customer_id = request.session.get("customer_user_id") or 0

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('rls.is_staff', %s, false), set_config('rls.customer_id', %s, false)",
                ["true" if is_staff_authenticated else "false", str(customer_id)],
            )

        return self.get_response(request)
