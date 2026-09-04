"""
Quotation serializers, staff and customer.

The customer's view is the narrower one for the same reason as elsewhere:
`source_price` is a catalogue row id, provenance for whoever has to explain
a figure internally and a handle on a rate card the customer cannot open.
What both views share is that every price field is read-only. A quotation
is priced by the server from the rate card in force; a client that could
send a `unit_amount` could quote any figure it liked.
"""

from rest_framework import serializers

from apps.quotations.models import Quotation, QuotationItem


class QuotationItemSerializer(serializers.ModelSerializer):
    offering_code = serializers.CharField(source="offering.code", read_only=True)
    offering_name = serializers.CharField(source="offering.name", read_only=True)
    line_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    net_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    vat_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    gross_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = QuotationItem
        fields = [
            "id", "quotation", "offering", "offering_code", "offering_name", "quantity", "discount_pct",
            "unit_amount", "currency", "vat_treatment", "vat_rate_pct", "source_price",
            "line_amount", "net_amount", "vat_amount", "gross_amount",
        ]
        read_only_fields = fields


class CustomerQuotationItemSerializer(QuotationItemSerializer):
    class Meta(QuotationItemSerializer.Meta):
        fields = [
            "id", "offering_code", "offering_name", "quantity", "discount_pct",
            "unit_amount", "currency", "vat_treatment", "vat_rate_pct",
            "line_amount", "net_amount", "vat_amount", "gross_amount",
        ]
        read_only_fields = fields


class QuotationSerializer(serializers.ModelSerializer):
    customer_email = serializers.CharField(source="customer.email", read_only=True)
    prepared_by_display_name = serializers.CharField(source="prepared_by.display_name", read_only=True, default=None)
    totals = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Quotation
        fields = [
            "id", "reference", "customer", "customer_email", "service_line", "order", "supersedes",
            "status", "valid_until", "notes", "item_count", "totals", "is_expired",
            "sent_at", "decided_at", "prepared_by", "prepared_by_display_name", "created_at",
        ]
        # status moves only through the FSM transitions in services.py, so a
        # PATCH can never set it -- the same rule Sample and TrainingSession
        # already live by.
        read_only_fields = [
            "id", "reference", "status", "order", "supersedes", "sent_at", "decided_at",
            "prepared_by", "created_at",
        ]

    def get_item_count(self, quotation):
        return quotation.items.count()

    def get_totals(self, quotation):
        net, vat, gross = quotation.totals()
        currencies = {item.currency for item in quotation.items.all()}
        return {
            "net": str(net),
            "vat": str(vat),
            "gross": str(gross),
            "currency": currencies.pop() if len(currencies) == 1 else None,
        }

    def validate_valid_until(self, value):
        """
        A date already past describes a quotation nobody can answer. Checked
        on write rather than only at send, so the mistake surfaces while the
        person who made it is still on the screen.
        """
        from apps.quotations.services import today

        if value < today():
            raise serializers.ValidationError("A quotation cannot be valid until a date that has already passed.")
        return value


class QuotationDetailSerializer(QuotationSerializer):
    items = QuotationItemSerializer(many=True, read_only=True)

    class Meta(QuotationSerializer.Meta):
        fields = [*QuotationSerializer.Meta.fields, "items"]


class CustomerQuotationSerializer(QuotationSerializer):
    """What the customer being quoted sees. No internal preparer, no notes-free rewrite -- just their offer."""

    class Meta(QuotationSerializer.Meta):
        fields = [
            "id", "reference", "service_line", "status", "valid_until", "notes",
            "item_count", "totals", "is_expired", "sent_at", "decided_at", "created_at",
        ]
        read_only_fields = fields


class CustomerQuotationDetailSerializer(CustomerQuotationSerializer):
    items = CustomerQuotationItemSerializer(many=True, read_only=True)
    order = serializers.IntegerField(source="order_id", read_only=True)

    class Meta(CustomerQuotationSerializer.Meta):
        fields = [*CustomerQuotationSerializer.Meta.fields, "items", "order"]
        read_only_fields = fields
