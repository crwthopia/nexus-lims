"""
Quotation endpoints, one set for each identity domain.

Staff build and issue them (`/quotations/`); the customer being quoted
reads and answers their own (`/my/quotations/`). The two are deliberately
separate viewsets over the same table rather than one with a branch, which
is the pattern every customer-facing resource here already follows -- and
the reason is the same: a single viewset that decides what to show by
inspecting `request.user` is one refactor away from showing the wrong
person the wrong offer.
"""

from decimal import Decimal, InvalidOperation

from django_fsm import TransitionNotAllowed
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.authentication import CustomerSessionAuthentication
from apps.accounts.models import Role
from apps.accounts.permissions import IsCustomerAuthenticated, roles_required
from apps.catalogue.models import ServiceOffering
from apps.common.params import body_dict, int_param
from apps.quotations import services
from apps.quotations.models import Quotation
from apps.quotations.serializers import (
    CustomerQuotationDetailSerializer,
    CustomerQuotationSerializer,
    QuotationDetailSerializer,
    QuotationItemSerializer,
    QuotationSerializer,
)

RoleName = Role.RoleName
# Quoting is commercial work: the same people who raise invoices, plus the
# receivers who take the enquiry in the first place.
QUOTATION_WRITE_ROLES = (
    RoleName.SAMPLE_RECEIVER,
    RoleName.TRAINING_COORDINATOR,
    RoleName.LAB_SUPERVISOR,
    RoleName.SYSTEM_ADMINISTRATOR,
)


def _quotation_error(exc):
    """A refusal the caller can act on is a 400 with the reason, never a 500."""
    return ValidationError({"detail": str(exc)})


class QuotationViewSet(viewsets.ModelViewSet):
    queryset = Quotation.objects.select_related("customer", "prepared_by").prefetch_related("items__offering")
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return QuotationDetailSerializer if self.action == "retrieve" else QuotationSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsAuthenticated(), roles_required(*QUOTATION_WRITE_ROLES)()]

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__in=status_param.split(","))
        customer_id = int_param(self.request.query_params.get("customer"), "customer")
        if customer_id is not None:
            qs = qs.filter(customer_id=customer_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(prepared_by=self.request.user)

    def update(self, request, *args, **kwargs):
        """
        Editing is a draft-only privilege.

        A sent quotation is a document a customer is reading; changing it
        underneath them would make "what did we quote" unanswerable. The
        supported way to change an offer is `revise`, below.
        """
        quotation = self.get_object()
        if quotation.status != Quotation.Status.DRAFT:
            raise _quotation_error(
                f"{quotation.reference} has already been {quotation.get_status_display().lower()}. "
                "Use revise/ to issue a replacement rather than editing it."
            )
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=["get", "post"], url_path="items")
    def items(self, request, pk=None):
        """GET/POST the quoted lines. The price is taken from the rate card, never from the request."""
        quotation = self.get_object()

        if request.method == "GET":
            return Response(QuotationItemSerializer(quotation.items.select_related("offering"), many=True).data)

        self._require_write(request)

        offering_id = int_param(body_dict(request).get("offering"), "offering")
        if not offering_id:
            raise ValidationError({"offering": "Required: the catalogue offering being quoted."})
        try:
            offering = ServiceOffering.objects.get(pk=offering_id, is_active=True)
        except ServiceOffering.DoesNotExist as exc:
            raise ValidationError({"offering": "No such active offering."}) from exc

        quantity = int_param(body_dict(request).get("quantity"), "quantity") or 1
        if quantity < 1:
            raise ValidationError({"quantity": "Must be at least 1."})

        try:
            discount = Decimal(str(body_dict(request).get("discount_pct") or 0))
        except InvalidOperation as exc:
            raise ValidationError({"discount_pct": "Expected a number."}) from exc

        try:
            item = services.add_item(quotation, offering, quantity=quantity, discount_pct=discount)
        except services.QuotationError as exc:
            raise _quotation_error(exc) from exc

        return Response(QuotationItemSerializer(item).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        """Issue it to the customer, which also emails them a notice."""
        return self._transition(request, services.send_quotation)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        """
        Record an acceptance that arrived some other way -- a signed copy, a
        purchase order by email. The customer's own acceptance goes through
        the portal endpoint below, and the two are told apart on the record.
        """
        return self._transition(request, lambda q: services.accept_quotation(q, staff=request.user))

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._transition(request, lambda q: services.decline_quotation(q, staff=request.user))

    @action(detail=True, methods=["post"])
    def revise(self, request, pk=None):
        """
        Start a replacement draft carrying this quotation's lines.

        The supported way to change an offer that has gone out: the new
        draft points back at the one it supersedes, so the history reads as
        what happened rather than as an edit nobody can see.
        """
        self._require_write(request)
        quotation = self.get_object()
        replacement = services.revise(quotation, prepared_by=request.user)
        return Response(QuotationDetailSerializer(replacement).data, status=status.HTTP_201_CREATED)

    def _require_write(self, request):
        if not (request.user.is_superuser or request.user.roles.filter(name__in=QUOTATION_WRITE_ROLES).exists()):
            raise PermissionDenied(
                "Working on a quotation requires the Sample Receiver, Training Coordinator, "
                "Lab Supervisor, or System Administrator role."
            )

    def _transition(self, request, operation):
        self._require_write(request)
        quotation = self.get_object()
        try:
            operation(quotation)
        except services.QuotationError as exc:
            raise _quotation_error(exc) from exc
        except TransitionNotAllowed as exc:
            raise ValidationError(
                {"detail": f"Cannot do that while the quotation is {quotation.status}: {exc}"}
            ) from exc
        quotation.refresh_from_db()
        return Response(QuotationDetailSerializer(quotation).data)


class CustomerQuotationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /my/quotations/ -- the customer's own offers, and their answer.

    Drafts are excluded, and that is a correctness rule rather than a
    tidiness one: a draft is a quotation the lab has not issued, and
    showing someone a price that has not been decided on is worse than
    showing them nothing. The RLS policy scopes the table to their rows;
    this filter is what scopes it to the ones that have been *sent*.
    """

    authentication_classes = [CustomerSessionAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get_serializer_class(self):
        return CustomerQuotationDetailSerializer if self.action == "retrieve" else CustomerQuotationSerializer

    def get_queryset(self):
        return (
            Quotation.objects.filter(customer=self.request.user)
            .exclude(status=Quotation.Status.DRAFT)
            .prefetch_related("items__offering")
        )

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        """
        The customer accepts their own offer, and the quoted figures become
        order lines at the price quoted.
        """
        return self._answer(request, lambda q: services.accept_quotation(q, customer=request.user))

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._answer(request, services.decline_quotation)

    def _answer(self, request, operation):
        quotation = self.get_object()
        try:
            operation(quotation)
        except services.QuotationError as exc:
            raise _quotation_error(exc) from exc
        except TransitionNotAllowed as exc:
            raise ValidationError(
                {"detail": f"This quotation has already been {quotation.get_status_display().lower()}."}
            ) from exc
        quotation.refresh_from_db()
        return Response(CustomerQuotationDetailSerializer(quotation).data)
