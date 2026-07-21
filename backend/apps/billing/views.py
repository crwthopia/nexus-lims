"""
Invoice/Payment endpoints (Blueprint Section 6: Billing resource group,
Section 3.7 manual payment reconciliation). No dedicated "billing" role
exists in the RBAC model (Blueprint Section 7.1's 10 named roles); Training
Coordinator and Lab Supervisor are the closest fits per Blueprint Section
5.1 ("Training Coordinator or billing-role staff"), so BILLING_WRITE_ROLES
uses those plus System Administrator.
"""

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.authentication import CustomerSessionAuthentication
from apps.accounts.models import Role
from apps.accounts.permissions import IsCustomerAuthenticated, roles_required
from apps.billing.models import Invoice, Payment
from apps.billing.serializers import InvoiceDetailSerializer, InvoiceSerializer, PaymentSerializer

RoleName = Role.RoleName
BILLING_WRITE_ROLES = (RoleName.TRAINING_COORDINATOR, RoleName.LAB_SUPERVISOR, RoleName.SYSTEM_ADMINISTRATOR)


class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = Invoice.objects.select_related("order", "enrollment").prefetch_related("payments")
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return InvoiceDetailSerializer
        return InvoiceSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), roles_required(*BILLING_WRITE_ROLES)()]
        return [IsAuthenticated()]

    @action(detail=True, methods=["get", "post"])
    def payments(self, request, pk=None):
        """
        GET/POST /invoices/{id}/payments/ -- Blueprint Section 6's exact
        endpoint. GET is open to any authenticated staff (viewing payment
        history); POST (recording a payment) is checked manually here
        against BILLING_WRITE_ROLES rather than in get_permissions(), since
        this one action needs a different rule per HTTP method.
        """
        invoice = self.get_object()

        if request.method == "GET":
            return Response(PaymentSerializer(invoice.payments.all(), many=True).data)

        if not (request.user.is_superuser or request.user.roles.filter(name__in=BILLING_WRITE_ROLES).exists()):
            raise PermissionDenied(
                "Recording a payment requires the Training Coordinator, Lab Supervisor, "
                "or System Administrator role."
            )

        serializer = PaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = serializer.save(invoice=invoice, recorded_by=request.user)

        if payment.status == Payment.Status.CONFIRMED and invoice.status != Invoice.Status.VOID:
            # Payment has no per-payment amount field in the current schema
            # (apps/billing/models.py) -- a single confirmed payment is
            # treated as paying the invoice in full, the same documented
            # limitation as apps/training/tasks.py's _amount_paid.
            invoice.status = Invoice.Status.PAID
            invoice.save(update_fields=["status"])

        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only top-level listing; creation only via InvoiceViewSet.payments (one write path, see above)."""

    queryset = Payment.objects.select_related("invoice", "recorded_by")
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]


class CustomerInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /my/invoices/ -- Blueprint Section 6: "Customer (view own invoice)"."""

    serializer_class = InvoiceSerializer
    authentication_classes = [CustomerSessionAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get_queryset(self):
        return Invoice.objects.filter(
            Q(order__customer=self.request.user) | Q(enrollment__customer=self.request.user)
        )
