"""
Adding a line to an order.

One function, and it exists so that the price snapshot is taken in exactly
one place. A serializer that accepted `unit_amount` from the client would
let a caller invent a price; one that looked the rate up at render time
would reprice history. Both are the same mistake from different ends.
"""

from django.db import transaction

from apps.catalogue.services import today
from apps.samples.models import OrderItem


class Unpriced(Exception):
    """Raised when an offering has no rate in force on the day it is being sold."""


@transaction.atomic
def add_item(order, offering, *, quantity=1, discount_pct=0, on_date=None):
    """
    Put `offering` on `order` at the rate in force today, and return the
    new OrderItem.

    Refuses an unpriced offering rather than defaulting to zero: a line
    that silently bills nothing is worse than a form that says why it
    cannot be added.
    """
    on_date = on_date or today()
    price = offering.price_on(on_date)
    if price is None:
        raise Unpriced(
            f"{offering.code} has no price in force on {on_date}. Set one in the catalogue before selling it."
        )

    return OrderItem.objects.create(
        order=order,
        offering=offering,
        quantity=quantity,
        unit_amount=price.amount,
        currency=price.currency,
        vat_treatment=price.vat_treatment,
        vat_rate_pct=price.vat_rate_pct,
        discount_pct=discount_pct,
        source_price=price,
    )
