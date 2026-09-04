"""
The fields every priced line carries, in one abstract model.

There are three of them now -- an order line, an invoice line and a
quotation line -- and they are the same shape for the same reason: each
one snapshots a rate rather than joining the catalogue, so that repricing
the rate card cannot rewrite a document that was already sold, billed or
sent. Three copies of that shape would drift, and the first thing to drift
would be the VAT arithmetic, which is the part nobody notices is wrong.

Abstract, not a table: these lines have nothing in common at the database
level and should not share a primary key space, a queryset, or a delete
cascade. What they share is a definition.
"""

from decimal import Decimal

from django.db import models

from apps.catalogue.money import VatTreatment, money, split

VAT_TREATMENT_CHOICES = [
    (VatTreatment.EXCLUSIVE, "VAT-exclusive (net)"),
    (VatTreatment.INCLUSIVE, "VAT-inclusive (gross)"),
]


class PricedLine(models.Model):
    """A quantity of something, at a rate that was copied when it was set."""

    quantity = models.PositiveIntegerField(default=1)
    unit_amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="The figure as it stood when this line was created. Whether it includes VAT is stated by vat_treatment.",
    )
    currency = models.CharField(max_length=3, default="PHP")
    vat_treatment = models.CharField(max_length=16, choices=VAT_TREATMENT_CHOICES, default=VatTreatment.EXCLUSIVE)
    vat_rate_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("12.00"))
    discount_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        help_text="Applied to the line before VAT is split out, so a discounted VAT-inclusive rate still reconciles.",
    )

    class Meta:
        abstract = True

    @property
    def line_amount(self) -> Decimal:
        """The line as quoted: unit x quantity, less the discount, before the VAT split."""
        return money(self.unit_amount * self.quantity * (Decimal(1) - self.discount_pct / Decimal(100)))

    @property
    def net_amount(self) -> Decimal:
        return split(self.line_amount, self.vat_treatment, self.vat_rate_pct)[0]

    @property
    def vat_amount(self) -> Decimal:
        return split(self.line_amount, self.vat_treatment, self.vat_rate_pct)[1]

    @property
    def gross_amount(self) -> Decimal:
        return split(self.line_amount, self.vat_treatment, self.vat_rate_pct)[2]


def sum_lines(lines) -> tuple[Decimal, Decimal, Decimal]:
    """(net, vat, gross) over any iterable of PricedLines."""
    net = vat = gross = Decimal("0.00")
    for line in lines:
        net += line.net_amount
        vat += line.vat_amount
        gross += line.gross_amount
    return money(net), money(vat), money(gross)
