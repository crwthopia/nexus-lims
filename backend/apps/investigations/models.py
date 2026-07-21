"""
Investigation / CAPA entity (Blueprint Section 3.4, E-9).
Opened per ISO/IEC 17025:2017 7.10 Nonconforming Work when a TestResult is
flagged OOS/OOT, or when an Approver rejects a Sample into under_investigation
(Blueprint Section 2.1 item 3a, closes Section 13 gap 12).
"""

from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user


class Investigation(models.Model):
    class InvestigationType(models.TextChoices):
        OOS = "oos", "Out of Specification"
        OOT = "oot", "Out of Trend"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ROOT_CAUSE_IDENTIFIED = "root_cause_identified", "Root Cause Identified"
        CAPA_IN_PROGRESS = "capa_in_progress", "CAPA In Progress"
        CLOSED = "closed", "Closed"

    id = models.BigAutoField(primary_key=True)
    related_test_result = models.ForeignKey(
        "testing.TestResult", null=True, blank=True, on_delete=models.SET_NULL, related_name="investigations",
    )
    related_sample = models.ForeignKey(
        "samples.Sample", null=True, blank=True, on_delete=models.SET_NULL, related_name="investigations",
        help_text="Populated when the investigation originates from an Approver rejection rather than an OOS TestResult.",
    )
    type = models.CharField(max_length=8, choices=InvestigationType.choices)
    opened_by = models.ForeignKey("accounts.StaffUser", on_delete=models.PROTECT, related_name="opened_investigations")
    root_cause = models.TextField(blank=True)
    capa_actions = models.TextField(blank=True, help_text="Corrective and Preventive Action description.")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "investigation"
        indexes = [models.Index(fields=["status"])]
        ordering = ["-opened_at"]

    def __str__(self):
        return f"Investigation #{self.id} ({self.get_type_display()}, {self.get_status_display()})"
