"""
Read-only listing for ReviewAction/ApprovalAction. Creation is intentionally
not exposed here: it happens exclusively through SampleViewSet's
review/approve/reject actions (apps/samples/views.py), so the
segregation-of-duties guard, e-signature capture, and the Sample FSM
transition always happen together and can't drift out of sync via a second
write path.
"""

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.review.models import ApprovalAction, ReviewAction
from apps.review.serializers import ApprovalActionSerializer, ReviewActionSerializer


class ReviewActionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ReviewAction.objects.select_related("reviewer")
    serializer_class = ReviewActionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        sample_id = self.request.query_params.get("sample")
        if sample_id:
            qs = qs.filter(sample_id=sample_id)
        return qs


class ApprovalActionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ApprovalAction.objects.select_related("approver")
    serializer_class = ApprovalActionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        sample_id = self.request.query_params.get("sample")
        if sample_id:
            qs = qs.filter(sample_id=sample_id)
        return qs
