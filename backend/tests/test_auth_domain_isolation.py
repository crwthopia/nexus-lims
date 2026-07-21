"""
Two segregated identity domains, no shared table, no FK between them
(Blueprint Section 2.1 item 7). A CustomerUser session must never satisfy a
staff-only endpoint and vice versa; a customer-authenticated write must not
crash django-simple-history (apps/accounts/history.py get_history_user, a
real bug that was found and fixed getting this project's customer auth
working -- HistoricalRecords.history_user is hard-typed to StaffUser).
"""

import pytest

from tests.factories import CustomerUserFactory, StaffUserFactory, TrainingSessionFactory

pytestmark = pytest.mark.django_db


def test_customer_session_cannot_reach_staff_only_endpoint(login_as_customer):
    customer = CustomerUserFactory()
    client = login_as_customer(customer)

    response = client.get("/api/v1/samples/")

    assert response.status_code == 403


def test_staff_session_cannot_reach_customer_only_endpoint(login_as_staff):
    staff = StaffUserFactory()
    client = login_as_staff(staff)

    response = client.get("/api/v1/auth/customer/me")

    assert response.status_code == 403


def test_customer_authenticated_write_does_not_crash_history_tracking(login_as_customer):
    """
    Enrollment carries HistoricalRecords(get_user=get_history_user).
    Before that fix, any write made during a customer session raised
    ValueError from django-simple-history's default get_user handing
    request.user (a CustomerUser) straight to a StaffUser-typed FK.
    """
    customer = CustomerUserFactory()
    session = TrainingSessionFactory()
    client = login_as_customer(customer)

    response = client.post("/api/v1/my/enrollments/", {"session": session.id}, format="json")

    assert response.status_code == 201
    assert response.data["customer"] == customer.id
