"""
StandardReagent/Instrument/CalibrationRecord endpoints (Blueprint Section
6, C-2/E-3). Write access is restricted to Instrument Custodian / Lab
Supervisor -- the roles the Blueprint ties to equipment stewardship
(Section 3.1 Role, Section 5.1 "Instrument/Equipment screen"). There's no
dedicated "reagent custodian" role in the RBAC model, so StandardReagent
write access uses the same gate.
"""

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.accounts.models import Role
from apps.accounts.permissions import roles_required
from apps.equipment.models import CalibrationRecord, Instrument, StandardReagent
from apps.equipment.serializers import (
    CalibrationRecordSerializer,
    InstrumentDetailSerializer,
    InstrumentSerializer,
    StandardReagentSerializer,
)

RoleName = Role.RoleName
EQUIPMENT_WRITE_ROLES = (RoleName.INSTRUMENT_CUSTODIAN, RoleName.LAB_SUPERVISOR)


class StandardReagentViewSet(viewsets.ModelViewSet):
    queryset = StandardReagent.objects.all()
    serializer_class = StandardReagentSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), roles_required(*EQUIPMENT_WRITE_ROLES)()]
        return [IsAuthenticated()]


class InstrumentViewSet(viewsets.ModelViewSet):
    queryset = Instrument.objects.select_related("parent_instrument", "custodian").prefetch_related("child_instruments")
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return InstrumentDetailSerializer
        return InstrumentSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), roles_required(*EQUIPMENT_WRITE_ROLES)()]
        return [IsAuthenticated()]


class CalibrationRecordViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """
    Create/list/retrieve only -- a calibration event is an immutable record
    of what happened, not something to edit after the fact (FR-E17-01
    ALCOA). Creating one keeps Instrument.status/calibration_due_date in
    sync (FR-E3-02: "block assignment of an out-of-calibration instrument
    to new testing until cleared"): a passing result returns the instrument
    to in_service, anything else marks it out_of_calibration, and either
    way calibration_due_date advances to next_due_date.
    """

    queryset = CalibrationRecord.objects.select_related("instrument", "performed_by")
    serializer_class = CalibrationRecordSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), roles_required(*EQUIPMENT_WRITE_ROLES)()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        instrument_id = self.request.query_params.get("instrument")
        if instrument_id:
            qs = qs.filter(instrument_id=instrument_id)
        return qs

    def perform_create(self, serializer):
        record = serializer.save(performed_by=self.request.user)
        instrument = record.instrument
        instrument.status = (
            Instrument.Status.IN_SERVICE
            if record.result.strip().lower() == "pass"
            else Instrument.Status.OUT_OF_CALIBRATION
        )
        instrument.calibration_due_date = record.next_due_date
        instrument.save(update_fields=["status", "calibration_due_date"])
