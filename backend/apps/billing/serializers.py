from rest_framework import serializers

from apps.billing.models import Invoice, InvoiceLine, Payment


class PaymentSerializer(serializers.ModelSerializer):
    """invoice/recorded_by are read-only: Payment is only ever created via POST /invoices/{id}/payments/ (apps/billing/views.py), which injects both server-side rather than trusting client-supplied values."""

    recorded_by_display_name = serializers.CharField(source="recorded_by.display_name", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id", "invoice", "method", "reference_number", "recorded_by",
            "recorded_by_display_name", "status", "paid_at", "notes",
        ]
        read_only_fields = ["id", "invoice", "recorded_by"]


class InvoiceLineSerializer(serializers.ModelSerializer):
    """
    Every field is read-only. Lines are written once, by
    `billing.services.invoice_order`, from a snapshot of the order line --
    an editable invoice line is an invoice that says something different
    today from what the customer was sent.
    """

    line_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    net_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    vat_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    gross_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = InvoiceLine
        fields = [
            "id", "invoice", "order_item", "description", "quantity", "unit_amount", "currency",
            "vat_treatment", "vat_rate_pct", "discount_pct",
            "line_amount", "net_amount", "vat_amount", "gross_amount", "created_at",
        ]
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    """customer_email: read-only display convenience -- an Invoice bills either an Order or an Enrollment (never both), so this resolves whichever is set rather than making a list UI look up two different resources to identify who's being billed."""

    customer_email = serializers.SerializerMethodField()
    # Derived from the lines rather than stored, so the breakdown and the
    # total can never disagree. Null on an invoice with no lines -- a
    # walk-in job billed as one typed figure has no VAT split to report,
    # and inventing one would be a claim the record does not support.
    net_total = serializers.SerializerMethodField()
    vat_total = serializers.SerializerMethodField()
    line_count = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "order", "enrollment", "customer_email", "amount", "currency", "status",
            "net_total", "vat_total", "line_count", "created_at",
        ]
        # status is read-only: it's only ever changed by confirming a Payment
        # (POST /invoices/{id}/payments/), not by direct PATCH, so it can't
        # drift out of sync with what payments were actually recorded.
        read_only_fields = ["id", "status", "created_at"]

    def validate_amount(self, value):
        """
        A negative invoice is a refund, and this system already has a
        separate model for that (training.CreditNote). Allowing one here
        would put money owed *to* a customer in the column that means money
        owed *by* them, where every total downstream adds it the wrong way.

        Zero is left alone deliberately: a fully discounted or fully
        credit-noted enrollment is a real thing to invoice at 0.00.
        """
        if value < 0:
            raise serializers.ValidationError(
                "An invoice amount cannot be negative. Issue a credit note instead."
            )
        return value

    def get_line_count(self, invoice):
        return invoice.lines.count()

    def get_net_total(self, invoice):
        net, _, _ = invoice.line_totals()
        return str(net) if invoice.lines.exists() else None

    def get_vat_total(self, invoice):
        _, vat, _ = invoice.line_totals()
        return str(vat) if invoice.lines.exists() else None

    def get_customer_email(self, invoice):
        if invoice.order_id:
            return invoice.order.customer.email
        if invoice.enrollment_id:
            return invoice.enrollment.customer.email
        return None

    def validate(self, attrs):
        order = attrs.get("order") or getattr(self.instance, "order", None)
        enrollment = attrs.get("enrollment") or getattr(self.instance, "enrollment", None)
        if not order and not enrollment:
            raise serializers.ValidationError("An Invoice must reference an order or an enrollment.")
        return attrs


class InvoiceDetailSerializer(InvoiceSerializer):
    payments = PaymentSerializer(many=True, read_only=True)
    lines = InvoiceLineSerializer(many=True, read_only=True)

    class Meta(InvoiceSerializer.Meta):
        fields = InvoiceSerializer.Meta.fields + ["payments", "lines"]
