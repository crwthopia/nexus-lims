"""
Catalogue serializers.

The one thing worth stating: a price is always returned with all three
figures — net, VAT and gross — regardless of which way it was quoted. The
alternative is every consumer reimplementing the same conditional, and a
dashboard that adds a VAT-inclusive rate to a VAT-exclusive one is off by
12% with nothing on screen to say so.
"""

from rest_framework import serializers

from apps.catalogue.models import CATALOGUE_SERVICE_LINES, OfferingPrice, ServiceOffering


class OfferingPriceSerializer(serializers.ModelSerializer):
    net_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    vat_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    gross_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_current = serializers.BooleanField(read_only=True)
    created_by_display_name = serializers.CharField(source="created_by.display_name", read_only=True, default=None)

    class Meta:
        model = OfferingPrice
        fields = [
            "id", "offering", "amount", "currency", "vat_treatment", "vat_rate_pct",
            "effective_from", "effective_to", "note",
            "net_amount", "vat_amount", "gross_amount", "is_current",
            "created_at", "created_by", "created_by_display_name",
        ]
        # effective_to is set by superseding, never by the client: two
        # clients each closing the other's window by hand is how price
        # history develops gaps.
        read_only_fields = ["id", "offering", "effective_to", "created_at", "created_by"]


class ServiceOfferingSerializer(serializers.ModelSerializer):
    current_price = serializers.SerializerMethodField()
    test_method_names = serializers.SerializerMethodField()

    class Meta:
        model = ServiceOffering
        fields = [
            "id", "code", "name", "description", "service_line", "test_methods", "test_method_names",
            "turnaround_days", "is_accredited", "is_active", "current_price", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_service_line(self, value):
        if value not in [line.value for line in CATALOGUE_SERVICE_LINES]:
            raise serializers.ValidationError(
                "Training is priced by its course catalogue (training.TrainingCourse), not here. "
                f"Choose one of: {', '.join(line.value for line in CATALOGUE_SERVICE_LINES)}."
            )
        return value

    def validate_code(self, value):
        # Quotations and POs are typed by hand at both ends; a code that
        # differs only in case or trailing space is the same code to
        # everyone except the unique constraint.
        return value.strip().upper()

    def get_test_method_names(self, obj):
        return [method.name for method in obj.test_methods.all()]

    def get_current_price(self, obj):
        from apps.catalogue.services import today

        price = obj.price_on(today())
        return OfferingPriceSerializer(price).data if price else None


class ServiceOfferingDetailSerializer(ServiceOfferingSerializer):
    """Adds the price history — the whole point of versioning them."""

    prices = OfferingPriceSerializer(many=True, read_only=True)

    class Meta(ServiceOfferingSerializer.Meta):
        fields = [*ServiceOfferingSerializer.Meta.fields, "prices"]


class SetPriceSerializer(serializers.Serializer):
    """Input to POST /service-offerings/{id}/set-price/."""

    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    vat_treatment = serializers.ChoiceField(choices=OfferingPrice.VatTreatment.choices)
    vat_rate_pct = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, required=False)
    effective_from = serializers.DateField(required=False)
    currency = serializers.CharField(max_length=3, required=False)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)
