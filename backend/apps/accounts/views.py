"""
Read-only support endpoints for identity resources (Blueprint Section 6:
Auth resource group). Staff/customer registration and Entra ID callback
handling are not yet wired (README "Known gaps") — these viewsets expose
the already-migrated Role/StaffUser/CustomerUser/ESignature data so the
core C-1 to C-6 endpoints (samples/testing/review/reporting) have something
to reference (e.g. "who is this StaffUser") while auth is built out.
"""

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.accounts.models import CustomerUser, ESignature, Role, StaffUser
from apps.accounts.serializers import (
    CustomerUserSerializer,
    ESignatureSerializer,
    RoleSerializer,
    StaffUserSerializer,
)


class RoleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated]


class StaffUserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StaffUser.objects.all()
    serializer_class = StaffUserSerializer
    permission_classes = [IsAuthenticated]


class CustomerUserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Staff-facing read access only. Customer self-service (view/edit own
    profile) belongs behind the customer auth backend, not this router
    (Blueprint Section 2.1 item 7: segregated identity domains).
    """

    queryset = CustomerUser.objects.all()
    serializer_class = CustomerUserSerializer
    permission_classes = [IsAuthenticated]


class ESignatureViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ESignature.objects.all()
    serializer_class = ESignatureSerializer
    permission_classes = [IsAuthenticated]
