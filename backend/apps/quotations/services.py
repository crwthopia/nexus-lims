"""
The quotation lifecycle: pricing it, sending it, and honouring it.

Every transition that means something commercially is here rather than on
the model, because each one is a guard plus a state change plus a side
effect, and django-fsm's @transition is only the middle of the three.
"""

from django.db import transaction
from django.utils import timezone

from apps.catalogue.services import today  # noqa: F401  (re-exported for tasks.py)
from apps.notifications.models import NotificationRecord
from apps.notifications.notify import notify
from apps.quotations.models import Quotation, QuotationItem
from apps.samples.models import Order, OrderItem


class QuotationError(Exception):
    """A quotation asked to do something its state or contents do not allow."""


@transaction.atomic
def add_item(quotation, offering, *, quantity=1, discount_pct=0, on_date=None):
    """
    Quote `offering` at the rate in force, and return the new line.

    Only on a draft: a sent quotation is a document a customer is reading,
    and adding a line to it would change what they were offered without
    their knowing.
    """
    if quotation.status != Quotation.Status.DRAFT:
        raise QuotationError(
            f"{quotation.reference} is {quotation.get_status_display().lower()}. "
            "Issue a new quotation that supersedes it rather than editing this one."
        )

    on_date = on_date or today()
    price = offering.price_on(on_date)
    if price is None:
        raise QuotationError(
            f"{offering.code} has no price in force on {on_date}. Set one in the catalogue before quoting it."
        )

    return QuotationItem.objects.create(
        quotation=quotation,
        offering=offering,
        quantity=quantity,
        unit_amount=price.amount,
        currency=price.currency,
        vat_treatment=price.vat_treatment,
        vat_rate_pct=price.vat_rate_pct,
        discount_pct=discount_pct,
        source_price=price,
    )


@transaction.atomic
def send_quotation(quotation):
    """
    Issue it to the customer, and stop it being editable.

    Two guards, both of which describe a quotation that cannot be answered:
    an empty one offers nothing, and one whose validity has already passed
    is expired the moment it lands.
    """
    if not quotation.items.exists():
        raise QuotationError("A quotation with no lines offers nothing. Add at least one before sending it.")
    if quotation.is_expired:
        raise QuotationError(
            f"{quotation.reference} is valid until {quotation.valid_until}, which has passed. "
            "Extend the date before sending it."
        )

    quotation.send()
    quotation.sent_at = timezone.now()
    quotation.save()

    # One path for every email the lab sends (apps/notifications). The
    # notice carries the total and the date and nothing else: the breakdown
    # lives in the customer's account, where it cannot be altered in
    # transit or forwarded to somebody it was not priced for.
    notify(
        NotificationRecord.Kind.QUOTATION_SENT,
        quotation.customer.email,
        f"Quotation {quotation.reference} from NASAT Laboratories",
        dedupe_key=f"quotation-sent:{quotation.id}",
        entity=quotation,
    )
    return quotation


@transaction.atomic
def accept_quotation(quotation, *, customer=None, staff=None):
    """
    Accept it, and put what was quoted onto an order.

    **The quoted figures are copied, not re-priced.** A quote honoured is a
    quote honoured: if the rate card has risen since, the customer pays what
    they were offered, and if it has fallen they still do. Re-reading the
    catalogue here would make every quotation a non-binding guess that the
    customer discovers at invoice time.

    `customer` or `staff` records who answered -- a customer accepting in
    the portal, or a coordinator recording the purchase order that arrived
    by email. Exactly one is expected.
    """
    if quotation.is_expired:
        raise QuotationError(
            f"{quotation.reference} expired on {quotation.valid_until} and cannot be accepted. "
            "Issue a new quotation."
        )

    order = quotation.order
    if order is None:
        order = Order.objects.create(
            customer=quotation.customer,
            service_line=quotation.service_line,
            status=Order.Status.SUBMITTED,
        )
        quotation.order = order

    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                offering=item.offering,
                quantity=item.quantity,
                unit_amount=item.unit_amount,
                currency=item.currency,
                vat_treatment=item.vat_treatment,
                vat_rate_pct=item.vat_rate_pct,
                discount_pct=item.discount_pct,
                source_price=item.source_price,
            )
            for item in quotation.items.select_related("offering").all()
        ]
    )

    quotation.accept()
    quotation.decided_at = timezone.now()
    quotation.accepted_by_customer = customer
    quotation.decided_by_staff = staff
    quotation.save()
    return quotation


@transaction.atomic
def decline_quotation(quotation, *, staff=None):
    """
    Record a no. Terminal: a change of mind is a new quotation, because the
    offer being reconsidered may no longer be the offer that was made.

    Only `staff` is recorded here, deliberately. `accepted_by_customer`
    means what its name says -- a customer put their name to an offer --
    and reusing it for a decline would make an acceptance audit that reads
    that column say something false. Who declined is in the history row
    (simple_history) if it is ever asked for.
    """
    quotation.decline()
    quotation.decided_at = timezone.now()
    quotation.decided_by_staff = staff
    quotation.save()
    return quotation


def revise(quotation, *, prepared_by=None, valid_until=None):
    """
    Start a new draft carrying this quotation's lines, pointing back at it.

    The documented way to change an offer that has already gone out. The
    lines are copied at their *quoted* figures rather than re-priced, so a
    revision that only changes one line does not silently reprice the rest;
    repricing a line means removing it and adding it again.
    """
    replacement = Quotation.objects.create(
        customer=quotation.customer,
        service_line=quotation.service_line,
        order=quotation.order,
        supersedes=quotation,
        valid_until=valid_until or quotation.valid_until,
        notes=quotation.notes,
        prepared_by=prepared_by or quotation.prepared_by,
    )
    QuotationItem.objects.bulk_create(
        [
            QuotationItem(
                quotation=replacement,
                offering=item.offering,
                quantity=item.quantity,
                unit_amount=item.unit_amount,
                currency=item.currency,
                vat_treatment=item.vat_treatment,
                vat_rate_pct=item.vat_rate_pct,
                discount_pct=item.discount_pct,
                source_price=item.source_price,
            )
            for item in quotation.items.all()
        ]
    )
    return replacement
