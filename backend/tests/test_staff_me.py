"""GET /auth/staff/me (apps/accounts/views.py StaffMeView) -- the staff-side counterpart to /auth/customer/me."""

import pytest

from tests.factories import CustomerUserFactory, StaffUserFactory

pytestmark = pytest.mark.django_db


def test_returns_the_logged_in_staff_user_with_roles(login_as_staff):
    staff = StaffUserFactory(roles=["analyst", "reviewer"])
    client = login_as_staff(staff)

    response = client.get("/api/v1/auth/staff/me")

    assert response.status_code == 200
    assert response.data["email"] == staff.email
    assert {r["name"] for r in response.data["roles"]} == {"analyst", "reviewer"}


def test_requires_authentication(api_client):
    response = api_client.get("/api/v1/auth/staff/me")

    assert response.status_code in (401, 403)


def test_a_customer_session_cannot_use_it(login_as_customer):
    client = login_as_customer(CustomerUserFactory())

    response = client.get("/api/v1/auth/staff/me")

    assert response.status_code == 403


def test_logout_clears_the_session(login_as_staff):
    staff = StaffUserFactory()
    client = login_as_staff(staff)
    assert client.get("/api/v1/auth/staff/me").status_code == 200

    response = client.post("/api/v1/auth/staff/logout")

    assert response.status_code == 204
    assert client.get("/api/v1/auth/staff/me").status_code in (401, 403)


def test_login_complete_redirects_to_the_staff_console(settings, api_client):
    settings.STAFF_CONSOLE_BASE_URL = "http://localhost:5174"

    response = api_client.get("/staff/login-complete/")

    assert response.status_code == 302
    assert response["Location"] == "http://localhost:5174"
