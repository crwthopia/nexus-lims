"""
Testing entities (Blueprint Section 3.2, C-3). TestMethod is defined here
first since accounts.StaffUser.instrument_certifications M2M's to it.
"""

from django.db import models
from django_fsm import FSMField, FSMModelMixin, transition
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user


class TestMethod(models.Model):
    """Blueprint Section 3.2: master data (D-1-5)."""

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    method_reference = models.CharField(
        max_length=255,
        help_text="Internal SOP code or ASTM/APHA/EPA reference used by NASAT's accredited methods.",
    )
    specification_limits = models.JSONField(default=dict, blank=True)
    holding_time = models.DurationField(null=True, blank=True)
    active_sop_version = models.ForeignKey(
        "documents.DocumentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "test_method"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.method_reference})"


class TestRequest(FSMModelMixin, models.Model):
    """
    Blueprint Section 3.2. status mirrors the relevant slice of Sample.status
    for the specific test (a Sample may have multiple TestRequests against
    different TestMethods running independently).

    FSMModelMixin: see apps.samples.models.Sample -- same protected=True
    refresh_from_db() footgun, same fix.
    """

    class Status(models.TextChoices):
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In Progress"
        AWAITING_REVIEW = "awaiting_review", "Awaiting Review"
        UNDER_INVESTIGATION = "under_investigation", "Under Investigation"
        RETEST_PENDING = "retest_pending", "Retest Pending"
        COMPLETED = "completed", "Completed"

    id = models.BigAutoField(primary_key=True)
    sample = models.ForeignKey("samples.Sample", on_delete=models.CASCADE, related_name="test_requests")
    test_method = models.ForeignKey(TestMethod, on_delete=models.PROTECT, related_name="test_requests")
    status = FSMField(max_length=32, choices=Status.choices, default=Status.ASSIGNED, protected=True)
    assigned_analyst = models.ForeignKey(
        "accounts.StaffUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_test_requests",
    )
    assigned_instrument = models.ForeignKey(
        "equipment.Instrument", null=True, blank=True, on_delete=models.SET_NULL, related_name="test_requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "test_request"
        indexes = [models.Index(fields=["status"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"TestRequest #{self.id} ({self.test_method.name})"

    @transition(field=status, source=Status.ASSIGNED, target=Status.IN_PROGRESS)
    def start(self):
        """FR-C3-05."""

    @transition(field=status, source=Status.IN_PROGRESS, target=Status.AWAITING_REVIEW)
    def submit_for_review(self):
        """FR-C4-04."""

    @transition(field=status, source=Status.AWAITING_REVIEW, target=Status.UNDER_INVESTIGATION)
    def flag_nonconforming(self):
        """ISO/IEC 17025:2017 7.10, mirrors Sample.reject (Blueprint Section 2.1 item 3a)."""

    @transition(field=status, source=Status.UNDER_INVESTIGATION, target=Status.RETEST_PENDING)
    def authorize_retest(self):
        """QA Officer / Lab Supervisor role only."""

    @transition(field=status, source=Status.RETEST_PENDING, target=Status.IN_PROGRESS)
    def resume_testing(self):
        """FR-C3-05: retest or resample decision loop."""

    @transition(field=status, source=Status.AWAITING_REVIEW, target=Status.COMPLETED)
    def complete(self):
        """Terminal state once ReviewAction and ApprovalAction both pass."""


class TestResult(models.Model):
    """Blueprint Section 3.2. data_type mirrors the dynamic Test Result Entry screen (Section 5.1)."""

    class DataType(models.TextChoices):
        FLOAT = "float", "Float"
        INT = "int", "Integer"
        TEXT = "text", "Text"
        DATE = "date", "Date"
        LIST = "list", "List"
        FILE = "file", "File"
        CALCULATED = "calculated", "Calculated"
        BOOLEAN = "boolean", "Boolean"
        INTERVAL = "interval", "Interval"

    id = models.BigAutoField(primary_key=True)
    test_request = models.ForeignKey(TestRequest, on_delete=models.CASCADE, related_name="results")
    data_type = models.CharField(max_length=16, choices=DataType.choices)
    value = models.TextField(help_text="Stored as text; interpreted per data_type at the serializer layer.")
    unit = models.CharField(max_length=32, blank=True)
    entered_by = models.ForeignKey("accounts.StaffUser", on_delete=models.PROTECT, related_name="entered_test_results")
    entered_at = models.DateTimeField(auto_now_add=True)
    is_out_of_spec = models.BooleanField(default=False, help_text="FR-C3-08, FR-C4-05 OOS auto-flag.")
    instrument = models.ForeignKey(
        "equipment.Instrument", null=True, blank=True, on_delete=models.SET_NULL, related_name="test_results",
    )
    standard_reagents = models.ManyToManyField(
        "equipment.StandardReagent", blank=True, related_name="test_results",
        help_text="Pre-filtered to active, non-expired items only at entry time (FR-C3-02).",
    )
    raw_file_id = models.CharField(
        max_length=512, null=True, blank=True,
        help_text="Alibaba Cloud OSS object key for the raw instrument export this result was parsed from (ALCOA traceability, Section 7.3).",
    )
    raw_file_checksum_sha256 = models.CharField(max_length=64, null=True, blank=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "test_result"
        indexes = [models.Index(fields=["is_out_of_spec"])]
        ordering = ["-entered_at"]

    def __str__(self):
        return f"TestResult #{self.id} = {self.value} {self.unit}".strip()
