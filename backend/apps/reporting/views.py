"""
Report endpoint (Blueprint Section 6: Reports resource group). Create/list/
retrieve only — no update/destroy, since a Report is immutable once
generated (FR-E17-01/FR-E17-03); a corrected report is a new Report row
with an incremented `version`, not an edit of an existing one.
"""

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.reporting.models import Report
from apps.reporting.serializers import ReportSerializer


class ReportViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = Report.objects.select_related("sample", "order", "generated_by")
    serializer_class = ReportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        sample_id = self.request.query_params.get("sample")
        if sample_id:
            qs = qs.filter(sample_id=sample_id)
        return qs
