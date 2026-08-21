"""
Investigation/CAPA endpoints (Blueprint Section 6, E-9; FR-E9-01). Write
access restricted to QA Officer / Lab Supervisor, matching the Blueprint
Section 6 API table's auth scope for "POST /investigations, PATCH
/investigations/{id}"; read is open to any authenticated staff.
"""

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.accounts.permissions import roles_required
from apps.common.params import int_param
from apps.investigations.models import Investigation
from apps.investigations.serializers import InvestigationSerializer

RoleName = Role.RoleName
INVESTIGATION_WRITE_ROLES = (RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR)


class InvestigationViewSet(viewsets.ModelViewSet):
    queryset = Investigation.objects.select_related("opened_by", "related_test_result", "related_sample")
    serializer_class = InvestigationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        ?status= (comma-separated), ?related_sample=, ?related_test_result= --
        same class of gap SampleViewSet/TestRequestViewSet had before their
        own filters were added: DRF ignores unrecognized query params rather
        than erroring, so without this override none of these did anything
        server-side. Needed by the Staff Console's Investigations list and
        by the "does this sample/result already have an investigation"
        checks on the Sample/Test Request detail pages.
        """
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__in=status_param.split(","))
        related_sample = int_param(self.request.query_params.get("related_sample"), "related_sample")
        if related_sample is not None:
            qs = qs.filter(related_sample_id=related_sample)
        related_test_result = int_param(self.request.query_params.get("related_test_result"), "related_test_result")
        if related_test_result is not None:
            qs = qs.filter(related_test_result_id=related_test_result)
        return qs

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy", "close"):
            return [IsAuthenticated(), roles_required(*INVESTIGATION_WRITE_ROLES)()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(opened_by=self.request.user)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """POST /investigations/{id}/close/ -- the only path to Status.CLOSED, always sets closed_at atomically."""
        investigation = self.get_object()
        if investigation.status == Investigation.Status.CLOSED:
            raise ValidationError("Investigation is already closed.")
        investigation.status = Investigation.Status.CLOSED
        investigation.closed_at = timezone.now()
        investigation.save(update_fields=["status", "closed_at"])
        return Response(InvestigationSerializer(investigation).data)
