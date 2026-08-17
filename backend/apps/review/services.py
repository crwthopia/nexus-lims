"""
Segregation-of-duties guard for ApprovalAction (Blueprint Section 2.1 item
3a, closes Section 13 gap 2; grounded in ASTM E1578-18 6.6.1). Lives outside
Sample.approve()'s @transition body because it needs request-time context
(which staff member is acting as Approver) that a pure django-fsm-2 condition
cannot see — it is evaluated by the view before calling sample.approve().
"""

from django.db.models import Q

from apps.samples.models import ServiceLine


class SegregationOfDutiesError(Exception):
    """Raised when an Approver may not approve a sample per the service-line rule below."""


def check_can_approve(sample, approver):
    """
    water_environmental (regulated): approver must differ from every
    ReviewAction.reviewer recorded against this sample — hard split, no
    override.
    failure_analysis / training (non-regulated): self-approve bypass
    permitted, so this is a no-op.
    """
    if sample.service_line != ServiceLine.WATER_ENVIRONMENTAL:
        return

    from apps.review.models import ReviewAction  # local import avoids a review<->samples import cycle

    reviewer_ids = ReviewAction.objects.filter(
        Q(sample=sample) | Q(test_result__test_request__sample=sample)
    ).values_list("reviewer_id", flat=True)

    if approver.id in reviewer_ids:
        raise SegregationOfDutiesError(
            "Water/Environmental Testing is a regulated service line: the Approver must be "
            "a different person from the Reviewer who reviewed this sample (ASTM E1578-18 6.6.1)."
        )
