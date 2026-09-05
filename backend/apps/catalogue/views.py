"""
Service catalogue endpoints.

Read is open to any authenticated staff member: an analyst booking a sample
in needs to see what was ordered and what it costs, and hiding the rate card
from the people doing the work has never made a lab quieter. Write is held
to Lab Supervisor and System Administrator -- a price change is a commercial
decision with an audit trail, not a correction anyone passing can make.

Customers cannot reach this at all yet. Publishing a rate card to the portal
is a business decision NASAT has not made, and the safe default for a price
list is that it goes out when someone decides it should, not because an
endpoint existed.
"""

from django.db.models import Prefetch, Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.accounts.permissions import roles_required
from apps.catalogue import services
from apps.catalogue.models import OfferingPrice, ServiceOffering
from apps.catalogue.serializers import (
    OfferingPriceSerializer,
    ServiceOfferingDetailSerializer,
    ServiceOfferingSerializer,
    SetPriceSerializer,
)
from apps.common.params import int_param, str_param

RoleName = Role.RoleName
CATALOGUE_WRITE_ROLES = (RoleName.LAB_SUPERVISOR, RoleName.SYSTEM_ADMINISTRATOR)


class ServiceOfferingViewSet(viewsets.ModelViewSet):
    # Prices are prefetched, not joined per row: price_on() reads them in
    # Python, so a catalogue of 200 offerings is two queries rather than 201.
    queryset = ServiceOffering.objects.prefetch_related(
        "test_methods", Prefetch("prices", queryset=OfferingPrice.objects.select_related("created_by")),
    )
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ("retrieve", "set_price"):
            return ServiceOfferingDetailSerializer
        return ServiceOfferingSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy", "set_price"):
            return [IsAuthenticated(), roles_required(*CATALOGUE_WRITE_ROLES)()]
        return [IsAuthenticated()]

    def get_queryset(self):
        """
        ?service_line=, ?active=true|false, ?q= (code or name).

        Same hand-read pattern as every other list endpoint here -- DRF
        ignores query params it does not recognise, so a filter that is not
        read is a filter that silently returns everything.
        """
        qs = super().get_queryset()

        service_line = str_param(self.request.query_params.get("service_line"), "service_line", max_length=32)
        if service_line:
            qs = qs.filter(service_line=service_line)

        active = self.request.query_params.get("active")
        if active in ("true", "false"):
            qs = qs.filter(is_active=(active == "true"))

        search = str_param(self.request.query_params.get("q"), "q", max_length=255)
        if search:
            qs = qs.filter(Q(code__icontains=search) | Q(name__icontains=search))
        return qs

    @action(detail=True, methods=["post"], url_path="set-price")
    def set_price(self, request, pk=None):
        """
        Price this offering from a date, closing whatever it was before.

        A POST rather than a PATCH on the price row, because that is what
        happens: the old price is not edited, it is ended. Defaults to
        taking effect today and to the 12% Philippine rate, so the common
        case is an amount and a treatment.
        """
        offering = self.get_object()
        payload = SetPriceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        services.set_price(
            offering,
            amount=data["amount"],
            vat_treatment=data["vat_treatment"],
            vat_rate_pct=data.get("vat_rate_pct", OfferingPrice._meta.get_field("vat_rate_pct").default),
            effective_from=data.get("effective_from") or services.today(),
            currency=data.get("currency", "PHP"),
            note=data.get("note", ""),
            created_by=request.user if request.user.is_authenticated else None,
        )
        offering.refresh_from_db()
        return Response(ServiceOfferingDetailSerializer(offering).data)


class OfferingPriceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Price history, read-only and on purpose: prices are written through
    `set-price` so the windows stay contiguous, and a row here that could be
    edited or deleted directly would be a hole in exactly the record an
    auditor asks to see.
    """

    queryset = OfferingPrice.objects.select_related("offering", "created_by")
    serializer_class = OfferingPriceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        offering_id = int_param(self.request.query_params.get("offering"), "offering")
        if offering_id is not None:
            qs = qs.filter(offering_id=offering_id)
        return qs
