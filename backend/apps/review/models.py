"""
Review / Approval entities (Blueprint Section 3.2, C-4/C-5).

Segregation-of-duties guard (Blueprint Section 2.1 item 3a, closes Section
13 gap 2) is enforced in apps.review.services.can_approve(), not as a
database constraint, since the rule is data-driven off Sample.service_line
and must be evaluated at the point ApprovalAction is created:
  - service_line == water_environmental: approver_id must differ from the
    ReviewAction.reviewer_id on the same Sample (hard split).
  - service_line == failure_analysis: self-approve bypass permitted.
"""

from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user


class ReviewAction(models.Model):
    """Blueprint Section 3.2."""

    class Action(models.TextChoices):
        REVIEWED = "reviewed", "Reviewed"
        FLAGGED = "flagged", "Flagged"
        RETURNED = "returned", "Returned"

    id = models.BigAutoField(primary_key=True)
    test_result = models.ForeignKey(
        "testing.TestResult", null=True, blank=True, on_delete=models.CASCADE, related_name="review_actions",
    )
    sample = models.ForeignKey(
        "samples.Sample", null=True, blank=True, on_delete=models.CASCADE, related_name="review_actions",
    )
    reviewer = models.ForeignKey("accounts.StaffUser", on_delete=models.PROTECT, related_name="review_actions")
    action = models.CharField(max_length=16, choices=Action.choices)
    comments = models.TextField(blank=True)
    e_signature = models.ForeignKey(
        "accounts.ESignature", null=True, blank=True, on_delete=models.SET_NULL, related_name="review_actions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "review_action"
        constraints = [
            models.CheckConstraint(
                check=models.Q(test_result__isnull=False) | models.Q(sample__isnull=False),
                name="review_action_target_required",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"ReviewAction #{self.id}: {self.get_action_display()} by {self.reviewer}"


class ApprovalAction(models.Model):
    """
    Blueprint Section 3.2. disposition mirrors Sample.status transitions
    (approve -> Sample.approve(); reject -> Sample.reject() into
    under_investigation, per ISO/IEC 17025:2017 7.10, Section 13 gap 12).
    """

    class Disposition(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.BigAutoField(primary_key=True)
    sample = models.ForeignKey("samples.Sample", on_delete=models.CASCADE, related_name="approval_actions")
    approver = models.ForeignKey("accounts.StaffUser", on_delete=models.PROTECT, related_name="approval_actions")
    disposition = models.CharField(max_length=16, choices=Disposition.choices)
    e_signature = models.ForeignKey(
        "accounts.ESignature", null=True, blank=True, on_delete=models.SET_NULL, related_name="approval_actions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "approval_action"
        ordering = ["-created_at"]

    def __str__(self):
        return f"ApprovalAction #{self.id}: {self.get_disposition_display()} by {self.approver}"
