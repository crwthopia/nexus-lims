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
    class Meta:
        model = Instrument
        fields = ["id", "name", "model", "parent_instrument", "calibration_due_date", "status", "custodian"]
        read_only_fields = ["id"]


class InstrumentDetailSerializer(InstrumentSerializer):
    child_instruments = InstrumentSerializer(many=True, read_only=True)

    class Meta(InstrumentSerializer.Meta):
        fields = InstrumentSerializer.Meta.fields + ["child_instruments"]


class CalibrationRecordSerializer(serializers.ModelSerializer):
    performed_by = serializers.PrimaryKeyRelatedField(read_only=True)
    instrument_name = serializers.CharField(source="instrument.name", read_only=True)

    class Meta:
        model = CalibrationRecord
        fields = ["id", "instrument", "instrument_name", "performed_by", "performed_at", "result", "next_due_date"]
        read_only_fields = ["id", "performed_by"]
