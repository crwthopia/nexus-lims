"""
Raising an invoice from an order, and keeping its total honest.

The whole of the care here is in one idea: **an invoice is a document that
was sent to someone.** Every figure it carries is copied at the moment it
is raised -- the description, the unit rate, the VAT treatment, the rate
percentage -- so that renaming an offering, repricing the rate card, or
editing the order afterwards cannot rewrite what a customer was told they
owed. The link back to the order line is kept for provenance and is never
read for a number.
"""

from decimal import Decimal

from django.db import transaction

from apps.billing.models import Invoice, InvoiceLine


def line_description(item) -> str:
    """
    What the customer reads. Includes the rate-card code because that is
    what a purchase order quotes back at the lab, and the quantity is
    carried in its own column rather than folded into the text.
    """
    return f"{item.offering.code} — {item.offering.name}"


@transaction.atomic
def invoice_order(order, *, items=None, currency=None):
    """
    Bill an order's items, and return the Invoice.

    `items` defaults to every line on the order that has not been billed
    yet, which is what makes this safe to call twice: an order part-billed
    in March and finished in July gets a second invoice for the July work
    and not a duplicate of March's. The unique constraint on
    `InvoiceLine.order_item` is the backstop -- a double-clicked button
    fails at the database rather than billing a customer twice.
    """
    pending = list(items if items is not None else unbilled_items(order))
    if not pending:
        raise ValueError("Every line on this order has already been invoiced.")

    mixed = {item.currency for item in pending}
    if len(mixed) > 1:
        # Summing two currencies into one `amount` would produce a number
        # that is not money in either of them.
        raise ValueError(f"This order mixes currencies ({', '.join(sorted(mixed))}); invoice them separately.")

    invoice = Invoice.objects.create(
        order=order,
        amount=Decimal("0.00"),  # replaced by recalculate() below, once the lines exist
        currency=currency or pending[0].currency,
    )
    InvoiceLine.objects.bulk_create(
        [
            InvoiceLine(
                invoice=invoice,
                order_item=item,
                description=line_description(item),
                quantity=item.quantity,
                unit_amount=item.unit_amount,
                currency=item.currency,
                vat_treatment=item.vat_treatment,
                vat_rate_pct=item.vat_rate_pct,
                discount_pct=item.discount_pct,
            )
            for item in pending
        ]
    )
    recalculate(invoice)
    return invoice


def unbilled_items(order):
    """
    Order lines with no invoice line against them.

    **An order line is billed once, and voiding the invoice does not free
    it.** That is a deliberate limit, and worth stating plainly because the
    friendlier behaviour is the obvious thing to want:

    The rule "one invoice line per order line" is enforced by a unique
    constraint, which is what makes a double-clicked Raise Invoice button
    fail at the database instead of charging a customer twice. Excepting
    void invoices from it cannot be expressed there -- a Postgres index
    predicate cannot reach into `invoice` to read a status -- so it would
    have to be either a copy of that status kept on the line, which can
    drift in the money path, or nothing but this function, which is a
    check any future caller can bypass by not calling it.

    The escape hatch is the honest one: an invoice raised in error is
    voided *and* the order corrected. Re-adding the line records that the
    first sale was cancelled and a new one made, which is what happened,
    and the new line bills normally.
    """
    return order.items.filter(invoice_lines__isnull=True)


def recalculate(invoice):
    """
    Set `amount` from the lines.

    `amount` is the gross -- what the customer pays -- because that is what
    it has always meant on this model and what every downstream reader
    (the portal, the payment flow) treats it as. Net and VAT are exposed
    alongside it by the serializer rather than stored, so the three can
    never disagree.
    """
    _, _, gross = invoice.line_totals()
    if invoice.amount != gross:
        invoice.amount = gross
        invoice.save(update_fields=["amount"])
    return invoice
