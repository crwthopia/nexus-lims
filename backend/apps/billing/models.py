"""
Billing / Payments entities (Blueprint Section 3.7).

RESOLVED (per NASAT's stated decision, closes Section 13 gap 5): Phase 1
uses manual payment reconciliation, not a live gateway integration. Staff
record payment receipt against an Invoice once funds are confirmed by other
means (cash, bank transfer, or an accepted Purchase Order). Payment.method
is deliberately open to add a `gateway` value later without a schema rewrite.
"""

from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user


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
