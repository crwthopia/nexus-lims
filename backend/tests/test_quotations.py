"""
Quotations: the priced offer that goes out before any work starts.

Two invariants carry the whole feature, and everything else here is
scaffolding around them:

**A sent quotation is immutable.** It is a document a customer is reading.
Editing it afterwards would make "what did we quote them" unanswerable,
which is precisely the gap this feature exists to close.

**A quote honoured is a quote honoured.** Accepting copies the quoted
figures onto the order at the rate quoted, however the rate card has moved
since. Without that, a quotation is a non-binding guess and the customer
finds out at invoice time.
"""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from django_fsm import TransitionNotAllowed

from apps.catalogue.models import OfferingPrice
from apps.catalogue.services import set_price
from apps.notifications.models import NotificationRecord
from apps.quotations import services
from apps.quotations.models import Quotation
from apps.quotations.tasks import expire_quotations
from apps.samples.models import Order, OrderItem
from tests.factories import (
    CustomerUserFactory,
    OrderFactory,
    QuotationFactory,
    QuotationItemFactory,
    ServiceOfferingFactory,
    StaffUserFactory,
)

pytestmark = pytest.mark.django_db

EXCLUSIVE = OfferingPrice.VatTreatment.EXCLUSIVE


def offering_at(amount, treatment=EXCLUSIVE, *, effective_from=datetime.date(2026, 1, 1), **kwargs):
    offering = ServiceOfferingFactory(**kwargs)
    set_price(
        offering, amount=Decimal(amount), vat_treatment=treatment,
        vat_rate_pct=Decimal("12.00"), effective_from=effective_from,
    )
    return offering


def sent_quotation(**kwargs):
    quotation = QuotationFactory(**kwargs)
    QuotationItemFactory(quotation=quotation, unit_amount=Decimal("1000.00"))
    return services.send_quotation(quotation)


# --- references ------------------------------------------------------------


def test_a_quotation_gets_a_reference_a_customer_can_quote_back():
    quotation = QuotationFactory()

    assert quotation.reference.startswith(f"Q-{timezone.localdate().year}-")
    assert quotation.reference.endswith(f"{quotation.id:05d}")


def test_references_are_unique_across_quotations_made_together():
    references = {QuotationFactory().reference for _ in range(5)}

    assert len(references) == 5


# --- sending ---------------------------------------------------------------


def test_an_empty_quotation_cannot_be_sent():
    quotation = QuotationFactory()

    with pytest.raises(services.QuotationError, match="offers nothing"):
        services.send_quotation(quotation)

    quotation.refresh_from_db()
    assert quotation.status == Quotation.Status.DRAFT


def test_a_quotation_whose_date_has_passed_cannot_be_sent():
    """It would be expired the moment it landed."""
    quotation = QuotationFactory(valid_until=timezone.localdate() - datetime.timedelta(days=1))
    QuotationItemFactory(quotation=quotation)

    with pytest.raises(services.QuotationError, match="has passed"):
        services.send_quotation(quotation)


def test_sending_notifies_the_customer_without_carrying_the_figures():
    """
    One path for every email the lab sends, and the same rule as reports:
    the notice says a quotation is ready, the breakdown stays in the
    account where it cannot be altered in transit.
    """
    quotation = sent_quotation()

    record = NotificationRecord.objects.get(kind=NotificationRecord.Kind.QUOTATION_SENT)
    assert record.recipient == quotation.customer.email
    assert quotation.reference in record.subject

    from apps.notifications.messages import build_body

    body = build_body(record)
    assert "portal" in body.lower()
    assert quotation.reference in body


def test_a_sent_quotation_cannot_take_new_lines():
    quotation = sent_quotation()

    with pytest.raises(services.QuotationError, match="Issue a new quotation"):
        services.add_item(quotation, offering_at("500.00"))


def test_quoting_an_unpriced_offering_is_refused():
    quotation = QuotationFactory()
    offering = ServiceOfferingFactory(code="WQ-NEW")

    with pytest.raises(services.QuotationError, match="no price in force"):
        services.add_item(quotation, offering)


def test_a_quoted_line_snapshots_the_rate():
    quotation = QuotationFactory()
    offering = offering_at("1200.00", code="WQ-BOD5")

    item = services.add_item(quotation, offering, quantity=2)

    assert item.unit_amount == Decimal("1200.00")
    assert item.source_price == offering.prices.get()
    assert item.net_amount == Decimal("2400.00")
    assert item.gross_amount == Decimal("2688.00")


