"""
Sample and Order entities (Blueprint Section 3.2, C-1/C-2).

Sample.status is a django-fsm-2 FSMField (Blueprint Section 2.1 item 3a) so
illegal transitions raise an error at the model layer regardless of which
API endpoint or admin action attempts it. Guard conditions differ by
service_line (Blueprint Section 2.1 item 3a segregation-of-duties RESOLVED
note): regulated lines (Water/Environmental) hard-enforce Reviewer != Approver,
non-regulated lines (Failure Analysis) permit a self-approve bypass.
"""

from decimal import Decimal

from django.db import models
from django_fsm import FSMField, FSMModelMixin, transition
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user
from apps.catalogue.money import VatTreatment, money, split

# The two ways a figure can be quoted, as model choices. Declared here as
# well as on catalogue.OfferingPrice because a line's snapshot has to stand
# on its own -- it is what the customer was billed, whatever the catalogue
# says now.
VAT_TREATMENT_CHOICES = [
    (VatTreatment.EXCLUSIVE, "VAT-exclusive (net)"),
    (VatTreatment.INCLUSIVE, "VAT-inclusive (gross)"),
]


class ServiceLine(models.TextChoices):
    FAILURE_ANALYSIS = "failure_analysis", "Failure Analysis / Materials Characterization"
    WATER_ENVIRONMENTAL = "water_environmental", "Water / Environmental Testing"
    TRAINING = "training", "Training"


