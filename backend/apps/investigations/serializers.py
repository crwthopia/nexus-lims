from rest_framework import serializers

from apps.investigations.models import Investigation


class InvestigationSerializer(serializers.ModelSerializer):
    opened_by_display_name = serializers.CharField(source="opened_by.display_name", read_only=True)

    class Meta:
        model = Investigation
        fields = [
            "id", "related_test_result", "related_sample", "type",
            "opened_by", "opened_by_display_name", "root_cause", "capa_actions",
            "status", "opened_at", "closed_at",
        ]
        # opened_by is set server-side (InvestigationViewSet.perform_create).
        # closed_at is only ever set atomically with status=closed by the
        # close action below, never as an independent field edit.
        read_only_fields = ["id", "opened_by", "closed_at", "opened_at"]

    def validate(self, attrs):
        related_test_result = attrs.get("related_test_result", getattr(self.instance, "related_test_result", None))
        related_sample = attrs.get("related_sample", getattr(self.instance, "related_sample", None))
        if not related_test_result and not related_sample:
            raise serializers.ValidationError("An Investigation must reference a related_test_result or related_sample.")
        return attrs

    def validate_status(self, value):
        if value == Investigation.Status.CLOSED:
            raise serializers.ValidationError(
                "Use POST /investigations/{id}/close/ to close an investigation (also sets closed_at)."
            )
        return value