# --- acceptance ------------------------------------------------------------


def test_accepting_puts_the_quoted_lines_on_an_order():
    quotation = QuotationFactory()
    offering = offering_at("1200.00")
    services.add_item(quotation, offering, quantity=3)
    services.send_quotation(quotation)

    services.accept_quotation(quotation, customer=quotation.customer)

    quotation.refresh_from_db()
    assert quotation.status == Quotation.Status.ACCEPTED
    order = quotation.order
    assert order is not None
    assert order.customer_id == quotation.customer_id
    item = order.items.get()
    assert (item.quantity, item.unit_amount) == (3, Decimal("1200.00"))


def test_a_quote_honoured_is_a_quote_honoured():
    """
    The invariant the whole feature turns on: a rise after the offer went
    out does not reach the customer who accepted the offer.
    """
    quotation = QuotationFactory()
    offering = offering_at("1000.00")
    services.add_item(quotation, offering)
    services.send_quotation(quotation)

    set_price(
        offering, amount=Decimal("9000.00"), vat_treatment=EXCLUSIVE,
        vat_rate_pct=Decimal("12.00"), effective_from=timezone.localdate(),
    )
    services.accept_quotation(quotation, customer=quotation.customer)

    assert quotation.order.items.get().unit_amount == Decimal("1000.00")


def test_accepting_attaches_to_the_order_it_was_quoted_against():
    """A quotation raised for work already ordered adds to that order rather than opening a second."""
    order = OrderFactory()
    quotation = QuotationFactory(customer=order.customer, order=order)
    QuotationItemFactory(quotation=quotation)
    services.send_quotation(quotation)

    services.accept_quotation(quotation, customer=order.customer)

    assert Order.objects.count() == 1
    assert order.items.count() == 1


def test_an_expired_quotation_cannot_be_accepted():
    quotation = sent_quotation()
    Quotation.objects.filter(pk=quotation.pk).update(valid_until=timezone.localdate() - datetime.timedelta(days=1))
    quotation.refresh_from_db()

    with pytest.raises(services.QuotationError, match="expired"):
        services.accept_quotation(quotation, customer=quotation.customer)

    assert OrderItem.objects.count() == 0


def test_a_declined_quotation_cannot_then_be_accepted():
    quotation = sent_quotation()
    services.decline_quotation(quotation)

    with pytest.raises(TransitionNotAllowed):
        services.accept_quotation(quotation, customer=quotation.customer)


def test_a_draft_cannot_be_accepted_before_it_is_sent():
    quotation = QuotationFactory()
    QuotationItemFactory(quotation=quotation)

    with pytest.raises(TransitionNotAllowed):
        services.accept_quotation(quotation, customer=quotation.customer)


def test_who_answered_is_recorded():
    """A customer accepting and a coordinator recording a PO are both real, and told apart."""
    by_customer = sent_quotation()
    services.accept_quotation(by_customer, customer=by_customer.customer)

    by_staff = sent_quotation()
    staff = StaffUserFactory(roles=["lab_supervisor"])
    services.accept_quotation(by_staff, staff=staff)

    assert by_customer.accepted_by_customer_id == by_customer.customer_id
    assert by_customer.decided_by_staff_id is None
    assert by_staff.decided_by_staff_id == staff.id
    assert by_staff.accepted_by_customer_id is None


def test_declining_does_not_claim_a_customer_accepted_anything():
    quotation = sent_quotation()

    services.decline_quotation(quotation, staff=StaffUserFactory(roles=["lab_supervisor"]))

    assert quotation.status == Quotation.Status.DECLINED
    assert quotation.accepted_by_customer_id is None


# --- revising --------------------------------------------------------------


def test_revising_copies_the_lines_at_the_quoted_figures():
    """A revision that changes one line must not silently reprice the rest."""
    quotation = QuotationFactory()
    offering = offering_at("1000.00")
    services.add_item(quotation, offering, quantity=2)
    services.send_quotation(quotation)
    set_price(
        offering, amount=Decimal("4000.00"), vat_treatment=EXCLUSIVE,
        vat_rate_pct=Decimal("12.00"), effective_from=timezone.localdate(),
    )

    replacement = services.revise(quotation)

    assert replacement.status == Quotation.Status.DRAFT
    assert replacement.supersedes_id == quotation.id
    assert replacement.items.get().unit_amount == Decimal("1000.00")
    assert replacement.reference != quotation.reference


# --- expiry ----------------------------------------------------------------