class Order(models.Model):
    """
    Blueprint Section 3.2: customer-portal-facing wrapper grouping samples
    under one customer request/quote/invoice. Not an ASTM Fig. 3 term
    (flagged as a blueprint-level addition, Section 13).
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.BigAutoField(primary_key=True)
    customer = models.ForeignKey("accounts.CustomerUser", on_delete=models.PROTECT, related_name="orders")
    service_line = models.CharField(max_length=32, choices=ServiceLine.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "order"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order #{self.id} ({self.get_service_line_display()})"


class OrderItem(models.Model):
    """
    One line of what a customer ordered: an offering, a quantity, and the
    price it was sold at.

    **The price is a snapshot, not a join.** `unit_amount`, `vat_treatment`
    and `vat_rate_pct` are copied from the catalogue when the line is
    created and never read live again. Joining the rate card at display
    time would silently reprice every historical order the next time the
    card changed -- which is the specific accident that versioned prices
    (apps/catalogue/models.py) exist to prevent, and it would undo them.
    `source_price` records *which* published rate was copied, for anyone
    who later asks why a line says what it says; it is provenance, not the
    authority.

    This is also what makes revenue attributable per analysis. Before it, a
    TestRequest reached the rate card only through its method's
    many-to-many, so a method sold both standalone and inside a panel could
    not be credited to either without guessing (see apps/analytics).
    """

    id = models.BigAutoField(primary_key=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    offering = models.ForeignKey(
        "catalogue.ServiceOffering", on_delete=models.PROTECT, related_name="order_items",
        help_text="PROTECTed: an offering that has been sold cannot be deleted out from under the orders that reference it.",
    )
    quantity = models.PositiveIntegerField(default=1)

    # --- the price snapshot ----------------------------------------------
    unit_amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="The offering's published figure at the moment this line was created. Whether it includes VAT is stated by vat_treatment.",
    )
    currency = models.CharField(max_length=3, default="PHP")
    vat_treatment = models.CharField(max_length=16, choices=VAT_TREATMENT_CHOICES, default=VatTreatment.EXCLUSIVE)
    vat_rate_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("12.00"))
    discount_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        help_text="Applied to the line before VAT is split out, so a discounted VAT-inclusive rate still reconciles.",
    )
    source_price = models.ForeignKey(
        "catalogue.OfferingPrice", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Which published rate this line copied. Provenance only -- the snapshot above is what the line is billed at.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "order_item"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gt=0), name="order_item_quantity_positive"),
            models.CheckConstraint(check=models.Q(unit_amount__gte=0), name="order_item_unit_amount_not_negative"),
            models.CheckConstraint(
                check=models.Q(discount_pct__gte=0) & models.Q(discount_pct__lte=100),
                name="order_item_discount_within_range",
            ),
        ]

    def __str__(self):
        return f"OrderItem #{self.id}: {self.quantity} x {self.offering_id}"

    @property
    def line_amount(self) -> Decimal:
        """The line as quoted: unit x quantity, less the discount, before the VAT split."""
        gross_of_discount = self.unit_amount * self.quantity
        return money(gross_of_discount * (Decimal(1) - self.discount_pct / Decimal(100)))

    @property
    def net_amount(self) -> Decimal:
        return split(self.line_amount, self.vat_treatment, self.vat_rate_pct)[0]

    @property
    def vat_amount(self) -> Decimal:
        return split(self.line_amount, self.vat_treatment, self.vat_rate_pct)[1]

    @property
    def gross_amount(self) -> Decimal:
        return split(self.line_amount, self.vat_treatment, self.vat_rate_pct)[2]


class Sample(FSMModelMixin, models.Model):
    """
    Blueprint Section 3.2. service_line is denormalized directly onto Sample
    (added per NASAT architectural review) rather than only derived via
    order_id, since walk-in samples have no Order but the django-fsm
    segregation-of-duties guard needs this value on every Sample regardless
    of intake path.

    status values, in FSM order:
    pre_registered -> registered -> received -> in_prep -> in_testing ->
    under_review -> approved | rejected -> under_investigation ->
    retest_pending (-> in_testing) | disposed

    FSMModelMixin: without it, instance.refresh_from_db() raises
    AttributeError on this model, since Model.refresh_from_db() does a plain
    setattr() for every field and status's protected=True descriptor rejects
    any second direct assignment. The mixin teaches refresh_from_db() to
    skip protected FSM fields instead of reassigning them.
    """

    class Status(models.TextChoices):
        PRE_REGISTERED = "pre_registered", "Pre-registered"
        REGISTERED = "registered", "Registered"
        RECEIVED = "received", "Received"
        IN_PREP = "in_prep", "In Prep"
        IN_TESTING = "in_testing", "In Testing"
        UNDER_REVIEW = "under_review", "Under Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        UNDER_INVESTIGATION = "under_investigation", "Under Investigation"
        RETEST_PENDING = "retest_pending", "Retest Pending"
        DISPOSED = "disposed", "Disposed"

    id = models.BigAutoField(primary_key=True)
    order = models.ForeignKey(
        Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="samples",
        help_text="Nullable for walk-in/non-portal samples.",
    )
    service_line = models.CharField(max_length=32, choices=ServiceLine.choices)
    unique_sample_code = models.CharField(max_length=64, unique=True, db_index=True)
    client_reference = models.CharField(max_length=128, blank=True)
    sampling_point = models.CharField(max_length=255, blank=True)
    collection_datetime = models.DateTimeField(null=True, blank=True)
    container_type = models.CharField(max_length=128, blank=True)
    container_count = models.PositiveIntegerField(default=1)
    preservation_method = models.CharField(max_length=255, blank=True)
    retention_period = models.CharField(max_length=128, blank=True, help_text="Physical sample retention, distinct from RetentionPolicy record retention (Section 3.1a).")
    holding_time = models.DurationField(null=True, blank=True)
    status = FSMField(max_length=32, choices=Status.choices, default=Status.PRE_REGISTERED, protected=True)
    safety_flags = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "sample"
        indexes = [models.Index(fields=["status", "service_line"])]
        ordering = ["-created_at"]

    def __str__(self):
        return self.unique_sample_code

    # --- django-fsm transitions (Blueprint Section 2.1 item 3a) ---

    @transition(field=status, source=Status.PRE_REGISTERED, target=Status.REGISTERED)
    def register(self):
        """FR-C1-01 Pre-registration to Registered."""

    @transition(field=status, source=Status.REGISTERED, target=Status.RECEIVED)
    def receive(self):
        """FR-C1-09: physical sample arrives, chain of custody starts."""

    @transition(field=status, source=Status.RECEIVED, target=Status.IN_PREP)
    def start_prep(self):
        """FR-C1-13: sample prep begins."""

    @transition(field=status, source=Status.IN_PREP, target=Status.IN_TESTING)
    def start_testing(self):
        """FR-C3-01 to C3-09."""

    @transition(field=status, source=Status.IN_TESTING, target=Status.UNDER_REVIEW)
    def submit_for_review(self):
        """FR-C4-04."""

    @transition(field=status, source=Status.UNDER_REVIEW, target=Status.APPROVED)
    def approve(self):
        """
        FR-C5-01 to C5-04. Guard condition (enforced at the view/serializer
        layer, not representable as a pure FSM condition without request
        context): for service_line == WATER_ENVIRONMENTAL, the acting
        Approver's ApprovalAction.approver_id must differ from the sample's
        ReviewAction.reviewer_id (regulated segregation of duties,
        ASTM E1578-18 Section 6.6.1). For FAILURE_ANALYSIS, a self-approve
        bypass is permitted. See apps.review.services for the guard
        implementation referenced by the Review/Approval screen (Section 5.1).
        """

    @transition(field=status, source=Status.UNDER_REVIEW, target=Status.UNDER_INVESTIGATION)
    def reject(self):
        """
        RESOLVED per ISO/IEC 17025:2017 7.10 Nonconforming Work (Blueprint
        Section 2.1 item 3a, closes Section 13 gap 12): rejection routes to
        under_investigation, not directly to retest_pending, halting work
        and withholding the report pending an evaluation of significance.
        """

    @transition(field=status, source=Status.UNDER_INVESTIGATION, target=Status.RETEST_PENDING)
    def authorize_retest(self):
        """QA Officer or Lab Supervisor role only (enforced at view layer, not pure FSM)."""

    @transition(field=status, source=Status.UNDER_INVESTIGATION, target=Status.DISPOSED)
    def dispose(self):
        """QA Officer or Lab Supervisor role only (enforced at view layer, not pure FSM)."""

    @transition(field=status, source=Status.RETEST_PENDING, target=Status.IN_TESTING)
    def requeue_for_retest(self):
        """Re-queues directly into the assigned Analyst's queue without a new Order/TestRequest."""


class ChainOfCustodyEvent(models.Model):
    """Blueprint Section 3.2: standard chain-of-custody model (Section 13 gap 1, RESOLVED)."""

    class EventType(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        TRANSFER = "transfer", "Transfer"
        ALIQUOT = "aliquot", "Aliquot"
        DISPOSAL = "disposal", "Disposal"

    id = models.BigAutoField(primary_key=True)
    sample = models.ForeignKey(Sample, on_delete=models.CASCADE, related_name="chain_of_custody_events")
    from_holder = models.ForeignKey(
        "accounts.StaffUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="custody_events_released",
    )
    to_holder = models.ForeignKey(
        "accounts.StaffUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="custody_events_received",
    )
    from_location = models.CharField(max_length=255, blank=True)
    to_location = models.CharField(max_length=255, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    event_type = models.CharField(max_length=16, choices=EventType.choices)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "chain_of_custody_event"
        ordering = ["sample_id", "timestamp"]

    def __str__(self):
        return f"{self.sample.unique_sample_code}: {self.get_event_type_display()} @ {self.timestamp:%Y-%m-%d %H:%M}"
