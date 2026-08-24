from rest_framework import serializers

from apps.audit.models import SystemFailure


class SystemFailureSerializer(serializers.ModelSerializer):
    """
    The 7.11.3(e) register. Almost everything here is read-only, because
    almost everything here is written by the system at the moment of failure
    -- the two fields a person owns are `corrective_action` and the link to
    the `investigation` opened for it.

    `immediate_action` is read-only for the same reason `opened_by` is on
    InvestigationSerializer: it is a fact about what happened, not an
    opinion, and a register whose account of what the system did can be
    edited afterwards is not a record of anything.
    """

    component_display = serializers.CharField(source="get_component_display", read_only=True)
    immediate_action_display = serializers.CharField(source="get_immediate_action_display", read_only=True)
    acknowledged_by_display_name = serializers.CharField(
        source="acknowledged_by.display_name", read_only=True, default=None,
    )
    closed_by_display_name = serializers.CharField(source="closed_by.display_name", read_only=True, default=None)

    class Meta:
        model = SystemFailure
        fields = [
            "id", "component", "component_display", "severity", "summary", "detail",
            "immediate_action", "immediate_action_display",
            "occurrences", "first_seen_at", "last_seen_at",
            "status", "acknowledged_by", "acknowledged_by_display_name", "acknowledged_at",
            "corrective_action", "investigation",
            "closed_by", "closed_by_display_name", "closed_at",
        ]
        # `status` is deliberately absent: a read-only field is *dropped*
        # by DRF rather than refused, so PATCHing one returns 200 having
        # silently done nothing. For status that is the wrong answer -- the
        # caller believes they closed a failure. validate_status below
        # refuses it explicitly and says which endpoint to use instead, the
        # same way InvestigationSerializer does.
        read_only_fields = [
            "id", "component", "severity", "summary", "detail", "immediate_action",
            "occurrences", "first_seen_at", "last_seen_at",
            "acknowledged_by", "acknowledged_at", "closed_by", "closed_at",
        ]

    def validate_status(self, value):
        raise serializers.ValidationError(
            "Use POST /system-failures/{id}/acknowledge/ or POST /system-failures/{id}/close/ "
            "to change status -- both record who did it and when, and close/ requires a "
            "corrective action (ISO/IEC 17025:2017 7.11.3(e))."
        )
