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
from django.utils import timezone
from django_fsm import FSMField, FSMModelMixin, transition
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user
from apps.catalogue.lines import VAT_TREATMENT_CHOICES, PricedLine  # noqa: F401  (re-exported for apps.billing)


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


class OrderItem(PricedLine):
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
    # quantity and the price snapshot come from PricedLine
    # (apps/catalogue/lines.py), shared with the invoice and quotation
    # lines that carry the same shape for the same reason.
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

    with one branch off the intake path: registered | received ->
    receipt_rejected -> disposed, for an item the laboratory declines to
    accept (ISO/IEC 17025:2017 7.4.3). That is a different clause, and a
    different decision, from the post-review `reject` below -- nothing was
    tested, so there is no nonconforming *work* to investigate.

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
        RECEIPT_REJECTED = "receipt_rejected", "Rejected at Receipt"
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
    unique_sample_code = models.CharField(
        max_length=64, unique=True, db_index=True,
        help_text=(
            "Allocated server-side by apps.samples.identity.allocate_sample_code and immutable "
            "thereafter (ISO/IEC 17025:2017 7.4.2 -- the identification is retained for the life "
            "of the item). A trigger on this table, not just the serializer, refuses a change."
        ),
    )
    client_reference = models.CharField(max_length=128, blank=True)
    sampling_point = models.CharField(max_length=255, blank=True)
    collection_datetime = models.DateTimeField(null=True, blank=True)
    container_type = models.CharField(max_length=128, blank=True)
    container_count = models.PositiveIntegerField(default=1)
    preservation_method = models.CharField(max_length=255, blank=True)
    retention_period = models.CharField(max_length=128, blank=True, help_text="Physical sample retention, distinct from RetentionPolicy record retention (Section 3.1a).")
    holding_time = models.DurationField(null=True, blank=True)
    status = FSMField(max_length=32, choices=Status.choices, default=Status.PRE_REGISTERED, protected=True)
    # When the laboratory physically took custody of the item -- ISO/IEC
    # 17025:2017 7.8.2.1 l) puts this on the report wherever it bears on the
    # validity of the results, and every holding-time calculation counts
    # from it. Denormalized from the RECEIPT chain-of-custody event rather
    # than derived on read: it is answered on every worksheet, every label
    # and every COA, and a report that had to walk a related table to
    # discover its own receipt date is a report that renders differently
    # depending on what was prefetched.
    received_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Set by the receive transition from the operator-supplied arrival time. Null until the item arrives.",
    )
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

    @transition(
        field=status,
        source=[Status.REGISTERED, Status.RECEIVED],
        target=Status.RECEIPT_REJECTED,
    )
    def reject_at_receipt(self):
        """
        ISO/IEC 17025:2017 7.4.3: the laboratory declines to accept the item.

        Reachable from `received` as well as `registered` because the two
        are the same physical situation seen a minute apart -- a cooler
        booked in at the counter and opened at the bench -- and a clerk who
        has already pressed Receive should not have to unwind that to
        record a leaking bottle.

        Deliberately *not* routed into under_investigation, where the
        post-review `reject` goes. That path is 7.10 Nonconforming Work,
        which asks what the significance of the nonconformity is for
        results already produced. Here nothing was tested, so the only
        remaining question is what happens to the item -- hence
        `dispose` as the one onward transition.
        """

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

    @transition(
        field=status,
        source=[Status.UNDER_INVESTIGATION, Status.RECEIPT_REJECTED],
        target=Status.DISPOSED,
    )
    def dispose(self):
        """
        QA Officer or Lab Supervisor role only (enforced at view layer, not pure FSM).

        Also the terminus of the intake-rejection branch: an item refused
        under 7.4.3 is either returned or disposed of, and both are
        recorded here plus a DISPOSAL chain-of-custody event. Without this
        source, a refused item had no legal next state and sat in
        receipt_rejected forever.
        """

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
    # Two clocks, and the distinction is the whole point of the pair.
    #
    # `timestamp` is the system's: auto_now_add, unwritable, the moment the
    # row was created. `occurred_at` is the operator's: when the handover
    # actually happened. They differ whenever the record is not made at the
    # bench -- a delivery signed for at 17:40 and keyed in at 18:05 the next
    # morning -- and before `occurred_at` existed that custody event was
    # simply unrecordable, because auto_now_add cannot be overridden.
    #
    # ALCOA wants records contemporaneous *and* accurate, which is exactly
    # why neither field alone will do: keeping both means the timeline says
    # when custody moved, and the audit trail still says when somebody
    # wrote that down.
    occurred_at = models.DateTimeField(
        default=timezone.now,
        help_text="When custody actually changed hands. Operator-supplied, defaults to now, never in the future.",
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        help_text="When this row was written. System clock, not the event time -- see occurred_at.",
    )
    event_type = models.CharField(max_length=16, choices=EventType.choices)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "chain_of_custody_event"
        # By the event time, not the write time: the custody timeline is a
        # claim about the physical item, and a backdated receipt keyed in
        # after a later transfer belongs before it. `timestamp` breaks ties
        # so the order is still total, and still stable between reads.
        ordering = ["sample_id", "occurred_at", "timestamp"]

    def __str__(self):
        return f"{self.sample.unique_sample_code}: {self.get_event_type_display()} @ {self.occurred_at:%Y-%m-%d %H:%M}"


