"""
Shared pytest fixtures for the NexusLIMS test suite.

Staff auth uses client.force_login(..., backend=...) rather than DRF's
force_authenticate(): force_authenticate only patches the DRF-wrapped
Request seen inside the view, but apps.accounts.middleware.RLSContextMiddleware
reads the plain Django request.user *before* DRF ever wraps it -- so a test
using force_authenticate would silently defeat RLS staff-bypass checks.
force_login drives a real session through AuthenticationMiddleware, exactly
like a real Entra ID-authenticated request would, keeping tests honest about
what the middleware actually sees.

Customer auth has no such shortcut available (or needed): CustomerUser isn't
AUTH_USER_MODEL, so tests log in for real via POST /auth/customer/login,
same as a real customer-portal client would.
"""

import pytest
from django.db import connection
from rest_framework.test import APIClient

from tests.factories import CUSTOMER_RAW_PASSWORD

STAFF_LOGIN_BACKEND = "django.contrib.auth.backends.ModelBackend"


@pytest.fixture(autouse=True)
def _no_ssl_redirect(settings):
    """
    Turn off SECURE_SSL_REDIRECT for the duration of every test.

    The production hardening in config/settings.py is gated on DEBUG being
    off, and it is off during tests -- so without this, SecurityMiddleware
    answers every request from the Django test client with a 301 to
    https://testserver, and the entire suite fails at the first assertion
    about a status code.

    Everything else in that block stays on, deliberately: secure cookies
    and the security headers cost nothing here and are worth exercising.
    Only the redirect is incompatible with a test client that speaks plain
    HTTP by definition.

    The probes are exempt from the redirect in production anyway (see
    SECURE_REDIRECT_EXEMPT), which is what makes a load balancer able to
    reach them at all.
    """
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture(autouse=True)
def _rls_staff_bypass_for_fixture_setup(db):
    """
    order/sample carry FORCE ROW LEVEL SECURITY (apps/samples/migrations
    0002/0003_*), which applies to every INSERT/UPDATE/SELECT the app's own
    connection role makes -- including factory_boy fixture setup, which
    writes directly via the ORM outside of any HTTP request. In production
    every real request goes through RLSContextMiddleware first, which sets
    these same session variables; nothing here runs in that context, so
    without this, ordinary OrderFactory/SampleFactory calls in test setup
    are rejected by Postgres with "new row violates row-level security
    policy" before the test under test even starts.

    Defaults every test's connection to the staff-bypass policy so fixture
    setup isn't blocked. tests/test_row_level_security.py exercises the
    actual customer-scoping policy directly and resets these variables
    itself; any real API request in any other test immediately overwrites
    both variables via the middleware regardless of this default.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('rls.is_staff', 'true', false), set_config('rls.customer_id', '0', false)"
        )


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def login_as_staff(api_client):
    """Returns a function that logs the given StaffUser into api_client and returns it."""

    def _login(staff_user):
        api_client.force_login(staff_user, backend=STAFF_LOGIN_BACKEND)
        return api_client

    return _login


@pytest.fixture
def login_as_customer(api_client):
    """
    Returns a function that performs the real POST /auth/customer/login flow
    for the given CustomerUser (password defaults to CUSTOMER_RAW_PASSWORD,
    which every CustomerUserFactory-created account shares) and returns the
    now-authenticated api_client. Raises via assert if login doesn't 200, so
    a broken auth flow fails loudly at the fixture call site, not deep in an
    unrelated test's assertions.
    """

    def _login(customer, password=CUSTOMER_RAW_PASSWORD, mfa_code=None):
        payload = {"email": customer.email, "password": password}
        if mfa_code:
            payload["mfa_code"] = mfa_code
        response = api_client.post("/api/v1/auth/customer/login", payload, format="json")
        assert response.status_code == 200, response.data
        return api_client

    return _login
