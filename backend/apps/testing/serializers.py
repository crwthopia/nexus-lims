from django.utils import timezone
from rest_framework import serializers

from apps.equipment.models import StandardReagent
from apps.testing import holding_times
from apps.testing.ingestion import IngestionError, assert_certified, compute_out_of_spec
from apps.accounts.models import Role
from apps.notifications.models import NotificationRecord
from apps.notifications.notify import notify_each, staff_emails_for_roles
from apps.testing.models import TestMethod, TestRequest, TestResult


class TestMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestMethod
        fields = ["id", "name", "method_reference", "specification_limits", "holding_time", "active_sop_version"]

    def validate_specification_limits(self, value):
        """
        FR-C3-08 depends on these being numbers that can be compared.

        A JSONField accepts anything, so {"min": "abc"} stored cleanly and
        then made every result entry and every ingestion for the method a
        500 -- see compute_out_of_spec in apps/testing/ingestion.py. A
        min above its max is the quieter failure of the two: nothing
        crashes, and every result the method ever produces is flagged
        out-of-spec, which reads as a process in crisis rather than as a
        typo in a form.
        """
        if value in (None, {}):
            return value
        if not isinstance(value, dict):
            raise serializers.ValidationError('Expected an object, e.g. {"min": 0, "max": 10}.')

        bounds = {}
        for key in ("min", "max"):
            if key not in value:
                continue
            try:
                bounds[key] = float(value[key])
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    f"'{key}' must be a number, got {value[key]!r}."
                ) from None

        if "min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]:
            raise serializers.ValidationError(
                f"'min' ({value['min']}) is above 'max' ({value['max']}), so every "
                f"result would be flagged out of spec."
            )
        return value


class TestRequestSerializer(serializers.ModelSerializer):
    """
    sample_code/test_method_name/assigned_analyst_display_name: read-only
    convenience fields for list/detail UIs (e.g. the Staff Console's Testing
    Queue) that would otherwise only see bare FK ids.

    `due_at` and `due_at_basis` are read-only because they are computed
    from the sample's clock and the method's holding time
    (apps/testing/holding_times.py), never chosen. A settable deadline is
    an editable holding time, which is the one thing a holding-time control
    must not be.

    `is_overdue` is sent down rather than left to the client to derive: it
    depends on the current time *and* on which statuses still count as
    outstanding, and a UI that guessed the second half would show a
    completed test as overdue forever.
    """

    sample_code = serializers.CharField(source="sample.unique_sample_code", read_only=True)
    sample_priority = serializers.CharField(source="sample.priority", read_only=True)
    test_method_name = serializers.CharField(source="test_method.name", read_only=True)
    assigned_analyst_display_name = serializers.CharField(
        source="assigned_analyst.display_name", read_only=True, default=None
    )
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = TestRequest
        fields = [
            "id", "sample", "sample_code", "sample_priority", "test_method", "test_method_name", "status",
            "due_at", "due_at_basis", "is_overdue",
            "assigned_analyst", "assigned_analyst_display_name", "assigned_instrument", "created_at",
        ]
        read_only_fields = ["id", "status", "due_at", "due_at_basis", "created_at"]

    def create(self, validated_data):
        """
        Book the request in with its deadline already computed, where the
        sample has a clock to compute one from.

        A request is routinely created against a sample that has not
        arrived yet, in which case this correctly sets nothing and the
        receive transition fills it in later
        (apps/samples/views.SampleViewSet.receive).
        """
        test_request = super().create(validated_data)
        holding_times.apply_to(test_request)
        return test_request


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
            "id", "test_request", "analyte", "data_type", "value", "unit", "entered_by", "entered_by_display_name",
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
        try:
            assert_certified(request.user, test_request.test_method)
        except IngestionError as exc:
            # Same rule, same message, one implementation -- see
            # apps/testing/ingestion.py for why it lives there.
            raise serializers.ValidationError(str(exc)) from exc
        return attrs

    def create(self, validated_data):
        validated_data["entered_by"] = self.context["request"].user
        validated_data["is_out_of_spec"] = compute_out_of_spec(
            validated_data["test_request"].test_method,
            validated_data["data_type"],
            validated_data["value"],
        )
        result = super().create(validated_data)
        if result.is_out_of_spec:
            # An OOS result is candidate nonconforming work (7.10) and the
            # analyst who entered it is not the person who decides that. The
            # measured value is deliberately not in the message -- see
            # apps/notifications/messages.py.
            notify_each(
                NotificationRecord.Kind.RESULT_OUT_OF_SPEC,
                staff_emails_for_roles(Role.RoleName.QA_OFFICER, Role.RoleName.LAB_SUPERVISOR),
                subject=f"NexusLIMS: out-of-specification result on {result.test_request.sample.unique_sample_code}",
                dedupe_key=f"result-oos:{result.id}",
                entity=result,
            )
        return result
