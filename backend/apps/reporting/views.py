"""
Report endpoint (Blueprint Section 6: Reports resource group). Create/list/
retrieve only — no update/destroy, since a Report is immutable once
generated (FR-E17-01/FR-E17-03); a corrected report is a new Report row
with an incremented `version`, not an edit of an existing one.

Creating one enqueues the PDF render (apps/reporting/tasks.py) and returns
immediately with status 'pending'; the document itself arrives via
GET /reports/{id}/download/ once the worker has finished.
"""

from botocore.exceptions import ClientError
from django.conf import settings
from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.authentication import CustomerSessionAuthentication
from apps.accounts.permissions import IsCustomerAuthenticated
from apps.audit.oss import OSSNotConfiguredError, presigned_url
from apps.reporting.models import Report
from apps.reporting.serializers import CustomerReportSerializer, ReportSerializer
from apps.reporting.tasks import enqueue_generation


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
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__in=status_param.split(","))
        return qs

    def perform_create(self, serializer):
        report = serializer.save()
        enqueue_generation(report)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """
        A short-lived presigned URL for the rendered PDF (Blueprint Section
        5.2), rather than streaming the file through Django -- see
        apps/audit/oss.presigned_url.

        A report that isn't ready answers 409 with its current status rather
        than 404: the report exists, it just isn't finished, and a client
        polling this endpoint needs to tell "not yet" apart from "no such
        report" to know whether to keep waiting.
        """
        report = self.get_object()

        if report.status != Report.Status.READY:
            return Response(
                {
                    "detail": f"Report is not ready for download (status '{report.status}').",
                    "status": report.status,
                    "failure_reason": report.failure_reason,
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            url = presigned_url(report.file_id)
        except (OSSNotConfiguredError, ClientError) as exc:
            # Object storage being unreachable is a server-side fault, not a
            # bad request -- surfacing it as anything else would send a client
            # off debugging its own call.
            return Response(
                {"detail": f"Could not produce a download link: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"url": url, "expires_in": settings.OSS_PRESIGNED_URL_EXPIRY_SECONDS})


class CustomerReportViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /my/reports/ — a customer's own certificates and reports.

    Scoped three ways, deliberately, because this is the first customer-facing
    endpoint over a table that used to be staff-only:

      1. `status=ready` — a customer has no use for a report that is pending,
         generating, or failed. Those are lab-internal states, and showing a
         `failed` row invites a support call about something the lab already
         knows is broken.
      2. The ORM filter below, through whichever parent the report hangs off.
      3. RLS on `report` itself (apps/reporting/migrations/0003), which holds
         at the database level even if this filter is ever dropped by a
         future change — the same defense-in-depth reasoning as
         CustomerOrderViewSet, and the reason that migration exists at all.
    """

    serializer_class = CustomerReportSerializer
    authentication_classes = [CustomerSessionAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get_queryset(self):
        customer = self.request.user
        return (
            Report.objects.filter(status=Report.Status.READY)
            .filter(
                Q(sample__order__customer=customer) | Q(order__customer=customer)
            )
            .select_related("sample", "order")
            .distinct()
        )

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """
        A presigned URL for the customer's own report.

        get_object() runs against the scoped queryset above, so a report
        belonging to somebody else is a 404 here rather than a 403 — the
        existence of another customer's report is itself information this
        endpoint should not confirm.
        """
        report = self.get_object()

        try:
            url = presigned_url(report.file_id)
        except (OSSNotConfiguredError, ClientError) as exc:
            return Response(
                {"detail": f"Could not produce a download link: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"url": url, "expires_in": settings.OSS_PRESIGNED_URL_EXPIRY_SECONDS})
