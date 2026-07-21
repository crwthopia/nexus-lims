"""
Document/DocumentVersion endpoints (Blueprint Section 6: Documents
resource group, D-1). Read access is open to any authenticated staff
member (FR-D1-02: "read-only access to current, approved SOPs... to
designated staff by role"); write access -- new documents, new versions,
approving a version to become current -- is restricted to QA Officer/Lab
Supervisor (Blueprint Section 5.1: "edit/approve restricted to QA Officer
/ Lab Supervisor").
"""

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.accounts.permissions import roles_required
from apps.documents.models import Document, DocumentVersion
from apps.documents.serializers import DocumentDetailSerializer, DocumentSerializer, DocumentVersionSerializer

RoleName = Role.RoleName
DOCUMENT_WRITE_ROLES = (RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR)


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.select_related("current_version").prefetch_related("versions")
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return DocumentDetailSerializer
        return DocumentSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), roles_required(*DOCUMENT_WRITE_ROLES)()]
        return [IsAuthenticated()]


class DocumentVersionViewSet(viewsets.ModelViewSet):
    queryset = DocumentVersion.objects.select_related("document", "approved_by")
    serializer_class = DocumentVersionSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy", "approve"):
            return [IsAuthenticated(), roles_required(*DOCUMENT_WRITE_ROLES)()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        document_id = self.request.query_params.get("document")
        if document_id:
            qs = qs.filter(document_id=document_id)
        return qs

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """
        POST /document-versions/{id}/approve/ -- FR-D1-03: designates this
        version as current, archiving (not deleting) any prior current
        version of the same document by clearing its is_current flag.
        """
        version = self.get_object()
        DocumentVersion.objects.filter(document=version.document, is_current=True).update(is_current=False)

        version.is_current = True
        version.approved_by = request.user
        if not version.effective_date:
            version.effective_date = timezone.localdate()
        version.save(update_fields=["is_current", "approved_by", "effective_date"])

        version.document.current_version = version
        version.document.save(update_fields=["current_version"])

        return Response(DocumentVersionSerializer(version).data)
