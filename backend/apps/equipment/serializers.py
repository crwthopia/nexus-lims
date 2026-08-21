from django.utils import timezone
from rest_framework import serializers

from apps.equipment.models import CalibrationRecord, Instrument, StandardReagent


class StandardReagentSerializer(serializers.ModelSerializer):
    class Meta:
        model = StandardReagent
        fields = [
            "id", "name", "lot_number", "crm_traceability_reference",
            "opened_date", "expiry_date", "status", "storage_location",
        ]
        read_only_fields = ["id"]


class InstrumentSerializer(serializers.ModelSerializer):
    custodian_display_name = serializers.CharField(source="custodian.display_name", read_only=True, default=None)

    class Meta:
        model = Instrument
        fields = [
            "id", "name", "model", "parent_instrument", "calibration_due_date",
            "status", "custodian", "custodian_display_name",
        ]
        read_only_fields = ["id"]


class InstrumentDetailSerializer(InstrumentSerializer):
    child_instruments = InstrumentSerializer(many=True, read_only=True)

    class Meta(InstrumentSerializer.Meta):
        fields = InstrumentSerializer.Meta.fields + ["child_instruments"]


class CalibrationRecordSerializer(serializers.ModelSerializer):
    performed_by = serializers.PrimaryKeyRelatedField(read_only=True)
    performed_by_display_name = serializers.CharField(source="performed_by.display_name", read_only=True, default=None)
    instrument_name = serializers.CharField(source="instrument.name", read_only=True)

    class Meta:
        model = CalibrationRecord
        fields = [
            "id", "instrument", "instrument_name", "performed_by", "performed_by_display_name",
            "performed_at", "result", "next_due_date",
        ]
        read_only_fields = ["id", "performed_by"]

    def validate(self, attrs):
        """
        A calibration record states that a calibration happened and when the
        next one falls due. Both halves have to be true of the same event.

        FR-E3-02 drives Instrument.status from these, and the Staff Console
        shows an instrument as due or overdue by comparing the due date to
        today -- so a record due before it was performed reports an
        instrument as overdue the moment it is calibrated, and a record
        performed in the future carries a `result` for something that has
        not happened yet.
        """
        performed_at = attrs.get("performed_at", getattr(self.instance, "performed_at", None))
        next_due_date = attrs.get("next_due_date", getattr(self.instance, "next_due_date", None))

        if performed_at is not None and performed_at > timezone.now():
            raise serializers.ValidationError(
                {"performed_at": "A calibration cannot be recorded as performed in the future."}
            )
        if performed_at is not None and next_due_date is not None:
            if next_due_date < performed_at.date():
                raise serializers.ValidationError(
                    {"next_due_date": (
                        f"The next calibration is due ({next_due_date}) before this one was "
                        f"performed ({performed_at.date()})."
                    )}
                )
        return attrs
