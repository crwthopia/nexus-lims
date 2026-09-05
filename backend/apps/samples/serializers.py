from decimal import Decimal

from rest_framework import serializers

from apps.billing.models import Invoice
from apps.samples.models import ChainOfCustodyEvent, Order, OrderItem, Sample


class OrderItemSerializer(serializers.ModelSerializer):
    """
    The price fields are all read-only, and that is the point of the model:
    they are snapshotted from the catalogue when the line is created
    (apps/samples/order_services.py). A writable `unit_amount` here would
    let a caller invent a price; a computed one would reprice history.
    """

    offering_code = serializers.CharField(source="offering.code", read_only=True)
    offering_name = serializers.CharField(source="offering.name", read_only=True)
    line_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    net_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    vat_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    gross_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_invoiced = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id", "order", "offering", "offering_code", "offering_name", "quantity", "discount_pct",
            "unit_amount", "currency", "vat_treatment", "vat_rate_pct", "source_price",
            "line_amount", "net_amount", "vat_amount", "gross_amount", "is_invoiced", "created_at",
        ]
        read_only_fields = [
            "id", "unit_amount", "currency", "vat_treatment", "vat_rate_pct", "source_price", "created_at",
        ]

    def get_is_invoiced(self, item):
        """Billed on an invoice that has not been voided -- see billing.services.unbilled_items."""
        return item.invoice_lines.exclude(invoice__status=Invoice.Status.VOID).exists()


class CustomerOrderItemSerializer(serializers.ModelSerializer):
    """
    An order line as the customer who placed it sees it.

    Narrower than the staff serializer on purpose, and the omissions are
    the point: `source_price` is a catalogue row id -- provenance for
    whoever has to explain a figure internally, and meaningless to the
    person who was charged it -- and the offering's own id is a handle on a
    rate card they cannot open. What is left is what a customer reading
    their order actually needs: what was tested, how much of it, at what
    rate, what was taken off, and what it comes to.

    The rate *is* shown, including any discount applied. It is their money;
    a line that hid what it cost, or quietly folded a discount into the
    total, would be worse than one that says nothing at all.
    """

    offering_code = serializers.CharField(source="offering.code", read_only=True)
    offering_name = serializers.CharField(source="offering.name", read_only=True)
    line_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    net_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    vat_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    gross_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_invoiced = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id", "offering_code", "offering_name", "quantity", "discount_pct",
            "unit_amount", "currency", "vat_treatment", "vat_rate_pct",
            "line_amount", "net_amount", "vat_amount", "gross_amount", "is_invoiced",
        ]
        read_only_fields = fields

    def get_is_invoiced(self, item):
        return item.invoice_lines.exclude(invoice__status=Invoice.Status.VOID).exists()


class OrderSerializer(serializers.ModelSerializer):
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ["id", "customer", "service_line", "status", "item_count", "created_at"]
        read_only_fields = ["id", "status", "created_at"]

    def get_item_count(self, order):
        return order.items.count()


class OrderDetailSerializer(OrderSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta(OrderSerializer.Meta):
        fields = [*OrderSerializer.Meta.fields, "items"]


class CustomerOrderDetailSerializer(OrderSerializer):
    """
    The customer's own order, with its lines and what they come to.

    Totals are summed here rather than left to the browser: the net of a
    line depends on how its rate was quoted, and a portal that added a
    VAT-inclusive line to a VAT-exclusive one would show a customer a total
    that is wrong by 12% -- on a page about what they owe.

    The invoices are listed too, so "what was I billed for this" is one
    click rather than a hunt through /my/invoices.
    """

    items = CustomerOrderItemSerializer(many=True, read_only=True)
    totals = serializers.SerializerMethodField()
    invoices = serializers.SerializerMethodField()

    class Meta(OrderSerializer.Meta):
        fields = [*OrderSerializer.Meta.fields, "items", "totals", "invoices"]

    def get_totals(self, order):
        net = vat = gross = Decimal("0.00")
        for item in order.items.all():
            net += item.net_amount
            vat += item.vat_amount
            gross += item.gross_amount
        currencies = {item.currency for item in order.items.all()}
        return {
            "net": str(net),
            "vat": str(vat),
            "gross": str(gross),
            # One currency per order in practice; stated rather than assumed
            # so a mixed order shows nothing instead of a meaningless sum.
            "currency": currencies.pop() if len(currencies) == 1 else None,
        }

    def get_invoices(self, order):
        return [
            {
                "id": invoice.id,
                "amount": str(invoice.amount),
                "currency": invoice.currency,
                "status": invoice.status,
                "created_at": invoice.created_at.isoformat(),
            }
            for invoice in order.invoices.all()
        ]


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