# The five plain yes/no checks a receiving clerk makes on an item, paired
# with how each one reads when it fails. Defined once, at module level,
# because both the Python conformity summary (SampleReceipt.deviation_
# reasons) and the database CHECK constraint below are built from it -- and
# a checklist whose two enforcement points disagree is worse than either
# alone.
RECEIPT_CHECKS = (
    ("seal_intact", "the seal was not intact"),
    ("volume_sufficient", "the quantity was insufficient for the tests requested"),
    ("container_conforms", "the container did not match the type specified"),
    ("preservation_conforms", "preservation did not match what the method requires"),
    ("labelling_legible", "the item's own labelling was missing or illegible"),
)


class SampleReceipt(models.Model):
    """
    What the laboratory observed when the item arrived (ISO/IEC 17025:2017
    7.4.3, closes the intake half of Section 13 gap 1).

    7.4.3 is short and has three separate demands, and this row is where
    each of them is discharged:

      1. *Record deviations from specified conditions on receipt.* The
         checklist columns and `deviations` below. The CHECK constraint
         makes a nonconforming receipt with no written deviation
         impossible to store, rather than merely discouraged.
      2. *Consult the customer before proceeding* where there is doubt
         about suitability, and record the outcome. `customer_consulted_at`
         / `consultation_outcome`, gated onto the workflow by
         apps.samples.receipt_services.check_can_begin_work, which is what
         actually stops a doubtful item reaching an analyst.
      3. *Include a disclaimer in the report* where the customer requires
         testing anyway, saying which results may be affected.
         `report_disclaimer_required` / `disclaimer_text`.

    A separate table rather than a dozen more nullable columns on Sample,
    for three reasons that all point the same way: it is one row per
    physical arrival, it is the thing a receipt document prints from, and
    it gets its own history stream -- so "who said the cooler was at 9 °C,
    and when did they say it" is answerable without diffing Sample.

    Storage and conditioning conditions themselves (7.4.4) are out of scope
    here beyond `receipt_temperature_c` and `storage_location`: monitoring a
    fridge over time is equipment's job, not the arrival record's.
    """

    class Condition(models.TextChoices):
        INTACT = "intact", "Intact"
        DAMAGED = "damaged", "Damaged"
        LEAKING = "leaking", "Leaking"
        SEAL_BROKEN = "seal_broken", "Seal broken"
        TEMPERATURE_EXCURSION = "temperature_excursion", "Temperature excursion"
        INSUFFICIENT_QUANTITY = "insufficient_quantity", "Insufficient quantity"
        OTHER = "other", "Other nonconformity"

    id = models.BigAutoField(primary_key=True)
    sample = models.OneToOneField(Sample, on_delete=models.CASCADE, related_name="receipt")

    received_at = models.DateTimeField(help_text="Arrival time as observed, mirrored onto Sample.received_at.")
    received_by = models.ForeignKey(
        "accounts.StaffUser", on_delete=models.PROTECT, related_name="sample_receipts",
        help_text="PROTECTed: the person who accepted an item cannot be deleted out from under the record saying so.",
    )
    received_from = models.CharField(
        max_length=255, blank=True,
        help_text="Courier, sampler or customer representative who handed the item over.",
    )

    condition_on_receipt = models.CharField(
        max_length=32, choices=Condition.choices, default=Condition.INTACT,
    )
    # Nullable rather than defaulted, and the three states are distinct:
    # True conforms, False is an excursion, NULL means no temperature
    # requirement applied to this item. Defaulting an unmeasured cooler to
    # "conforms" would put an assertion nobody made into a regulated record.
    receipt_temperature_c = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Measured temperature on arrival, where the method specifies one.",
    )
    temperature_conforms = models.BooleanField(
        null=True, blank=True,
        help_text="Null when no temperature requirement applies to this item -- not the same as conforming.",
    )

    seal_intact = models.BooleanField(default=True)
    volume_sufficient = models.BooleanField(default=True)
    container_conforms = models.BooleanField(default=True)
    preservation_conforms = models.BooleanField(default=True)
    labelling_legible = models.BooleanField(default=True)

    storage_location = models.CharField(
        max_length=255, blank=True, help_text="Where the item was put pending prep (7.4.4).",
    )
    deviations = models.TextField(
        blank=True,
        help_text="Required whenever any check above fails -- enforced by a CHECK constraint, per 7.4.3.",
    )

    customer_consulted_at = models.DateTimeField(null=True, blank=True)
    consultation_outcome = models.TextField(
        blank=True, help_text="What the customer instructed. 7.4.3 requires the outcome be recorded, not just the call.",
    )
    customer_authorised_despite_deviation = models.BooleanField(
        default=False,
        help_text="The customer required testing to proceed knowing the deviation. Triggers the report disclaimer.",
    )

    # Derived in save(), never set by a caller -- see the method for why it
    # is stored rather than computed on read.
    report_disclaimer_required = models.BooleanField(default=False)
    disclaimer_text = models.TextField(
        blank=True,
        help_text="Which results may be affected by the deviation. Printed on the COA when the flag above is set.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "sample_receipt"
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["report_disclaimer_required"]),
            models.Index(fields=["received_at"]),
        ]
        constraints = [
            # 7.4.3 first sentence, in the schema. Reads as: either every
            # check passed, or somebody wrote down what didn't.
            models.CheckConstraint(
                check=(
                    (
                        models.Q(condition_on_receipt="intact")
                        & models.Q(seal_intact=True)
                        & models.Q(volume_sufficient=True)
                        & models.Q(container_conforms=True)
                        & models.Q(preservation_conforms=True)
                        & models.Q(labelling_legible=True)
                        & (models.Q(temperature_conforms=True) | models.Q(temperature_conforms__isnull=True))
                    )
                    | ~models.Q(deviations="")
                ),
                name="sample_receipt_deviation_recorded",
            ),
            # 7.4.3 second sentence: the customer's instruction to proceed
            # anyway is only meaningful alongside the consultation it came
            # out of. A bare flag with no recorded outcome is the shape of
            # a checkbox someone ticked to get past a form.
            models.CheckConstraint(
                check=(
                    models.Q(customer_authorised_despite_deviation=False)
                    | ~models.Q(consultation_outcome="")
                ),
                name="sample_receipt_authorisation_needs_consultation",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(report_disclaimer_required=False)
                    | ~models.Q(disclaimer_text="")
                ),
                name="sample_receipt_disclaimer_has_text",
            ),
        ]

    def __str__(self):
        state = "conforming" if self.is_conforming else "with deviations"
        return f"Receipt of {self.sample.unique_sample_code} ({state})"

    @property
    def deviation_reasons(self):
        """Every check that failed, phrased for a person. Empty means the item conformed."""
        reasons = []
        if self.condition_on_receipt != self.Condition.INTACT:
            reasons.append(f"condition on receipt was '{self.get_condition_on_receipt_display()}'")
        for field, phrasing in RECEIPT_CHECKS:
            if not getattr(self, field):
                reasons.append(phrasing)
        # `is False` rather than `not`: None means no requirement applied.
        if self.temperature_conforms is False:
            measured = f" ({self.receipt_temperature_c} °C)" if self.receipt_temperature_c is not None else ""
            reasons.append(f"the item was outside its specified temperature range{measured}")
        return reasons

    @property
    def is_conforming(self):
        return not self.deviation_reasons

    @property
    def consultation_recorded(self):
        """7.4.3's 'record the outcome of the consultation' -- the call alone is not the record."""
        return self.customer_consulted_at is not None and bool(self.consultation_outcome.strip())

    def save(self, *args, **kwargs):
        """
        Derives `report_disclaimer_required` from the two facts that create
        the obligation: the item deviated, and the customer required testing
        regardless.

        Stored rather than left as a property because the question it
        answers is asked in the aggregate -- "which reports issued this
        quarter carry a disclaimer" is a filter, and a property cannot be
        one -- and because it belongs in this row's history, so a change of
        mind about the disclaimer is visible as a change rather than as a
        silently different render of the same COA.
        """
        self.report_disclaimer_required = bool(self.deviation_reasons) and self.customer_authorised_despite_deviation
        if not self.report_disclaimer_required:
            self.disclaimer_text = ""
        super().save(*args, **kwargs)


class SampleCodeSequence(models.Model):
    """
    The counter behind apps.samples.identity.allocate_sample_code.

    A table rather than a Postgres sequence, because a sequence gives no
    way to restart per month without creating one object per month per
    service line, and because a row can be locked: allocation takes
    SELECT ... FOR UPDATE on exactly the (prefix, period) being drawn from,
    which is what makes two clerks booking in the same delivery get two
    different codes instead of one collision.

    Not customer-visible and carries no customer data, so no RLS policy --
    unlike `sample_receipt`, which gets one in migration 0007.
    """

    id = models.BigAutoField(primary_key=True)
    prefix = models.CharField(max_length=8, help_text="Service-line prefix, e.g. 'WE'.")
    period = models.CharField(max_length=6, help_text="Allocation month as YYYYMM.")
    last_number = models.PositiveIntegerField(default=0, help_text="Highest number issued for this prefix/period.")

    class Meta:
        db_table = "sample_code_sequence"
        ordering = ["prefix", "period"]
        constraints = [
            models.UniqueConstraint(fields=["prefix", "period"], name="sample_code_sequence_unique_period"),
        ]

    def __str__(self):
        return f"{self.prefix}-{self.period}: {self.last_number} issued"
