from rest_framework import serializers

from apps.billing.models import Invoice, Payment


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


class InvoiceSerializer(serializers.ModelSerializer):
    """customer_email: read-only display convenience -- an Invoice bills either an Order or an Enrollment (never both), so this resolves whichever is set rather than making a list UI look up two different resources to identify who's being billed."""

    customer_email = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = ["id", "order", "enrollment", "customer_email", "amount", "currency", "status", "created_at"]
        # status is read-only: it's only ever changed by confirming a Payment
        # (POST /invoices/{id}/payments/), not by direct PATCH, so it can't
        # drift out of sync with what payments were actually recorded.
        read_only_fields = ["id", "status", "created_at"]

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

    class Meta(InvoiceSerializer.Meta):
        fields = InvoiceSerializer.Meta.fields + ["payments"]
