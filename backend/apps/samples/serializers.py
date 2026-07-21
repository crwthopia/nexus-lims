from rest_framework import serializers

from apps.samples.models import ChainOfCustodyEvent, Order, Sample


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ["id", "customer", "service_line", "status", "created_at"]
        read_only_fields = ["id", "status", "created_at"]


class ChainOfCustodyEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChainOfCustodyEvent
        fields = [
            "id", "sample", "from_holder", "to_holder", "from_location",
            "to_location", "timestamp", "event_type",
        ]
        read_only_fields = ["id", "timestamp"]


class SampleSerializer(serializers.ModelSerializer):
    """
    status is FSM-managed and read-only here (FR-C1-01 etc.); it only ever
    changes through the dedicated transition actions on SampleViewSet, never
    via a plain PATCH, so illegal transitions can't be smuggled in through
    a generic update.
    """

    class Meta:
        model = Sample
        fields = [
            "id", "order", "service_line", "unique_sample_code", "client_reference",
            "sampling_point", "collection_datetime", "container_type", "container_count",
            "preservation_method", "retention_period", "holding_time", "status",
            "safety_flags", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]


class SampleDetailSerializer(SampleSerializer):
    chain_of_custody_events = ChainOfCustodyEventSerializer(many=True, read_only=True)

    class Meta(SampleSerializer.Meta):
        fields = SampleSerializer.Meta.fields + ["chain_of_custody_events"]
