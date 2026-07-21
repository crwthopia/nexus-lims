"""
Training entities (Blueprint Section 3.6), mapped to NASAT catalog's
Technical Trainings and Workshops (CPD-accredited).

Encodes the fully RESOLVED Section 13 gap 7 decisions:
  - discounts are non-stackable, with a manual discount_override escape hatch
  - cancellations use a `rescheduled` Enrollment state, not a refund
  - CPD reporting is satisfied by a generic Attendee Export CSV feature
    (TrainingCoordinatorExport is implemented as a service/view, not a
    model, per Blueprint Section 5.1; no new table needed since it reads
    Enrollment + CustomerUser + TrainingCourse directly)
  - session capacity/cancellation policy: min_capacity,
    cancellation_threshold_days, automatic pending_reschedule transition,
    CreditNote issuance
"""

from django.db import models
from django_fsm import FSMField, transition
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user


class TrainingCourse(models.Model):
    """Blueprint Section 3.6."""

    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    cpd_units = models.DecimalField(max_digits=5, decimal_places=2, help_text="Per NASAT's CPD-accredited trainings.")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    early_bird_discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=20.00)
    student_discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=20.00)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "training_course"
        ordering = ["title"]

    def __str__(self):
        return self.title


class TrainingSession(models.Model):
    """
    Blueprint Section 3.6. min_capacity and cancellation_threshold_days
    (added per NASAT architectural review, closes the remainder of Section
    13 gap 7) drive the automated Celery beat capacity check described in
    Blueprint Section 3.6 / 4.3: if confirmed Enrollment count is below
    min_capacity at cancellation_threshold_days before start_date, status
    auto-transitions to pending_reschedule.
    """

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        PENDING_RESCHEDULE = "pending_reschedule", "Pending Reschedule"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.BigAutoField(primary_key=True)
    course = models.ForeignKey(TrainingCourse, on_delete=models.PROTECT, related_name="sessions")
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    capacity = models.PositiveIntegerField(help_text="Maximum enrollments accepted.")
    min_capacity = models.PositiveIntegerField(
        help_text="Minimum confirmed enrollments required by cancellation_threshold_days before start_date, or the session auto-transitions to pending_reschedule (ISO/IEC 17025:2017 6.2.2).",
    )
    cancellation_threshold_days = models.PositiveIntegerField(
        help_text="Days before start_date at which the Celery beat min_capacity check runs.",
    )
    instructor = models.ForeignKey(
        "accounts.StaffUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="instructed_sessions",
    )
    status = FSMField(max_length=32, choices=Status.choices, default=Status.SCHEDULED, protected=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "training_session"
        indexes = [models.Index(fields=["status", "start_date"])]
        ordering = ["start_date"]

    def __str__(self):
        return f"{self.course.title} @ {self.start_date:%Y-%m-%d}"

    @transition(field=status, source=Status.SCHEDULED, target=Status.PENDING_RESCHEDULE)
    def flag_below_min_capacity(self):
        """
        Fired by the Celery beat capacity-check task (Blueprint Section
        3.6/4.3) when confirmed Enrollment count < min_capacity at
        cancellation_threshold_days before start_date. Triggers the
        automated customer email and CreditNote issuance at the call site.
        """

    @transition(field=status, source=Status.SCHEDULED, target=Status.IN_PROGRESS)
    def start_session(self):
        pass

    @transition(field=status, source=Status.IN_PROGRESS, target=Status.COMPLETED)
    def complete_session(self):
        pass

    @transition(field=status, source=[Status.SCHEDULED, Status.PENDING_RESCHEDULE], target=Status.CANCELLED)
    def cancel_session(self):
        pass


class Enrollment(models.Model):
    """
    Blueprint Section 3.6. `rescheduled` replaces any refund-style workflow
    (Section 13 gap 7, RESOLVED): funds stay tied to the customer's account
    via a CreditNote rather than a cash/bank refund.
    """

    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        RESCHEDULED = "rescheduled", "Rescheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        PAID = "paid", "Paid"

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(TrainingSession, on_delete=models.PROTECT, related_name="enrollments")
    customer = models.ForeignKey("accounts.CustomerUser", on_delete=models.PROTECT, related_name="enrollments")
    payment_status = models.CharField(max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    discount_applied = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="System-calculated: the single highest valid discount (early-bird vs student), never stacked.",
    )
    discount_override = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Admin/Training Coordinator-set manual discount, e.g. negotiated corporate rate. Overrides discount_applied when set.",
    )
    certificate_issued = models.BooleanField(default=False)
    status = FSMField(max_length=16, choices=Status.choices, default=Status.CONFIRMED, protected=True)
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "enrollment"
        indexes = [models.Index(fields=["status"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Enrollment #{self.id}: {self.customer.email} -> {self.session}"

    @transition(field=status, source=Status.CONFIRMED, target=Status.RESCHEDULED)
    def reschedule(self):
        """
        Fired either by direct customer/staff cancellation request, or
        automatically alongside TrainingSession.flag_below_min_capacity
        for every affected Enrollment (Blueprint Section 3.6).
        """

    @transition(field=status, source=Status.CONFIRMED, target=Status.COMPLETED)
    def mark_completed(self):
        """Training Coordinator marks attendance/completion (Section 4.3)."""

    @transition(field=status, source=[Status.CONFIRMED, Status.RESCHEDULED], target=Status.CANCELLED)
    def cancel(self):
        pass


class CreditNote(models.Model):
    """
    Blueprint Section 3.6 (added per NASAT architectural review, closes the
    remainder of Section 13 gap 7). Issued when an Enrollment's session is
    rescheduled due to under-capacity, keeping funds tied to the customer's
    account rather than a cash/bank refund. Redeemable against the
    rescheduled session or any other future TrainingSession (Section 5.2).
    """

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        APPLIED = "applied", "Applied"
        EXPIRED = "expired", "Expired"

    id = models.BigAutoField(primary_key=True)
    customer = models.ForeignKey("accounts.CustomerUser", on_delete=models.PROTECT, related_name="credit_notes")
    source_enrollment = models.ForeignKey(
        Enrollment, on_delete=models.PROTECT, related_name="credit_notes_issued",
        help_text="The rescheduled Enrollment that generated this credit.",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.AVAILABLE)
    applied_to_enrollment = models.ForeignKey(
        Enrollment, null=True, blank=True, on_delete=models.SET_NULL, related_name="credit_notes_applied",
        help_text="Set once the customer redeems this credit against a new Enrollment.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "credit_note"
        indexes = [models.Index(fields=["status"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"CreditNote #{self.id}: {self.amount} for {self.customer.email} ({self.get_status_display()})"
