"""
Order lines and invoice lines: the path from the rate card to what a
customer owes.

One idea runs through every test here. **A price is copied, never joined.**
An order line snapshots the rate in force when it is created; an invoice
line snapshots the order line when the invoice is raised. Repricing the
catalogue afterwards, renaming an offering, or editing the order must
leave both alone -- an invoice is a document that was sent to someone, and
it has to keep saying what it said.

The other thing worth a test rather than a comment is that an order line is
billed **once**. A double-clicked button that charges a customer twice is
the kind of bug nobody finds until they complain.
"""

import datetime
from decimal import Decimal

import pytest
from django.db.utils import IntegrityError

from apps.billing import services as billing
from apps.billing.models import Invoice, InvoiceLine
from apps.catalogue.models import OfferingPrice
from apps.catalogue.services import set_price
from apps.samples import order_services
from apps.samples.models import OrderItem
from tests.factories import (
    OrderFactory,
    OrderItemFactory,
    ServiceOfferingFactory,
    StaffUserFactory,
)

pytestmark = pytest.mark.django_db

EXCLUSIVE = OfferingPrice.VatTreatment.EXCLUSIVE
INCLUSIVE = OfferingPrice.VatTreatment.INCLUSIVE


def offering_at(amount, treatment=EXCLUSIVE, *, effective_from=datetime.date(2026, 1, 1), **kwargs):
    offering = ServiceOfferingFactory(**kwargs)
    set_price(
        offering, amount=Decimal(amount), vat_treatment=treatment,
        vat_rate_pct=Decimal("12.00"), effective_from=effective_from,
    )
    return offering


# --- the snapshot ----------------------------------------------------------


def test_adding_a_line_copies_the_rate_in_force():
    offering = offering_at("1200.00", code="WQ-BOD5")
    order = OrderFactory()

    item = order_services.add_item(order, offering, quantity=2)

    assert item.unit_amount == Decimal("1200.00")
    assert item.vat_treatment == EXCLUSIVE
    assert item.source_price == offering.prices.get()
    assert item.net_amount == Decimal("2400.00")
    assert item.gross_amount == Decimal("2688.00")


def test_repricing_the_catalogue_leaves_a_sold_line_alone():
    """The reason the snapshot exists at all."""
    offering = offering_at("1000.00")
    item = order_services.add_item(OrderFactory(), offering)

    set_price(
        offering, amount=Decimal("5000.00"), vat_treatment=EXCLUSIVE,
        vat_rate_pct=Decimal("12.00"), effective_from=datetime.date.today(),
    )

    item.refresh_from_db()
    assert item.unit_amount == Decimal("1000.00")
    assert item.net_amount == Decimal("1000.00")


def test_an_unpriced_offering_is_refused_rather_than_sold_for_nothing():
    offering = ServiceOfferingFactory(code="WQ-NEW")  # never priced

    with pytest.raises(order_services.Unpriced, match="WQ-NEW"):
        order_services.add_item(OrderFactory(), offering)

    assert OrderItem.objects.count() == 0


def test_a_discount_is_applied_before_the_vat_split():
    """A discounted VAT-inclusive rate still has to reconcile."""
    offering = offering_at("1120.00", INCLUSIVE)

    item = order_services.add_item(OrderFactory(), offering, discount_pct=Decimal("10.00"))

    assert item.line_amount == Decimal("1008.00")
    assert item.net_amount == Decimal("900.00")
    assert item.vat_amount == Decimal("108.00")
    assert item.gross_amount == Decimal("1008.00")


def test_net_plus_vat_equals_gross_on_every_line():
    for amount, treatment, quantity in [
        ("1234.56", EXCLUSIVE, 3), ("1234.56", INCLUSIVE, 3),
        ("0.05", EXCLUSIVE, 7), ("99999.99", INCLUSIVE, 1),
    ]:
        item = OrderItemFactory(unit_amount=Decimal(amount), vat_treatment=treatment, quantity=quantity)
        assert item.net_amount + item.vat_amount == item.gross_amount, f"{amount} {treatment} x{quantity}"


# --- raising an invoice ----------------------------------------------------


def test_invoicing_an_order_copies_its_lines_and_totals_them():
    order = OrderFactory()
    OrderItemFactory(order=order, unit_amount=Decimal("1000.00"), quantity=2)
    OrderItemFactory(order=order, unit_amount=Decimal("500.00"))

    invoice = billing.invoice_order(order)

    assert invoice.lines.count() == 2
    assert invoice.amount == Decimal("2800.00")  # (2,000 + 500) + 12%
    net, vat, gross = invoice.line_totals()
    assert (net, vat, gross) == (Decimal("2500.00"), Decimal("300.00"), Decimal("2800.00"))


