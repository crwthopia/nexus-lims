"""
Cross-tenant isolation across every customer-facing endpoint.

There are six routes a logged-in customer can reach -- my/orders,
my/samples, my/reports, my/invoices, my/enrollments, my/credit-notes --
and each one is scoped by a `.filter()` in its viewset. This file asserts
the boundary from the outside for all six, list and detail, so the sweep is
uniform rather than three routes covered in three different files and three
covered nowhere. It is the standing version of a one-off probe.

Two conventions worth stating, because both are load-bearing:

  * another customer's id must be a 404, never a 403. A 403 confirms the
    row exists, which is itself the disclosure the scoping exists to
    prevent; a scoped queryset makes a real id indistinguishable from one
    that was never issued.
  * each test is paired with a database policy (apps/training/migrations/
    0002, apps/billing/migrations/0002, and the order/sample/report
    policies that predate them). The tests here go through the API, so they
    pass whether the boundary is held by the ORM filter or by Postgres.
    tests/test_row_level_security.py is the counterpart that removes the
    ORM from the picture entirely.
"""

import pytest

from apps.reporting.models import Report
from apps.training.models import Enrollment
from apps.samples.models import Sample
from tests.factories import (
    CreditNoteFactory, CustomerUserFactory, EnrollmentFactory, InvoiceFactory,
    OrderFactory, SampleFactory, StaffUserFactory, TrainingSessionFactory,
)

pytestmark = pytest.mark.django_db


def owned_by(customer):
    """One row on every customer-reachable route, all owned by `customer`."""
    order = OrderFactory(customer=customer)
    sample = SampleFactory(order=order)
    Sample.objects.filter(pk=sample.pk).update(status=Sample.Status.APPROVED)
    report = Report.objects.create(
        sample=sample,
        order=order,
        report_type=Report.ReportType.WATER_ENVIRONMENTAL_COA,
        generated_by=StaffUserFactory(),
        version=1,
    )
    Report.objects.filter(pk=report.pk).update(
        status=Report.Status.READY,
        file_id=f"reports/water_environmental_coa/{report.pk}-v1.pdf",
    )
    enrollment = EnrollmentFactory(customer=customer)
    return {
        "my/orders": order.pk,
        "my/samples": sample.pk,
        "my/reports": report.pk,
        # Order-backed. The enrollment-backed case is separate below: the two
        # take different branches of the invoice policy and behaved
        # differently under an unscoped queryset, so one does not cover the
        # other.
        "my/invoices": InvoiceFactory(order=order).pk,
        "my/enrollments": enrollment.pk,
        "my/credit-notes": CreditNoteFactory(
            customer=customer, source_enrollment=enrollment
        ).pk,
    }


ROUTES = [
    "my/orders", "my/samples", "my/reports",
    "my/invoices", "my/enrollments", "my/credit-notes",
]


@pytest.fixture
def two_customers(login_as_customer):
    """Alice logged in, with Bob's rows sitting alongside hers."""
    alice, bob = CustomerUserFactory(), CustomerUserFactory()
    mine, theirs = owned_by(alice), owned_by(bob)
    return login_as_customer(alice), mine, theirs


@pytest.mark.parametrize("route", ROUTES)
def test_list_returns_only_the_callers_own_rows(route, two_customers):
    client, mine, theirs = two_customers

    response = client.get(f"/api/v1/{route}/")

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()["results"]]
    assert ids == [mine[route]], f"{route} returned {ids}, expected {[mine[route]]}"


@pytest.mark.parametrize("route", ROUTES)
def test_another_customers_row_is_a_404(route, two_customers):
    client, _mine, theirs = two_customers

    response = client.get(f"/api/v1/{route}/{theirs[route]}/")

    assert response.status_code == 404, (
        f"{route} exposed another customer's row {theirs[route]} "
        f"as HTTP {response.status_code}"
    )


@pytest.mark.parametrize("route", ROUTES)
def test_a_customer_can_still_read_their_own_row(route, two_customers):
    """
    The other half of every isolation assertion. Scoping that returns
    nothing to anybody would satisfy the two tests above and be useless.
    """
    client, mine, _theirs = two_customers

    assert client.get(f"/api/v1/{route}/{mine[route]}/").status_code == 200


# --- The invoice split -----------------------------------------------------
#
# An Invoice reaches its customer through *either* an order or an
# enrollment. With the customer filter removed, the order-backed branch
# 500'd (protected only incidentally, by `order`'s policy hiding the parent
# the serializer needed) while the enrollment-backed branch returned another
# customer's financial record. Both branches now have a policy; both are
# asserted.

def test_an_enrollment_backed_invoice_is_scoped_to_its_customer(login_as_customer):
    alice, bob = CustomerUserFactory(), CustomerUserFactory()
    mine = InvoiceFactory(order=None, enrollment=EnrollmentFactory(customer=alice))
    theirs = InvoiceFactory(order=None, enrollment=EnrollmentFactory(customer=bob))
    client = login_as_customer(alice)

    listed = client.get("/api/v1/my/invoices/")
    assert [row["id"] for row in listed.json()["results"]] == [mine.pk]

    assert client.get(f"/api/v1/my/invoices/{theirs.pk}/").status_code == 404
    assert client.get(f"/api/v1/my/invoices/{mine.pk}/").status_code == 200


def test_both_invoice_branches_are_visible_to_the_same_customer(login_as_customer):
    """A customer with one of each sees both, not whichever branch was written last."""
    alice = CustomerUserFactory()
    from_order = InvoiceFactory(order=OrderFactory(customer=alice))
    from_enrollment = InvoiceFactory(
        order=None, enrollment=EnrollmentFactory(customer=alice)
    )
    client = login_as_customer(alice)

    response = client.get("/api/v1/my/invoices/")

    assert set(row["id"] for row in response.json()["results"]) == {
        from_order.pk, from_enrollment.pk,
    }


# --- The write side --------------------------------------------------------
#
# The policies on these tables are FOR ALL with no separate WITH CHECK, so
# the USING clause governs INSERTs as well as SELECTs. That is a real gain
# -- a customer-context connection cannot write a row belonging to someone
# else even if application code asked it to -- but it can only be claimed
# if the legitimate write still works, so both halves are asserted.

def test_a_customer_can_still_enrol_themselves(login_as_customer):
    """
    The positive control for the write path. If the enrollment policy were
    too strict, self-enrollment would fail with an RLS violation rather
    than a clean error, and the portal's only customer-initiated write
    would be broken.
    """
    alice = CustomerUserFactory()
    session = TrainingSessionFactory()
    client = login_as_customer(alice)

    response = client.post(
        "/api/v1/my/enrollments/", {"session": session.pk}, format="json"
    )

    assert response.status_code == 201, response.data
    assert Enrollment.objects.get(pk=response.json()["id"]).customer_id == alice.pk


def test_enrolling_cannot_be_redirected_to_another_customer(login_as_customer):
    """
    `customer` is read-only on the serializer and set from the session, so
    supplying someone else's id must be ignored rather than honoured.
    """
    alice, bob = CustomerUserFactory(), CustomerUserFactory()
    session = TrainingSessionFactory()
    client = login_as_customer(alice)

    response = client.post(
        "/api/v1/my/enrollments/",
        {"session": session.pk, "customer": bob.pk},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert Enrollment.objects.get(pk=response.json()["id"]).customer_id == alice.pk
