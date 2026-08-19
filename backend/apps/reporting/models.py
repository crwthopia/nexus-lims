"""
Reporting entities (Blueprint Section 3.2 C-6, Section 2.1a).

Report itself is a thin metadata/pointer model; the actual PDF assembly
happens in the decoupled WeasyPrint template pipeline described in
Blueprint Section 2.1a (HTML/Jinja2 templates outside application code,
selected by report_type). This app's templates/ directory (per Section 10
repository scaffold) is where NASAT QA authors/revises those templates.
"""

from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user


class Report(models.Model):
    """
    Blueprint Section 3.2 (C-6). report_type selects which Jinja2/HTML
    template the WeasyPrint pipeline renders against (Blueprint Section
    2.1a): failure_analysis_coa, water_environmental_coa (production
    template now sourced from Job Order LABW2410-238, closes Section 13
    gap 6), or training_cpd_certificate.
    """

    class Status(models.TextChoices):
        """
        Generation-job status, not a business workflow -- deliberately a plain
        CharField rather than a django-fsm FSMField like Sample/TestRequest.
        Those four model regulated processes where each transition has a role
        gate and an audit consequence; this one is moved only by the Celery
        worker, has no operator-facing transitions, and gating it would mean
        the worker needed a role to do its job.
        """

        PENDING = "pending", "Pending"
        GENERATING = "generating", "Generating"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    class ReportType(models.TextChoices):
        FAILURE_ANALYSIS_COA = "failure_analysis_coa", "Failure Analysis COA"
        WATER_ENVIRONMENTAL_COA = "water_environmental_coa", "Water/Environmental COA (DOH/DENR)"
        TRAINING_CPD_CERTIFICATE = "training_cpd_certificate", "Training CPD Certificate"
        CUSTOM = "custom", "Custom / Other"

    id = models.BigAutoField(primary_key=True)
    sample = models.ForeignKey(
        "samples.Sample", null=True, blank=True, on_delete=models.PROTECT, related_name="reports",
    )
    order = models.ForeignKey(
        "samples.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="reports",
    )
    report_type = models.CharField(max_length=32, choices=ReportType.choices)
    # Written by apps/reporting/tasks.generate_report_pdf, never by the client:
    # a caller-supplied key could point at any object in the bucket, including
    # another customer's report. Blank until the render succeeds.
    file_id = models.CharField(
        max_length=512, blank=True, default="",
        help_text="Alibaba Cloud OSS object key for the generated PDF. Set by the generation task.",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    # Operator-facing reason a render failed, so a failure is diagnosable from
    # the Reports screen without reading worker logs.
    failure_reason = models.TextField(blank=True, default="")
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey("accounts.StaffUser", on_delete=models.PROTECT, related_name="generated_reports")
    version = models.PositiveIntegerField(default=1)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "report"
        constraints = [
            models.CheckConstraint(
                check=models.Q(sample__isnull=False) | models.Q(order__isnull=False),
                name="report_target_required",
            )
        ]
        indexes = [models.Index(fields=["report_type"]), models.Index(fields=["status"])]
        ordering = ["-generated_at"]

    def __str__(self):
        return f"Report #{self.id} ({self.get_report_type_display()}) v{self.version}"