def test_an_invoice_line_carries_its_own_description():
    """Renaming an offering must not rewrite an invoice that was sent."""
    offering = offering_at("1000.00", code="WQ-BOD5", name="BOD (5-day)")
    order = OrderFactory()
    order_services.add_item(order, offering)
    invoice = billing.invoice_order(order)

    offering.name = "Biochemical oxygen demand, five-day"
    offering.save()

    line = invoice.lines.get()
    assert line.description == "WQ-BOD5 — BOD (5-day)"


def test_editing_the_order_line_afterwards_does_not_change_the_invoice():
    order = OrderFactory()
    item = OrderItemFactory(order=order, unit_amount=Decimal("1000.00"))
    invoice = billing.invoice_order(order)

    item.quantity = 10
    item.save()

    line = invoice.lines.get()
    assert line.quantity == 1
    assert line.gross_amount == Decimal("1120.00")


def test_an_order_line_cannot_be_billed_twice():
    order = OrderFactory()
    OrderItemFactory(order=order)
    billing.invoice_order(order)

    with pytest.raises(ValueError, match="already been invoiced"):
        billing.invoice_order(order)

    assert Invoice.objects.count() == 1


def test_the_database_refuses_a_second_line_against_one_order_item():
    """The backstop under the check above -- a retried request, a race."""
    order = OrderFactory()
    item = OrderItemFactory(order=order)
    invoice = billing.invoice_order(order)

    with pytest.raises(IntegrityError):
        InvoiceLine.objects.create(
            invoice=invoice, order_item=item, description="again", quantity=1, unit_amount=Decimal("1.00"),
        )


def test_only_the_unbilled_lines_are_invoiced():
    """An order part-billed in March and finished in July gets a second invoice, not a duplicate."""
    order = OrderFactory()
    OrderItemFactory(order=order, unit_amount=Decimal("1000.00"))
    first = billing.invoice_order(order)

    later = OrderItemFactory(order=order, unit_amount=Decimal("300.00"))
    second = billing.invoice_order(order)

    assert first.lines.count() == 1
    assert [line.order_item_id for line in second.lines.all()] == [later.id]
    assert second.amount == Decimal("336.00")


def test_voiding_an_invoice_does_not_free_its_line_to_be_billed_again():
    """
    The documented limit (see billing.services.unbilled_items): the
    one-line-one-billing rule is a unique constraint, and a constraint
    cannot except void invoices without a copy of the invoice's status
    living on the line, which is drift in the money path.
    """
    order = OrderFactory()
    OrderItemFactory(order=order, unit_amount=Decimal("1000.00"))
    first = billing.invoice_order(order)
    first.status = Invoice.Status.VOID
    first.save()

    with pytest.raises(ValueError, match="already been invoiced"):
        billing.invoice_order(order)


def test_correcting_the_order_is_how_a_voided_invoice_is_re_raised():
    """The escape hatch, and the reason the limit above is liveable."""
    order = OrderFactory()
    OrderItemFactory(order=order, unit_amount=Decimal("1000.00"))
    first = billing.invoice_order(order)
    first.status = Invoice.Status.VOID
    first.save()

    OrderItemFactory(order=order, unit_amount=Decimal("1000.00"))  # the corrected line
    second = billing.invoice_order(order)

    assert second.amount == Decimal("1120.00")
    assert second.lines.count() == 1


def test_an_order_mixing_currencies_is_refused_rather_than_summed():
    order = OrderFactory()
    OrderItemFactory(order=order, currency="PHP")
    OrderItemFactory(order=order, currency="USD")

    with pytest.raises(ValueError, match="mixes currencies"):
        billing.invoice_order(order)


def test_a_manually_billed_invoice_still_works_and_reports_no_split():
    """Walk-in jobs and enrollments are still one typed figure."""
    from tests.factories import InvoiceFactory

    invoice = InvoiceFactory(amount=Decimal("2500.00"))

    assert invoice.lines.count() == 0
    assert invoice.line_totals() == (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))


# --- API -------------------------------------------------------------------


def test_adding_a_line_requires_an_intake_role(login_as_staff):
    order = OrderFactory()
    offering = offering_at("1000.00")
    client = login_as_staff(StaffUserFactory(roles=["analyst"]))

    response = client.post(f"/api/v1/orders/{order.id}/items/", {"offering": offering.id}, format="json")

    assert response.status_code == 403
    assert order.items.count() == 0


