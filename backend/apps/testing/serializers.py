from django.utils import timezone
from rest_framework import serializers

from apps.equipment.models import StandardReagent
from apps.testing.models import TestMethod, TestRequest, TestResult


class TestMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestMethod
        fields = ["id", "name", "method_reference", "specification_limits", "holding_time", "active_sop_version"]


class TestRequestSerializer(serializers.ModelSerializer):
    """sample_code/test_method_name/assigned_analyst_display_name: read-only convenience fields for list/detail UIs (e.g. the Staff Console's Testing Queue) that would otherwise only see bare FK ids."""

    sample_code = serializers.CharField(source="sample.unique_sample_code", read_only=True)
    test_method_name = serializers.CharField(source="test_method.name", read_only=True)
    assigned_analyst_display_name = serializers.CharField(
        source="assigned_analyst.display_name", read_only=True, default=None
    )

    class Meta:
        model = TestRequest
        fields = [
            "id", "sample", "sample_code", "test_method", "test_method_name", "status",
            "assigned_analyst", "assigned_analyst_display_name", "assigned_instrument", "created_at",
        ]
        read_only_fields = ["id", "status", "created_at"]


class TestResultSerializer(serializers.ModelSerializer):
    """
    FR-C3-01/C3-02: standard_reagents is restricted to active, non-expired
    items. FR-C3-08: is_out_of_spec is computed at entry time from
    TestMethod.specification_limits (a {"min": ..., "max": ...} numeric
    range), not accepted as client input, so a result can't be silently
    entered as in-spec when it isn't.
    """

    is_out_of_spec = serializers.BooleanField(read_only=True)
    entered_by = serializers.PrimaryKeyRelatedField(read_only=True)
    entered_by_display_name = serializers.CharField(source="entered_by.display_name", read_only=True, default=None)

    class Meta:
        model = TestResult
        fields = [
            "id", "test_request", "data_type", "value", "unit", "entered_by", "entered_by_display_name",
            "entered_at", "is_out_of_spec", "instrument", "standard_reagents", "raw_file_id", "raw_file_checksum_sha256",
        ]
        read_only_fields = ["id", "entered_by", "entered_at", "is_out_of_spec"]

    def validate_standard_reagents(self, reagents):
        today = timezone.localdate()
        invalid = [
            r for r in reagents
            if r.status != StandardReagent.Status.ACTIVE or r.expiry_date < today
        ]
        if invalid:
            names = ", ".join(f"{r.name} (lot {r.lot_number})" for r in invalid)
            raise serializers.ValidationError(
                f"Only active, non-expired standards/reagents may be used (FR-C3-02): {names}"
            )
        return reagents

    def validate(self, attrs):
        request = self.context["request"]
        test_request = attrs.get("test_request") or getattr(self.instance, "test_request", None)
        test_method = test_request.test_method
        if not request.user.is_superuser and not request.user.instrument_certifications.filter(
            pk=test_method.pk
        ).exists():
            raise serializers.ValidationError(
                f"'{request.user.display_name}' is not certified for test method "
                f"'{test_method.name}' (FR-C3-02 competency check)."
            )
        return attrs

    def create(self, validated_data):
        validated_data["entered_by"] = self.context["request"].user
        validated_data["is_out_of_spec"] = self._compute_out_of_spec(validated_data)
        return super().create(validated_data)

    @staticmethod
    def _compute_out_of_spec(validated_data):
        limits = validated_data["test_request"].test_method.specification_limits or {}
        if validated_data["data_type"] not in (TestResult.DataType.FLOAT, TestResult.DataType.INT):
            return False
        if "min" not in limits and "max" not in limits:
            return False
        try:
            numeric_value = float(validated_data["value"])
        except (TypeError, ValueError):
            return False
        if "min" in limits and numeric_value < limits["min"]:
            return True
        if "max" in limits and numeric_value > limits["max"]:
            return True
        return False
