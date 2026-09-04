"""
Quotations: the priced offer that goes out before any work starts.

This is the one step of the commercial path that was still happening
outside the system -- a spreadsheet, an email, and a PO number typed into
an order afterwards. The consequence was that the price a customer was
quoted and the price they were billed had no connection anyone could
check, which is exactly the kind of gap the rest of this chain (versioned
prices, snapshotted order lines, snapshotted invoice lines) exists to
close.

Two rules give a quotation its meaning, and both are enforced rather than
documented:

**A sent quotation is immutable.** It is a document that went to a
customer; editing it afterwards would make "what did we quote them" an
unanswerable question. Changing an offer means issuing a new quotation
that supersedes it, which is also what the customer's copy of the email
implies happened.

**A quote honoured is a quote honoured.** Accepting copies the quoted
figures onto the order, at the rate quoted, however the rate card has
moved since. That is the whole point of quoting: without it a quotation is
a non-binding guess and the customer finds out at invoice time.
"""

import datetime

from django.db import models
from django_fsm import FSMField, FSMModelMixin, transition
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user
from apps.catalogue.lines import PricedLine, sum_lines
from apps.samples.models import ServiceLine


class Quotation(FSMModelMixin, models.Model):
    """
    A priced offer to one customer, valid until a stated date.

    FSMModelMixin, as on Sample and TrainingSession: without it
    `refresh_from_db()` raises on a protected FSMField, because
    Model.refresh_from_db() does a plain setattr for every field and the
    protected descriptor rejects the second assignment.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"

    id = models.BigAutoField(primary_key=True)
    reference = models.CharField(
        max_length=32, unique=True, editable=False,
        help_text="What the customer quotes back at the lab on a purchase order (Q-2026-00042).",
    )
    customer = models.ForeignKey("accounts.CustomerUser", on_delete=models.PROTECT, related_name="quotations")
    service_line = models.CharField(max_length=32, choices=ServiceLine.choices)
    order = models.ForeignKey(
        "samples.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="quotations",
        help_text="Set when the quotation is raised against an order that already exists; otherwise accepting creates one.",
    )
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="superseded_by",
        help_text="The quotation this one replaces. Revising a sent quotation means issuing a new one, never editing it.",
    )
    status = FSMField(max_length=16, choices=Status.choices, default=Status.DRAFT, protected=True)
    valid_until = models.DateField(help_text="Last day the customer can accept. A quote with no end is not a quote.")
    notes = models.TextField(blank=True, help_text="Terms, scope caveats, anything the customer should read.")

    sent_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    # Who answered. A customer accepting in the portal and a coordinator
    # recording "they sent us a PO" are both real, and an audit trail that
    # could not tell them apart would be worth little.
    accepted_by_customer = models.ForeignKey(
        "accounts.CustomerUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    decided_by_staff = models.ForeignKey(
        "accounts.StaffUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    prepared_by = models.ForeignKey(
        "accounts.StaffUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="prepared_quotations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "quotation"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "valid_until"])]

    def __str__(self):
        return f"{self.reference} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        """
        Assign the reference on first save.

        Derived from the id rather than a counter, so two quotations
        created at once cannot collide over one: the database has already
        decided which is which. Gaps are fine -- a quotation is not a
        tax-sequential document, and a deleted draft leaving a hole in the
        numbering is better than a lock on every insert.
        """
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating and not self.reference:
            self.reference = f"Q-{self.created_at.year}-{self.id:05d}"
            super().save(update_fields=["reference"])

    @property
    def is_expired(self) -> bool:
        """
        Past its date, whatever the stored status says.

        The sweep (apps/quotations/tasks.py) moves `sent` rows to `expired`
        nightly, but a quotation that lapsed at midnight is lapsed at
        00:01, not at 03:00 when the task runs -- so acceptance checks this
        rather than the status, and the status catches up.
        """
        return datetime.date.today() > self.valid_until

    def totals(self):
        return sum_lines(self.items.all())

    # --- transitions -------------------------------------------------------

    @transition(field=status, source=Status.DRAFT, target=Status.SENT)
    def send(self):
        """Issue it. Guarded in services.send_quotation, which checks it has lines and a future date."""

    @transition(field=status, source=Status.SENT, target=Status.ACCEPTED)
    def accept(self):
        """Guarded in services.accept_quotation, which refuses an expired offer and writes the order lines."""

    @transition(field=status, source=Status.SENT, target=Status.DECLINED)
    def decline(self):
        """The customer said no. Terminal: a change of mind is a new quotation."""

    @transition(field=status, source=Status.SENT, target=Status.EXPIRED)
    def expire(self):
        """valid_until passed with no answer."""


class QuotationItem(PricedLine):
    """
    A quoted line: an offering at the rate in force when it was quoted.

    Snapshotted like every other priced line here, and for the sharpest
    reason of the three: this figure is a promise. `source_price` records
    which published rate it came from, for whoever has to explain the
    number later.
    """

    id = models.BigAutoField(primary_key=True)
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="items")
    offering = models.ForeignKey(
        "catalogue.ServiceOffering", on_delete=models.PROTECT, related_name="quotation_items",
    )
    source_price = models.ForeignKey(
        "catalogue.OfferingPrice", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "quotation_item"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gt=0), name="quotation_item_quantity_positive"),
            models.CheckConstraint(check=models.Q(unit_amount__gte=0), name="quotation_item_unit_amount_not_negative"),
            models.CheckConstraint(
                check=models.Q(discount_pct__gte=0) & models.Q(discount_pct__lte=100),
                name="quotation_item_discount_within_range",
            ),
        ]

    def __str__(self):
        return f"QuotationItem #{self.id}: {self.quantity} x {self.offering_id}"
