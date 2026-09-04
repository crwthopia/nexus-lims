"""
Billing / Payments entities (Blueprint Section 3.7).

RESOLVED (per NASAT's stated decision, closes Section 13 gap 5): Phase 1
uses manual payment reconciliation, not a live gateway integration. Staff
record payment receipt against an Invoice once funds are confirmed by other
means (cash, bank transfer, or an accepted Purchase Order). Payment.method
is deliberately open to add a `gateway` value later without a schema rewrite.
"""

from decimal import Decimal

from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user
from apps.catalogue.money import VatTreatment, money, split
from apps.samples.models import VAT_TREATMENT_CHOICES


class Invoice(models.Model):
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    id = models.BigAutoField(primary_key=True)
    order = models.ForeignKey(
        "samples.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="invoices",
    )
    enrollment = models.ForeignKey(
        "training.Enrollment", null=True, blank=True, on_delete=models.PROTECT, related_name="invoices",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="PHP")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UNPAID)
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "invoice"
        constraints = [
            models.CheckConstraint(
                check=models.Q(order__isnull=False) | models.Q(enrollment__isnull=False),
                name="invoice_target_required",
            )
        ]
        indexes = [models.Index(fields=["status"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invoice #{self.id}: {self.amount} {self.currency} ({self.get_status_display()})"

    # --- totals -----------------------------------------------------------
    #
    # `amount` stays the authority for what is owed, and stays writable:
    # a walk-in job or a training enrollment is still invoiced as one
    # figure, and this system has always let staff do that. What changes is
    # that an invoice raised *from an order* now has lines, and `amount` is
    # then maintained from them (see services.recalculate) rather than typed
    # -- so the total and the breakdown cannot disagree.

    @property
    def has_lines(self) -> bool:
        return self.lines.exists()

    def line_totals(self) -> tuple[Decimal, Decimal, Decimal]:
        """(net, vat, gross) summed over the lines. Zeroes when there are none."""
        net = vat = gross = Decimal("0.00")
        for line in self.lines.all():
            net += line.net_amount
            vat += line.vat_amount
            gross += line.gross_amount
        return money(net), money(vat), money(gross)


class InvoiceLine(models.Model):
    """
    One billed line, snapshotted away from the order it came from.

    Every figure here is copied, including the description: an invoice is a
    document that was sent to a customer, and it must keep saying what it
    said on the day it was sent however the order, the offering or the rate
    card change afterwards. `order_item` records where the line came from
    and is PROTECTed so that history cannot be deleted; it is not read for
    any of the numbers.
    """

    id = models.BigAutoField(primary_key=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    order_item = models.ForeignKey(
        "samples.OrderItem", null=True, blank=True, on_delete=models.PROTECT, related_name="invoice_lines",
        help_text="The order line billed. Null for a line entered by hand on an invoice with no order behind it.",
    )
    description = models.CharField(
        max_length=255,
        help_text="What the customer sees. Snapshotted, so renaming an offering never rewrites an issued invoice.",
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="PHP")
    vat_treatment = models.CharField(max_length=16, choices=VAT_TREATMENT_CHOICES, default=VatTreatment.EXCLUSIVE)
    vat_rate_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("12.00"))
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "invoice_line"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gt=0), name="invoice_line_quantity_positive"),
            models.CheckConstraint(check=models.Q(unit_amount__gte=0), name="invoice_line_unit_amount_not_negative"),
            models.CheckConstraint(
                check=models.Q(discount_pct__gte=0) & models.Q(discount_pct__lte=100),
                name="invoice_line_discount_within_range",
            ),
            # An order line is billed once. Without this, raising the same
            # invoice twice -- a double-click, a retried request -- bills a
            # customer twice for one piece of work, and nothing downstream
            # would notice.
            models.UniqueConstraint(
                fields=["order_item"], condition=models.Q(order_item__isnull=False),
                name="invoice_line_one_per_order_item",
            ),
        ]

    def __str__(self):
        return f"InvoiceLine #{self.id}: {self.description}"

    @property
    def line_amount(self) -> Decimal:
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


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        PURCHASE_ORDER = "purchase_order", "Purchase Order"
        GATEWAY = "gateway", "Payment Gateway (reserved for future phase)"

    class Status(models.TextChoices):
        PENDING_CONFIRMATION = "pending_confirmation", "Pending Confirmation"
        CONFIRMED = "confirmed", "Confirmed"
        REVERSED = "reversed", "Reversed"

    id = models.BigAutoField(primary_key=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=16, choices=Method.choices)
    reference_number = models.CharField(
        max_length=128, null=True, blank=True, help_text="Bank transfer reference or PO number.",
    )
    recorded_by = models.ForeignKey(
        "accounts.StaffUser", on_delete=models.PROTECT, related_name="recorded_payments",
        help_text="The staff member who confirmed and recorded the payment.",
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING_CONFIRMATION)
    paid_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "payment"
        indexes = [models.Index(fields=["status"])]
        ordering = ["-paid_at"]

    def __str__(self):
        return f"Payment #{self.id}: {self.get_method_display()} ({self.get_status_display()})"
