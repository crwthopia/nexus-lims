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

    Actual PDF assembly (the decoupled WeasyPrint/Jinja2 pipeline, Blueprint
    Section 2.1a) is a Celery task not yet wired (README "Known gaps");
    file_id is accepted here as the OSS object key once that task has run.
    """

    generated_by = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Report
        fields = ["id", "sample", "order", "report_type", "file_id", "generated_at", "generated_by", "version"]
        read_only_fields = ["id", "generated_at", "generated_by", "version"]

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
