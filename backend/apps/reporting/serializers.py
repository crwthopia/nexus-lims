from rest_framework import serializers

from apps.reporting.models import Report
from apps.samples.models import Sample


class ReportSerializer(serializers.ModelSerializer):
    """
    FR-C6-03: a COA/Report may only be generated once its Sample has reached
    'approved'. This is the OQ negative-test scenario called out in
    Blueprint Section 8.3 ("attempt POST /samples/{id}/reports against a
    Sample not in the approved state"); it's checked here against
    Sample.status, which is itself FSM-protected, so this can't be spoofed
    by client input.

    file_id and status are read-only: the PDF pipeline
    (apps/reporting/tasks.generate_report_pdf) writes both. A client-supplied
    file_id would be a pointer to an arbitrary object in the bucket, including
    another customer's report, and a client-supplied status would let a caller
    claim a report was ready before anything had rendered.
    """

    generated_by = serializers.PrimaryKeyRelatedField(read_only=True)
    # Read-only display fields, matching the convention used across the other
    # serializers: a list UI would otherwise only see bare FK ids and have to
    # issue a request per row to render a sample code.
    generated_by_display_name = serializers.CharField(source="generated_by.display_name", read_only=True)
    sample_code = serializers.CharField(source="sample.unique_sample_code", read_only=True, default=None)

    class Meta:
        model = Report
        fields = [
            "id", "sample", "sample_code", "order", "report_type", "file_id", "status",
            "failure_reason", "generated_at", "generated_by", "generated_by_display_name",
            "version",
        ]
        read_only_fields = [
            "id", "file_id", "status", "failure_reason", "generated_at", "generated_by",
            "generated_by_display_name", "sample_code", "version",
        ]

    def validate(self, attrs):
        sample = attrs.get("sample")
        order = attrs.get("order")
        if not sample and not order:
            raise serializers.ValidationError("A Report must reference a sample or an order.")
        if sample and sample.status != Sample.Status.APPROVED:
            raise serializers.ValidationError(
                f"Sample '{sample.unique_sample_code}' must be 'approved' before a report can be "
                f"generated (currently '{sample.status}'), per FR-C6-03."
            )
        return attrs

    def create(self, validated_data):
        validated_data["generated_by"] = self.context["request"].user
        return super().create(validated_data)
