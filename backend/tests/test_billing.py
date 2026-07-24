"""Invoice/Payment (Blueprint Section 3.7): a CONFIRMED payment auto-transitions its Invoice to paid."""

import pytest

from apps.billing.models import Invoice, Payment
from tests.factories import EnrollmentFactory, InvoiceFactory, StaffUserFactory

pytestmark = pytest.mark.django_db


def _post_payment(client, invoice, status):
    return client.post(
        f"/api/v1/invoices/{invoice.id}/payments/",
        {"method": "bank_transfer", "status": status},
        format="json",
    )


def test_confirmed_payment_marks_invoice_paid(login_as_staff):
    invoice = InvoiceFactory(status=Invoice.Status.UNPAID)
    billing_staff = StaffUserFactory(roles=["training_coordinator"])
    client = login_as_staff(billing_staff)

    response = _post_payment(client, invoice, Payment.Status.CONFIRMED)

    assert response.status_code == 201
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID


def test_pending_payment_does_not_mark_invoice_paid(login_as_staff):
    invoice = InvoiceFactory(status=Invoice.Status.UNPAID)
    billing_staff = StaffUserFactory(roles=["lab_supervisor"])
    client = login_as_staff(billing_staff)

    response = _post_payment(client, invoice, Payment.Status.PENDING_CONFIRMATION)

    assert response.status_code == 201
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.UNPAID


def test_recording_a_payment_requires_billing_role(login_as_staff):
    invoice = InvoiceFactory()
    analyst = StaffUserFactory(roles=["analyst"])
    client = login_as_staff(analyst)

    response = _post_payment(client, invoice, Payment.Status.CONFIRMED)

    assert response.status_code == 403


def test_status_filter_supports_comma_separated_values(login_as_staff):
    unpaid = InvoiceFactory(status=Invoice.Status.UNPAID)
    paid = InvoiceFactory(status=Invoice.Status.PAID)
    client = login_as_staff(StaffUserFactory())

    response = client.get("/api/v1/invoices/?status=unpaid")

    assert response.status_code == 200
    ids = {i["id"] for i in response.data["results"]}
    assert unpaid.id in ids
    assert paid.id not in ids


def test_customer_email_resolves_from_order(login_as_staff):
    invoice = InvoiceFactory()  # order-based by default
    client = login_as_staff(StaffUserFactory())

    response = client.get(f"/api/v1/invoices/{invoice.id}/")

    assert response.status_code == 200
    assert response.data["customer_email"] == invoice.order.customer.email


def test_customer_email_resolves_from_enrollment(login_as_staff):
    enrollment = EnrollmentFactory()
    invoice = InvoiceFactory(order=None, enrollment=enrollment)
    client = login_as_staff(StaffUserFactory())

    response = client.get(f"/api/v1/invoices/{invoice.id}/")

    assert response.status_code == 200
    assert response.data["customer_email"] == enrollment.customer.email
