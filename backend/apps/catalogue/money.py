"""
The VAT split, in one place.

NASAT quotes both ways -- some rates VAT-exclusive, some VAT-inclusive --
so every figure in this system that represents money has to state which
kind it is, and something has to turn that into the three numbers an
invoice needs. That "something" is here rather than on each model, because
there are now three of them (a catalogue price, an order line, an invoice
line) and three copies of this arithmetic would eventually be two.

Two rules the callers depend on:

- **Round half-up, as an invoice does.** Decimal's default is banker's
  rounding, which turns 0.125 into 0.12 -- defensible statistically, and
  not what a customer reading a receipt expects.
- **VAT is the difference of the two rounded figures**, never rounded
  separately. Round all three independently and net + VAT stops equalling
  gross by a centavo, often enough to reach a real invoice.
"""

from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


class VatTreatment:
    """
    The two ways a figure can be quoted. Mirrored by
    `OfferingPrice.VatTreatment`, `OrderItem` and `InvoiceLine`, which each
    declare their own TextChoices for the admin and the API -- this holds
    the values the arithmetic keys on.
    """

    EXCLUSIVE = "exclusive"
    INCLUSIVE = "inclusive"


def money(value: Decimal) -> Decimal:
    """Round to centavos, half-up."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def split(amount: Decimal, treatment: str, vat_rate_pct: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """
    (net, vat, gross) for `amount` quoted under `treatment`.

    `amount` is the figure as published or as billed -- already multiplied
    by quantity and discounted, if it is a line rather than a unit rate.
    """
    rate = Decimal(1) + (Decimal(vat_rate_pct) / Decimal(100))
    if treatment == VatTreatment.INCLUSIVE:
        gross = money(amount)
        net = money(amount / rate)
    else:
        net = money(amount)
        gross = money(amount * rate)
    return net, gross - net, gross
