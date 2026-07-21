"""
Document Management entities (Blueprint Section 3.5, D-1).

Built early in dependency order since CustomerUser.school_id_document
(accounts app) and Report.file_id (samples app) reference Document.
"""

from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user


class Document(models.Model):
    """Blueprint Section 3.5: SOP/manual browser root entity (D-1)."""

    class DocumentType(models.TextChoices):
        SOP = "sop", "SOP"
        MANUAL = "manual", "Manual"
        FORM = "form", "Form"
        TRAINING_MATERIAL = "training_material", "Training Material"
        UPLOADED_SUPPORTING_FILE = "uploaded_supporting_file", "Uploaded Supporting File"

    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=255)
    type = models.CharField(max_length=32, choices=DocumentType.choices)
    current_version = models.ForeignKey(
        "DocumentVersion", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "document"
        ordering = ["title"]

    def __str__(self):
        return self.title


class DocumentVersion(models.Model):
    """Blueprint Section 3.5: version history, edit/approve restricted to QA Officer/Lab Supervisor (Section 5.1)."""

    id = models.BigAutoField(primary_key=True)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()
    file_id = models.CharField(max_length=512, help_text="Alibaba Cloud OSS object key (Blueprint Section 2.2).")
    approved_by = models.ForeignKey(
        "accounts.StaffUser", null=True, blank=True, on_delete=models.PROTECT, related_name="approved_document_versions",
    )
    effective_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "document_version"
        unique_together = [("document", "version_number")]
        ordering = ["document_id", "-version_number"]

    def __str__(self):
        return f"{self.document.title} v{self.version_number}"