def test_the_sweep_moves_lapsed_offers_out_of_sent():
    lapsed = sent_quotation()
    Quotation.objects.filter(pk=lapsed.pk).update(valid_until=timezone.localdate() - datetime.timedelta(days=1))
    live = sent_quotation()

    assert expire_quotations() == 1

    lapsed.refresh_from_db()
    live.refresh_from_db()
    assert lapsed.status == Quotation.Status.EXPIRED
    assert live.status == Quotation.Status.SENT


def test_expiry_is_true_from_the_date_not_from_the_sweep():
    """
    A quotation that lapsed at midnight is lapsed at 00:01, not at 03:30
    when the task runs -- which is why acceptance checks the date rather
    than the status.
    """
    quotation = sent_quotation()
    Quotation.objects.filter(pk=quotation.pk).update(valid_until=timezone.localdate() - datetime.timedelta(days=1))
    quotation.refresh_from_db()

    assert quotation.status == Quotation.Status.SENT
    assert quotation.is_expired is True


def test_the_sweep_leaves_answered_quotations_alone():
    accepted = sent_quotation()
    services.accept_quotation(accepted, customer=accepted.customer)
    Quotation.objects.filter(pk=accepted.pk).update(valid_until=timezone.localdate() - datetime.timedelta(days=1))

    expire_quotations()

    accepted.refresh_from_db()
    assert accepted.status == Quotation.Status.ACCEPTED


# --- API: staff ------------------------------------------------------------


def test_building_a_quotation_requires_a_commercial_role(login_as_staff):
    quotation = QuotationFactory()
    offering = offering_at("1000.00")
    client = login_as_staff(StaffUserFactory(roles=["analyst"]))

    response = client.post(f"/api/v1/quotations/{quotation.id}/items/", {"offering": offering.id}, format="json")

    assert response.status_code == 403


def test_a_receiver_can_quote_but_not_name_the_price(login_as_staff):
    quotation = QuotationFactory()
    offering = offering_at("1200.00")
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = client.post(
        f"/api/v1/quotations/{quotation.id}/items/",
        # unit_amount sent and deliberately ignored: the rate card prices
        # the line, or quoting would mean nothing.
        {"offering": offering.id, "quantity": 2, "unit_amount": "1.00"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["unit_amount"] == "1200.00"
    assert response.data["gross_amount"] == "2688.00"


def test_a_sent_quotation_cannot_be_patched(login_as_staff):
    quotation = sent_quotation()
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))

    response = client.patch(
        f"/api/v1/quotations/{quotation.id}/", {"notes": "quietly changed"}, format="json",
    )

    assert response.status_code == 400
    assert "revise" in str(response.data["detail"])
    quotation.refresh_from_db()
    assert quotation.notes == ""


def test_status_cannot_be_set_by_patching_a_draft(login_as_staff):
    """It moves through the FSM or not at all -- the Sample/TrainingSession rule."""
    quotation = QuotationFactory()
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))

    response = client.patch(f"/api/v1/quotations/{quotation.id}/", {"status": "accepted"}, format="json")

    assert response.status_code == 200
    quotation.refresh_from_db()
    assert quotation.status == Quotation.Status.DRAFT


def test_a_quotation_cannot_be_created_valid_until_a_past_date(login_as_staff):
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))

    response = client.post(
        "/api/v1/quotations/",
        {
            "customer": CustomerUserFactory().id,
            "service_line": "water_environmental",
            "valid_until": str(timezone.localdate() - datetime.timedelta(days=1)),
        },
        format="json",
    )

    assert response.status_code == 400
    assert "already passed" in str(response.data["valid_until"])


def test_revise_over_the_api_returns_the_replacement_draft(login_as_staff):
    quotation = sent_quotation()
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))

    response = client.post(f"/api/v1/quotations/{quotation.id}/revise/")

    assert response.status_code == 201
    assert response.data["status"] == "draft"
    assert response.data["supersedes"] == quotation.id
    assert len(response.data["items"]) == 1


# --- API: the customer -----------------------------------------------------


def test_a_customer_sees_their_sent_quotations_but_not_drafts(login_as_customer):
    customer = CustomerUserFactory()
    issued = sent_quotation(customer=customer)
    QuotationFactory(customer=customer)  # a draft the lab has not issued

    client = login_as_customer(customer)
    response = client.get("/api/v1/my/quotations/")

    assert response.status_code == 200
    assert [row["reference"] for row in response.data["results"]] == [issued.reference]