def test_a_sample_receiver_can_add_a_line_but_not_price_it(login_as_staff):
    order = OrderFactory()
    offering = offering_at("1200.00")
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = client.post(
        f"/api/v1/orders/{order.id}/items/",
        # unit_amount is deliberately sent and deliberately ignored: the
        # server prices the line, or nobody would need a rate card.
        {"offering": offering.id, "quantity": 2, "unit_amount": "1.00"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["unit_amount"] == "1200.00"
    assert response.data["gross_amount"] == "2688.00"


def test_selling_an_unpriced_offering_is_a_400_with_the_reason(login_as_staff):
    order = OrderFactory()
    offering = ServiceOfferingFactory(code="WQ-NEW")
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = client.post(f"/api/v1/orders/{order.id}/items/", {"offering": offering.id}, format="json")

    assert response.status_code == 400
    assert "no price in force" in str(response.data["offering"])


def test_raising_an_invoice_requires_a_billing_role(login_as_staff):
    order = OrderFactory()
    OrderItemFactory(order=order)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = client.post(f"/api/v1/orders/{order.id}/invoice/")

    assert response.status_code == 403


def test_raising_an_invoice_returns_it_with_its_lines(login_as_staff):
    order = OrderFactory()
    OrderItemFactory(order=order, unit_amount=Decimal("1000.00"))
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))

    response = client.post(f"/api/v1/orders/{order.id}/invoice/")

    assert response.status_code == 201
    assert response.data["amount"] == "1120.00"
    assert response.data["net_total"] == "1000.00"
    assert response.data["vat_total"] == "120.00"
    assert len(response.data["lines"]) == 1


def test_invoicing_an_order_with_nothing_left_to_bill_is_a_400(login_as_staff):
    order = OrderFactory()
    OrderItemFactory(order=order)
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))
    client.post(f"/api/v1/orders/{order.id}/invoice/")

    response = client.post(f"/api/v1/orders/{order.id}/invoice/")

    assert response.status_code == 400
    assert Invoice.objects.count() == 1


def test_an_invoice_with_no_lines_reports_no_split(login_as_staff):
    from tests.factories import InvoiceFactory

    invoice = InvoiceFactory(amount=Decimal("2500.00"))
    client = login_as_staff(StaffUserFactory())

    response = client.get(f"/api/v1/invoices/{invoice.id}/")

    assert response.data["amount"] == "2500.00"
    assert response.data["net_total"] is None
    assert response.data["vat_total"] is None


def test_invoice_lines_are_not_writable_over_the_api(login_as_staff):
    order = OrderFactory()
    OrderItemFactory(order=order)
    invoice = billing.invoice_order(order)
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))

    response = client.patch(
        f"/api/v1/invoices/{invoice.id}/", {"lines": [{"description": "rewritten"}]}, format="json",
    )

    assert response.status_code in (200, 400)
    assert invoice.lines.get().description != "rewritten"


# --- row-level security ----------------------------------------------------


def test_the_database_scopes_order_lines_and_invoice_lines_to_their_customer():
    """
    Straight at the database, bypassing every viewset: the policies added
    in samples/0005 and billing/0005 have to hold on their own, because the
    reason apps/training/migrations/0002 exists is that two tables were
    protected by nothing but a `.filter()` in a viewset.
    """
    from django.db import connection

    from tests.factories import CustomerUserFactory

    customer_a, customer_b = CustomerUserFactory(), CustomerUserFactory()
    order_a, order_b = OrderFactory(customer=customer_a), OrderFactory(customer=customer_b)
    item_a = OrderItemFactory(order=order_a)
    OrderItemFactory(order=order_b)
    invoice_a = billing.invoice_order(order_a)
    billing.invoice_order(order_b)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('rls.is_staff', 'false', false), set_config('rls.customer_id', %s, false)",
            [str(customer_a.id)],
        )
        cursor.execute("SELECT id FROM order_item")
        assert {row[0] for row in cursor.fetchall()} == {item_a.id}
        cursor.execute("SELECT invoice_id FROM invoice_line")
        assert {row[0] for row in cursor.fetchall()} == {invoice_a.id}

        # No context at all: default deny, as everywhere else.
        cursor.execute(
            "SELECT set_config('rls.is_staff', 'false', false), set_config('rls.customer_id', '0', false)"
        )
        cursor.execute("SELECT id FROM order_item")
        assert cursor.fetchall() == []
        cursor.execute("SELECT id FROM invoice_line")
        assert cursor.fetchall() == []

        # Staff see everything, which is what the console needs.
        cursor.execute(
            "SELECT set_config('rls.is_staff', 'true', false), set_config('rls.customer_id', '0', false)"
        )
        cursor.execute("SELECT id FROM order_item")
        assert len(cursor.fetchall()) == 2


def test_a_customer_sees_the_breakdown_of_their_own_invoice(login_as_customer):
    from tests.factories import CustomerUserFactory

    customer = CustomerUserFactory()
    order = OrderFactory(customer=customer)
    OrderItemFactory(order=order, unit_amount=Decimal("1000.00"))
    invoice = billing.invoice_order(order)

    client = login_as_customer(customer)
    response = client.get("/api/v1/my/invoices/")

    assert response.status_code == 200
    row = next(item for item in response.data["results"] if item["id"] == invoice.id)
    assert row["amount"] == "1120.00"
    assert row["net_total"] == "1000.00"
    assert row["vat_total"] == "120.00"
