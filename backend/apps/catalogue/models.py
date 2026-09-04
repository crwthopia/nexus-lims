"""
The service catalogue: what the lab sells, and for how much.

Nothing in the schema priced analytical work before this. `TrainingCourse`
carries a price because a course is sold as a course, but a Sample arrives
against a `TestMethod`, and a TestMethod is a *method* -- an SOP reference
and its specification limits -- not a line on a rate card. `Invoice.amount`
was a single figure typed in by staff, with nothing recording what it was
for. That is why "which analyses earn the most" could not be answered from
this database at all, and why the catalogue comes before the dashboard.

Two entities, deliberately kept apart:

  - `ServiceOffering` is the thing a customer buys: a named analysis or
    panel, in one service line, mapped to the TestMethod(s) that fulfil it.
  - `OfferingPrice` is what it cost during a stated period. Prices are
    versioned rather than edited, because an invoice raised in March must
    keep quoting March's rate however many times the rate card changes
    afterwards -- and because "what did we charge last year" is a question
    a lab gets asked by its own auditors.

VAT is a property of the price, not of the catalogue, because NASAT quotes
both ways: some rates are published VAT-exclusive (net, VAT added at
invoicing) and some VAT-inclusive (what the customer pays, VAT backed out
for reporting). Storing the treatment alongside the figure is the only way
a total can be computed without someone remembering which kind this one
was. Every price exposes all three numbers -- net, VAT, gross -- so no
caller has to do that arithmetic, or get it wrong.
"""

from decimal import Decimal

from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user
from apps.catalogue.money import split
from apps.samples.models import ServiceLine

# Training is a service line, but its catalogue is `training.TrainingCourse`
# and always was: a course carries CPD units, an early-bird and a student
# discount, and sells through sessions with capacity. Duplicating it here
# would create a second price for the same thing, and one of the two would
# be wrong within a month. The catalogue covers the analytical service
# lines only, and the constraint below is what keeps that true.
CATALOGUE_SERVICE_LINES = [ServiceLine.FAILURE_ANALYSIS, ServiceLine.WATER_ENVIRONMENTAL]


class ServiceOffering(models.Model):
    """
    One sellable line of the rate card.

    `test_methods` is many-to-many rather than a single FK because a good
    part of any water lab's revenue is panels: "Potability (Drinking Water)"
    is one price and one turnaround to the customer, and six TestMethods to
    the lab. Modelling it as a set means one order line can later raise the
    six TestRequests that fulfil it, and means the dashboard can attribute
    those six back to the one thing that was actually sold.

    `code` is the identifier staff and customers quote at each other on a
    quotation or a purchase order, so it is the natural key here -- not the
    surrogate id, which appears on nothing anyone reads.
    """

    id = models.BigAutoField(primary_key=True)
    code = models.CharField(
        max_length=32, unique=True,
        help_text="Rate-card code, as it appears on a quotation (e.g. 'WQ-BOD5'). Unique.",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    service_line = models.CharField(max_length=32, choices=ServiceLine.choices)
    test_methods = models.ManyToManyField(
        "testing.TestMethod", blank=True, related_name="offerings",
        help_text="The method(s) that fulfil this offering. More than one for a panel; none for an offering not yet mapped to its methods.",
    )
    turnaround_days = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Standard turnaround quoted to the customer, in working days. Null where it depends on the sample.",
    )
    is_accredited = models.BooleanField(
        default=False,
        help_text="Within NASAT's ISO/IEC 17025 scope of accreditation. Affects what a report may claim, so it is stated per offering rather than assumed.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Withdrawn offerings stay in the catalogue rather than being deleted: past orders reference them, and 'what did we stop selling' is itself a question.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "service_offering"
        ordering = ["code"]
        indexes = [models.Index(fields=["service_line", "is_active"])]
        constraints = [
            models.CheckConstraint(
                check=models.Q(service_line__in=[line.value for line in CATALOGUE_SERVICE_LINES]),
                name="service_offering_analytical_service_line",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"

    def price_on(self, on_date):
        """
        The price in force on `on_date`, or None if the offering wasn't
        priced then. Reads from prefetched `prices` when there is one, so
        listing a catalogue with its current prices stays one extra query
        rather than one per row.
        """
        for price in self.prices.all():
            if price.effective_from <= on_date and (price.effective_to is None or on_date <= price.effective_to):
                return price
        return None


class OfferingPrice(models.Model):
    """
    What an offering cost over a stated period.

    Superseding rather than editing is enforced by how prices are written
    (`services.set_price`), not merely by convention: a new price closes the
    previous one the day before it starts, so the windows never overlap and
    every date has exactly one answer.
    """

    class VatTreatment(models.TextChoices):
        EXCLUSIVE = "exclusive", "VAT-exclusive (net)"
        INCLUSIVE = "inclusive", "VAT-inclusive (gross)"

    id = models.BigAutoField(primary_key=True)
    offering = models.ForeignKey(ServiceOffering, on_delete=models.CASCADE, related_name="prices")
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="The figure as published. Whether it includes VAT is stated by vat_treatment, not inferred.",
    )
    currency = models.CharField(max_length=3, default="PHP")
    vat_treatment = models.CharField(max_length=16, choices=VatTreatment.choices, default=VatTreatment.EXCLUSIVE)
    vat_rate_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("12.00"),
        help_text="Philippine VAT is 12%. Stored per price so a zero-rated or exempt service is a value here, not a special case in code.",
    )
    effective_from = models.DateField()
    effective_to = models.DateField(
        null=True, blank=True,
        help_text="Inclusive last day this price applied. Null means it is the current price.",
    )
    note = models.CharField(max_length=255, blank=True, help_text="Why this price exists — '2026 rate card', say.")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "accounts.StaffUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "offering_price"
        # Newest first: the current price is the first row, which is what
        # both the serializer and price_on() want most of the time.
        ordering = ["-effective_from", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["offering", "effective_from"], name="offering_price_one_per_start_date"),
            models.CheckConstraint(check=models.Q(amount__gte=0), name="offering_price_amount_not_negative"),
            models.CheckConstraint(check=models.Q(vat_rate_pct__gte=0), name="offering_price_vat_rate_not_negative"),
            models.CheckConstraint(
                check=models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=models.F("effective_from")),
                name="offering_price_window_not_backwards",
            ),
        ]

    def __str__(self):
        return f"{self.offering.code}: {self.amount} {self.currency} from {self.effective_from}"

    @property
    def is_current(self):
        return self.effective_to is None

    # --- the three figures every caller actually wants ---------------------
    #
    # Computed rather than stored: a stored net/VAT/gross triple can drift
    # out of agreement with the amount it was derived from, and there is no
    # way to tell afterwards which of the four was the one someone meant.
    # The arithmetic itself lives in catalogue/money.py, shared with the
    # order and invoice lines that copy these figures.

    @property
    def net_amount(self) -> Decimal:
        return split(self.amount, self.vat_treatment, self.vat_rate_pct)[0]

    @property
    def vat_amount(self) -> Decimal:
        return split(self.amount, self.vat_treatment, self.vat_rate_pct)[1]

    @property
    def gross_amount(self) -> Decimal:
        return split(self.amount, self.vat_treatment, self.vat_rate_pct)[2]