def test_a_customer_cannot_see_another_customers_quotation(login_as_customer):
    theirs = sent_quotation(customer=CustomerUserFactory())

    client = login_as_customer(CustomerUserFactory())
    response = client.get(f"/api/v1/my/quotations/{theirs.id}/")

    assert response.status_code == 404


def test_a_customer_accepts_their_own_quotation(login_as_customer):
    customer = CustomerUserFactory()
    quotation = QuotationFactory(customer=customer)
    services.add_item(quotation, offering_at("1200.00"), quantity=2)
    services.send_quotation(quotation)

    client = login_as_customer(customer)
    response = client.post(f"/api/v1/my/quotations/{quotation.id}/accept/")

    assert response.status_code == 200
    assert response.data["status"] == "accepted"
    quotation.refresh_from_db()
    assert quotation.accepted_by_customer_id == customer.id
    assert quotation.order.items.get().unit_amount == Decimal("1200.00")


def test_a_customer_cannot_accept_someone_elses_quotation(login_as_customer):
    from django.db import connection

    theirs = sent_quotation(customer=CustomerUserFactory())

    client = login_as_customer(CustomerUserFactory())
    response = client.post(f"/api/v1/my/quotations/{theirs.id}/accept/")

    assert response.status_code == 404
    # Re-read as staff first. The request left this connection in the
    # *other* customer's RLS context, under which the row is not visible at
    # all -- so a plain refresh_from_db() here raises DoesNotExist. That is
    # the policy working, not the row having gone; asserting the status
    # requires stepping outside the boundary that just held.
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('rls.is_staff', 'true', false)")
    theirs.refresh_from_db()
    assert theirs.status == Quotation.Status.SENT


def test_accepting_twice_is_refused_rather_than_ordering_twice(login_as_customer):
    customer = CustomerUserFactory()
    quotation = sent_quotation(customer=customer)
    client = login_as_customer(customer)
    client.post(f"/api/v1/my/quotations/{quotation.id}/accept/")

    response = client.post(f"/api/v1/my/quotations/{quotation.id}/accept/")

    assert response.status_code == 400
    assert OrderItem.objects.count() == 1


def test_accepting_an_expired_quotation_says_so(login_as_customer):
    customer = CustomerUserFactory()
    quotation = sent_quotation(customer=customer)
    Quotation.objects.filter(pk=quotation.pk).update(valid_until=timezone.localdate() - datetime.timedelta(days=1))

    client = login_as_customer(customer)
    response = client.post(f"/api/v1/my/quotations/{quotation.id}/accept/")

    assert response.status_code == 400
    assert "expired" in str(response.data["detail"])


def test_the_customer_view_omits_the_internal_provenance(login_as_customer):
    customer = CustomerUserFactory()
    quotation = QuotationFactory(customer=customer)
    services.add_item(quotation, offering_at("1000.00"))
    services.send_quotation(quotation)

    client = login_as_customer(customer)
    response = client.get(f"/api/v1/my/quotations/{quotation.id}/")

    line = response.data["items"][0]
    assert "source_price" not in line
    assert "offering" not in line
    assert line["unit_amount"] == "1000.00"
    assert "prepared_by" not in response.data


# --- row-level security ----------------------------------------------------


def test_the_database_scopes_quotations_to_their_customer():
    """
    Straight at the database. What one customer was quoted is exactly what
    another must not see, which makes this the most disclosure-sensitive
    row in the commercial chain.
    """
    from django.db import connection

    mine, theirs = CustomerUserFactory(), CustomerUserFactory()
    my_quotation = sent_quotation(customer=mine)
    sent_quotation(customer=theirs)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('rls.is_staff', 'false', false), set_config('rls.customer_id', %s, false)",
            [str(mine.id)],
        )
        cursor.execute("SELECT id FROM quotation")
        assert {row[0] for row in cursor.fetchall()} == {my_quotation.id}
        cursor.execute("SELECT quotation_id FROM quotation_item")
        assert {row[0] for row in cursor.fetchall()} == {my_quotation.id}

        cursor.execute(
            "SELECT set_config('rls.is_staff', 'false', false), set_config('rls.customer_id', '0', false)"
        )
        cursor.execute("SELECT id FROM quotation")
        assert cursor.fetchall() == []
        cursor.execute("SELECT id FROM quotation_item")
        assert cursor.fetchall() == []

        cursor.execute(
            "SELECT set_config('rls.is_staff', 'true', false), set_config('rls.customer_id', '0', false)"
        )
        cursor.execute("SELECT id FROM quotation")
        assert len(cursor.fetchall()) == 2
