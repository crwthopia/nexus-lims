from decimal import Decimal

from rest_framework import serializers

from apps.billing.models import Invoice
from apps.samples.models import ChainOfCustodyEvent, Order, OrderItem, Sample, SampleReceipt
from apps.testing import holding_times


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
            "to_location", "occurred_at", "timestamp", "event_type",
        ]
        # occurred_at stays writable (it is the operator's claim about when
        # custody moved); timestamp never is (it is the system's record of
        # when they said so). See the field comments on the model.
        read_only_fields = ["id", "timestamp"]


class SampleSerializer(serializers.ModelSerializer):
    """
    status is FSM-managed and read-only here (FR-C1-01 etc.); it only ever
    changes through the dedicated transition actions on SampleViewSet, never
    via a plain PATCH, so illegal transitions can't be smuggled in through
    a generic update.

    `unique_sample_code` is read-only for the same class of reason and a
    stronger one: it is allocated server-side on create
    (apps.samples.identity) and a trigger refuses any later change, because
    it is printed on a physical container and ISO/IEC 17025:2017 7.4.2
    requires that identification to survive for as long as the item is in
    the building. A writable field here would let a client both invent the
    identity of an item and, worse, renumber one already on a shelf.

    `received_at` is read-only because it is written by the receive
    transition from the operator-supplied arrival time, alongside the
    SampleReceipt row that says what the item looked like when it got here.
    Letting it be PATCHed would allow the date on the report to drift away
    from the receipt record backing it.
    """

    HOLDING_TIME_INPUTS = frozenset({"collection_datetime", "holding_time"})

    class Meta:
        model = Sample
        fields = [
            "id", "order", "service_line", "unique_sample_code", "client_reference",
            "sampling_point", "collection_datetime", "container_type", "container_count",
            "preservation_method", "retention_period", "holding_time", "status", "priority",
            "safety_flags", "received_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "unique_sample_code", "status", "received_at", "created_at", "updated_at",
        ]

    def update(self, instance, validated_data):
        """
        Correcting a collection time or a sample holding time moves every
        deadline computed from it, so recompute them here.

        The third of the three call sites in apps/testing/holding_times --
        and the one that is easiest to forget, because nothing about a
        PATCH to a sample looks like it touches the testing queue. Without
        it, a collection time corrected the morning after receipt would
        leave every analysis on that sample carrying a deadline counted
        from the wrong instant, with nothing to show it was stale.

        Guarded on the two fields that actually feed the calculation:
        recomputing on every unrelated PATCH would write a history row per
        test request each time somebody fixed a typo in a sampling point.
        """
        touches_deadlines = self.HOLDING_TIME_INPUTS & validated_data.keys()
        sample = super().update(instance, validated_data)
        if touches_deadlines:
            holding_times.apply_to_sample(sample)
        return sample


class SampleReceiptSerializer(serializers.ModelSerializer):
    """
    The arrival record, read-only over the API.

    Every field here is written by a transition action -- receive,
    receipt-consultation, reject-at-receipt -- rather than by a PATCH, for
    the same reason Sample.status is: the CHECK constraints and the
    start_prep gate assume a receipt only ever changes through a path that
    knows what ISO/IEC 17025:2017 7.4.3 requires of it. A generic update
    could satisfy the constraints and still leave, say, a consultation
    outcome recorded against a receipt that never deviated.

    `deviation_reasons` and `is_conforming` are computed on the model and
    surfaced here so a client renders the same summary the workflow gate
    reasons about, rather than re-deriving it from eight booleans and
    getting the tri-state temperature check subtly wrong.
    """

    deviation_reasons = serializers.ListField(child=serializers.CharField(), read_only=True)
    is_conforming = serializers.BooleanField(read_only=True)
    consultation_recorded = serializers.BooleanField(read_only=True)
    received_by_name = serializers.CharField(source="received_by.display_name", read_only=True)

    class Meta:
        model = SampleReceipt
        fields = [
            "id", "sample", "received_at", "received_by", "received_by_name", "received_from",
            "condition_on_receipt", "receipt_temperature_c", "temperature_conforms",
            "seal_intact", "volume_sufficient", "container_conforms", "preservation_conforms",
            "labelling_legible", "storage_location", "deviations",
            "customer_consulted_at", "consultation_outcome", "customer_authorised_despite_deviation",
            "report_disclaimer_required", "disclaimer_text",
            "deviation_reasons", "is_conforming", "consultation_recorded",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class SampleDetailSerializer(SampleSerializer):
    chain_of_custody_events = ChainOfCustodyEventSerializer(many=True, read_only=True)
    receipt = SampleReceiptSerializer(read_only=True)

    class Meta(SampleSerializer.Meta):
        fields = SampleSerializer.Meta.fields + ["chain_of_custody_events", "receipt"]
