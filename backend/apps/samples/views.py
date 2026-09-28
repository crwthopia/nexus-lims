"""
Sample/Order/ChainOfCustodyEvent endpoints (Blueprint Section 6: Orders,
Samples, Review/Approval resource groups).

The review/approve/reject/dispose actions live here rather than on a
review-app viewset because they must always happen atomically with the
Sample FSM transition and the segregation-of-duties guard (Blueprint
Section 2.1 item 3a) — keeping them on SampleViewSet means there is exactly
one write path that can move a Sample through review/approval, so the guard
can't be bypassed by posting a ReviewAction/ApprovalAction directly.
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django_fsm import TransitionNotAllowed
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from apps.accounts.authentication import CustomerSessionAuthentication
from apps.accounts.models import ESignature, Role
from apps.accounts.permissions import IsCustomerAuthenticated, roles_required
from apps.accounts.services import capture_esignature
from apps.billing import services as billing_services
from apps.billing.serializers import InvoiceDetailSerializer
from apps.billing.views import BILLING_WRITE_ROLES
from apps.catalogue.models import ServiceOffering
from apps.common.renderers import PdfRenderer
from apps.common.params import body_dict, bool_param, datetime_param, decimal_param, int_param, str_param
from apps.review.models import ApprovalAction, ReviewAction
from apps.review.serializers import ApprovalActionSerializer, ReviewActionSerializer
from apps.review.services import SegregationOfDutiesError, check_can_approve
from apps.notifications.tasks import notify_sample_progress
from apps.reporting.barcodes import BarcodeTooWide
from apps.samples import labels as label_services, order_services, receipt_services
from apps.samples.identity import UnknownServiceLine, allocate_sample_code
from apps.testing import holding_times
from apps.samples.models import (
    RECEIPT_CHECKS,
    ChainOfCustodyEvent,
    LabelPrintEvent,
    Order,
    Sample,
    SampleReceipt,
)
from apps.samples.serializers import (
    ChainOfCustodyEventSerializer,
    CustomerOrderDetailSerializer,
    OrderDetailSerializer,
    OrderItemSerializer,
    OrderSerializer,
    SampleDetailSerializer,
    SampleReceiptSerializer,
    SampleSerializer,
)

RoleName = Role.RoleName
# Ordering is intake work, so it takes the intake roles -- who books a
# sample in is who says what was ordered. Billing it is a different job
# with a different list (BILLING_WRITE_ROLES, apps/billing/views.py).
ORDER_ITEM_WRITE_ROLES = (RoleName.SAMPLE_RECEIVER, RoleName.LAB_SUPERVISOR, RoleName.SYSTEM_ADMINISTRATOR)
# Talking to a customer about a doubtful item, and deciding to refuse one,
# are intake decisions with a quality consequence -- so the receiving desk
# plus the two roles that already own nonconforming work elsewhere in this
# viewset. Deliberately not the Analyst: the point of ISO/IEC 17025:2017
# 7.4.3 is that this is settled before the item reaches a bench.
RECEIPT_RESOLUTION_ROLES = (RoleName.SAMPLE_RECEIVER, RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR)
# Printing an identity onto a physical container is intake work, and taking
# an aliquot to the bench is an analyst's -- both put a label on something,
# so both roles print. The supervisor is here for the same reason they are
# on every other list in this file: somebody has to be able to act when the
# person who normally would is not in.
LABEL_PRINT_ROLES = (
    RoleName.SAMPLE_RECEIVER, RoleName.ANALYST, RoleName.LAB_SUPERVISOR, RoleName.SYSTEM_ADMINISTRATOR,
)


def pdf_response(pdf_bytes, filename):
    """
    A rendered PDF, inline. Public because apps/testing/views.py prints
    worksheet labels through the same path -- the same reason
    BILLING_WRITE_ROLES is imported across apps above.

    `inline` rather than `attachment` so the browser's own print dialogue
    opens on it -- which is how a label reaches a label printer. An
    attachment saves a file somebody then has to find and open, and the
    extra step is where the wrong sample's labels get printed.
    """
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def print_labels_response(*, render, kind, request, filename, **target):
    """
    Render, record the print, return the PDF -- the shape every print
    endpoint shares, here and in apps/testing/views.py.

    Deliberately a POST, despite reading like a download: printing writes a
    LabelPrintEvent, and a GET that writes is a GET a browser may repeat,
    prefetch, or serve from cache. On this endpoint each of those is either
    a phantom reprint in the register or a label that never reaches the
    printer.

    The event is written *after* a successful render and inside the same
    transaction, so a barcode that will not fit leaves no trace of a print
    that never happened.
    """
    reason = str_param(body_dict(request).get("reason"), "reason")

    try:
        with transaction.atomic():
            pdf_bytes, pages = render()
            label_services.record_print(
                kind=kind, printed_by=request.user, copies=pages, reason=reason, **target,
            )
    except label_services.ReprintNeedsReason as exc:
        raise ValidationError({"reason": str(exc)}) from exc
    except BarcodeTooWide as exc:
        # A 400 rather than a 500: the request is answerable and the message
        # says what to do about it -- print this one on wider stock.
        raise ValidationError({"detail": str(exc)}) from exc

    return pdf_response(pdf_bytes, filename)


def _run_transition(sample, method_name):
    """Runs a django-fsm-2 @transition method, translating TransitionNotAllowed into an HTTP 400."""
    try:
        getattr(sample, method_name)()
    except TransitionNotAllowed as exc:
        raise ValidationError(
            f"Cannot perform '{method_name}' while Sample is '{sample.status}': {exc}"
        )
    sample.save()
    # Every Sample transition runs through here, so one call covers all ten
    # rather than ten actions each remembering to notify. Which milestones a
    # customer actually hears about -- and which are never sent
    # automatically -- is decided in apps/notifications/tasks.py.
    notify_sample_progress(sample)


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.select_related("customer").prefetch_related("items__offering")
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return OrderDetailSerializer if self.action == "retrieve" else OrderSerializer

    @action(detail=True, methods=["get", "post"], url_path="items")
    def items(self, request, pk=None):
        """
        GET/POST /orders/{id}/items/ -- what was ordered, and adding to it.

        POST takes an offering, a quantity and an optional discount, and
        nothing else: the price is snapshotted server-side from the rate in
        force (apps/samples/order_services.py). A client that could send a
        `unit_amount` could sell at any price it liked.
        """
        order = self.get_object()

        if request.method == "GET":
            return Response(OrderItemSerializer(order.items.select_related("offering"), many=True).data)

        if not (request.user.is_superuser or request.user.roles.filter(name__in=ORDER_ITEM_WRITE_ROLES).exists()):
            raise PermissionDenied(
                "Adding a line to an order requires the Sample Receiver, Lab Supervisor, "
                "or System Administrator role."
            )

        offering_id = int_param(body_dict(request).get("offering"), "offering")
        if not offering_id:
            raise ValidationError({"offering": "Required: the catalogue offering being ordered."})
        try:
            offering = ServiceOffering.objects.get(pk=offering_id, is_active=True)
        except ServiceOffering.DoesNotExist as exc:
            raise ValidationError({"offering": "No such active offering."}) from exc

        quantity = int_param(body_dict(request).get("quantity"), "quantity") or 1
        if quantity < 1:
            raise ValidationError({"quantity": "Must be at least 1."})
        discount = body_dict(request).get("discount_pct") or 0

        try:
            item = order_services.add_item(order, offering, quantity=quantity, discount_pct=Decimal(str(discount)))
        except order_services.Unpriced as exc:
            # A 400 rather than a 500: the request is answerable, the
            # catalogue just isn't ready for it, and the message says so.
            raise ValidationError({"offering": str(exc)}) from exc
        except InvalidOperation as exc:
            raise ValidationError({"discount_pct": "Expected a number."}) from exc

        return Response(OrderItemSerializer(item).data, status=status.HTTP_201_CREATED)


    @action(
        detail=True, methods=["post"], url_path="job-order",
        renderer_classes=[PdfRenderer, JSONRenderer],
    )
    def job_order(self, request, pk=None):
        """
        POST /orders/{id}/job-order/ — the A4 sheet that travels with the
        work: what was ordered per sample, the analyses in the order they
        have to be run, the condition each item arrived in, and signature
        blocks for the courier and the receiving officer.

        Printed rather than only displayed because those two signatures are
        the point. A custody handover happens at a counter between people,
        and no laboratory asks a courier to authenticate to a web
        application to acknowledge one.
        """
        order = self.get_object()

        if not (request.user.is_superuser or request.user.roles.filter(name__in=LABEL_PRINT_ROLES).exists()):
            raise PermissionDenied(
                "Printing a job order requires the Sample Receiver, Analyst, Lab Supervisor, "
                "or System Administrator role."
            )

        return print_labels_response(
            render=lambda: (label_services.render_job_order(order, printed_by=request.user), 1),
            kind=LabelPrintEvent.Kind.JOB_ORDER,
            request=request,
            filename=f"job-order-{order.id}.pdf",
            order=order,
        )

    @action(detail=True, methods=["post"], url_path="invoice")
    def invoice(self, request, pk=None):
        """
        POST /orders/{id}/invoice/ -- raise an invoice for everything on
        this order that has not been billed yet.

        Billing is a different job from ordering, so it takes the billing
        roles rather than the ordering ones.
        """
        order = self.get_object()

        if not (request.user.is_superuser or request.user.roles.filter(name__in=BILLING_WRITE_ROLES).exists()):
            raise PermissionDenied(
                "Raising an invoice requires the Training Coordinator, Lab Supervisor, "
                "or System Administrator role."
            )

        try:
            invoice = billing_services.invoice_order(order)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        return Response(InvoiceDetailSerializer(invoice).data, status=status.HTTP_201_CREATED)


class CustomerOrderViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /my/orders/ — Blueprint Section 6 Orders row: "Customer, Staff",
    "Customer (read own)". Filtered by CustomerUser.orders at the ORM layer
    *and* backed by the RLS policies on `order` (Blueprint Section 2.1 item
    3b) as defense in depth: even if this get_queryset() filter were ever
    dropped or bypassed by a future change, the database-level policy still
    only returns rows where order.customer_id matches the RLS session's
    rls.customer_id, which apps.accounts.middleware.RLSContextMiddleware
    sets from this same authenticated customer's session on every request.
    """

    serializer_class = OrderSerializer
    authentication_classes = [CustomerSessionAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get_serializer_class(self):
        return CustomerOrderDetailSerializer if self.action == "retrieve" else OrderSerializer

    def get_queryset(self):
        return (
            Order.objects.filter(customer=self.request.user)
            .prefetch_related("items__offering", "items__invoice_lines__invoice", "invoices")
        )


class CustomerSampleViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /my/samples/ — same defense-in-depth reasoning as CustomerOrderViewSet."""

    serializer_class = SampleSerializer
    authentication_classes = [CustomerSessionAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get_queryset(self):
        return Sample.objects.filter(order__customer=self.request.user)


class ChainOfCustodyEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ChainOfCustodyEvent.objects.select_related("sample", "from_holder", "to_holder")
    serializer_class = ChainOfCustodyEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        sample_id = int_param(self.request.query_params.get("sample"), "sample")
        if sample_id is not None:
            qs = qs.filter(sample_id=sample_id)
        return qs


class SampleViewSet(viewsets.ModelViewSet):
    queryset = Sample.objects.select_related("order").prefetch_related("chain_of_custody_events")
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        ?status= (e.g. the Staff Console's Review Queue: ?status=under_review),
        ?service_line=, and ?code= for the Receiving screen's scan lookup --
        DRF ignores unrecognized query params rather than erroring, so
        without this override these silently did nothing server-side even
        though a client sent them.
        """
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        service_line = self.request.query_params.get("service_line")
        if service_line:
            qs = qs.filter(service_line=service_line)
        code = str_param(self.request.query_params.get("code"), "code", max_length=64).strip()
        if code:
            # Exact, case-insensitively: this is what a barcode scanner
            # sends when somebody points it at a container, and the
            # Receiving screen looks a sample up by the only thing the
            # scanner knows. `iexact` rather than `exact` because the other
            # caller is a person typing the code off the label when the
            # scan fails, and a lowercase "we-202609-0042" is the same
            # bottle.
            #
            # Deliberately not `icontains`: a partial match would let a
            # scan of one code resolve to a different sample, which is the
            # confusion ISO/IEC 17025:2017 7.4.2 is about.
            qs = qs.filter(unique_sample_code__iexact=code)
        return qs

    # Per-action role requirements (Blueprint Section 7.1 RBAC / Section 5.1 role-aware screens).
    _ROLE_MAP = {
        "register": (RoleName.SAMPLE_RECEIVER,),
        "receive": (RoleName.SAMPLE_RECEIVER,),
        "start_prep": (RoleName.ANALYST,),
        "start_testing": (RoleName.ANALYST,),
        "submit_for_review": (RoleName.ANALYST,),
        "review": (RoleName.REVIEWER,),
        "approve": (RoleName.APPROVER,),
        "reject": (RoleName.APPROVER,),
        "reject_at_receipt": RECEIPT_RESOLUTION_ROLES,
        "receipt_consultation": RECEIPT_RESOLUTION_ROLES,
        "labels": LABEL_PRINT_ROLES,
        "print_labels": LABEL_PRINT_ROLES,
        "authorize_retest": (RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR),
        "dispose": (RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR),
        "requeue_for_retest": (RoleName.ANALYST, RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR),
    }

    def get_serializer_class(self):
        if self.action == "retrieve":
            return SampleDetailSerializer
        return SampleSerializer

    def get_permissions(self):
        roles = self._ROLE_MAP.get(self.action)
        if roles:
            return [IsAuthenticated(), roles_required(*roles)()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        """
        FR-C1-01 pre-registration. The identity is allocated here, not sent
        by the client -- see apps/samples/identity.py and the
        `unique_sample_code` note on SampleSerializer.

        `service_line` is read off validated_data rather than the request
        body so the prefix always matches the value that is actually
        stored; the serializer has already rejected anything that is not a
        valid ServiceLine by this point.
        """
        service_line = serializer.validated_data["service_line"]
        try:
            code = allocate_sample_code(service_line)
        except UnknownServiceLine as exc:
            # A 400: the request is answerable, the service line simply has
            # no code prefix defined yet, and the message says which.
            raise ValidationError({"service_line": str(exc)}) from exc
        serializer.save(unique_sample_code=code)

    # --- FR-C1 intake transitions ---

    @action(detail=True, methods=["post"])
    def register(self, request, pk=None):
        sample = self.get_object()
        _run_transition(sample, "register")
        return Response(SampleSerializer(sample).data)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """
        FR-C1-09: the physical item arrives.

        Three things happen together or not at all: the FSM moves to
        `received`, a SampleReceipt records what the item looked like
        (ISO/IEC 17025:2017 7.4.3), and the chain-of-custody timeline opens
        with a RECEIPT event. Atomic because a sample marked received with
        no arrival record is exactly the hole 7.4.3 exists to close, and
        the reverse -- a receipt for an item the FSM says never arrived --
        is worse.

        The body is parsed *before* the transition runs, so a malformed
        temperature leaves the sample where it was rather than moving it
        and then failing.

        `received_at` may be backdated to when the courier actually
        arrived, and may not be in the future. The checklist defaults to
        conforming; see receipt_services.record_receipt for why that
        default is the receiver's affirmation rather than an assumption.
        """
        sample = self.get_object()
        body = body_dict(request)

        received_at = datetime_param(body.get("received_at"), "received_at", not_future=True)
        observations = {
            "received_from": str_param(body.get("received_from"), "received_from", max_length=255),
            "condition_on_receipt": self._condition_param(body.get("condition_on_receipt")),
            "receipt_temperature_c": decimal_param(body.get("receipt_temperature_c"), "receipt_temperature_c"),
            "temperature_conforms": bool_param(body.get("temperature_conforms"), "temperature_conforms"),
            "storage_location": str_param(body.get("storage_location"), "storage_location", max_length=255),
            "deviations": str_param(body.get("deviations"), "deviations"),
        }
        for field, _phrasing in RECEIPT_CHECKS:
            observations[field] = bool_param(body.get(field), field, default=True)

        # Unsaved, and only ever asked which checks failed -- the row that
        # gets written is record_receipt's, below.
        probe = SampleReceipt(sample=sample, received_by=request.user, received_at=timezone.now(), **observations)
        if probe.deviation_reasons and not observations["deviations"].strip():
            # The CHECK constraint would catch this as an IntegrityError --
            # a 500 quoting a constraint name at somebody filling in a
            # form. 7.4.3 asks for the deviation to be *recorded*, so the
            # message says which check failed and asks for the words.
            raise ValidationError({
                "deviations": (
                    "Required when the item did not conform on receipt "
                    f"({'; '.join(probe.deviation_reasons)}). ISO/IEC 17025:2017 7.4.3 requires "
                    "deviations from specified conditions to be recorded."
                )
            })

        with transaction.atomic():
            _run_transition(sample, "receive")
            receipt_services.record_receipt(
                sample,
                received_by=request.user,
                received_at=received_at,
                location=str_param(body.get("location"), "location", max_length=255),
                **observations,
            )
            # received_at is set on the instance by record_receipt; the
            # transition's own save() has already run by then, so persist it.
            sample.save(update_fields=["received_at", "updated_at"])
            # The sample now has an anchor, so every test request already
            # booked against it gets its holding-time deadline. Requests
            # added *after* this point compute their own on create
            # (apps/testing/serializers.py) -- between them the two cover
            # both orders the inputs can arrive in.
            holding_times.apply_to_sample(sample)

        return Response(SampleDetailSerializer(sample).data)

    @staticmethod
    def _condition_param(value):
        """A SampleReceipt.Condition from the body, defaulting to intact."""
        if value is None or value == "":
            return SampleReceipt.Condition.INTACT
        if value not in SampleReceipt.Condition.values:
            raise ValidationError({
                "condition_on_receipt": f"Expected one of {', '.join(SampleReceipt.Condition.values)}."
            })
        return value

    @action(detail=True, methods=["post"], url_path="reject-at-receipt")
    def reject_at_receipt(self, request, pk=None):
        """
        POST /samples/{id}/reject-at-receipt/ — the laboratory declines the
        item (ISO/IEC 17025:2017 7.4.3).

        Legal from `registered` as well as `received`, and in the first
        case there is no SampleReceipt yet -- so one is written here. That
        is not a workaround: refusing an item *is* a receipt observation,
        the lab did take physical delivery, and an intake register that
        silently omitted every refused delivery would be the one document
        an assessor most wants to see.

        A reason is required and is stored as the receipt's deviation,
        alongside an e-signature: this is a decision about a customer's
        property, and 7.4.3 offers no version of it that is not written
        down.
        """
        sample = self.get_object()
        reason = str_param(body_dict(request).get("reason"), "reason").strip()
        if not reason:
            raise ValidationError({
                "reason": "Required: why the item was refused (ISO/IEC 17025:2017 7.4.3)."
            })

        with transaction.atomic():
            _run_transition(sample, "reject_at_receipt")

            receipt = getattr(sample, "receipt", None)
            if receipt is None:
                receipt = receipt_services.record_receipt(
                    sample,
                    received_by=request.user,
                    condition_on_receipt=SampleReceipt.Condition.OTHER,
                    deviations=reason,
                )
                sample.save(update_fields=["received_at", "updated_at"])
            else:
                # Append rather than replace: whatever the receiving clerk
                # observed at the counter is part of the same story as the
                # decision to refuse, and overwriting it would delete the
                # evidence for the decision being recorded.
                receipt.deviations = f"{receipt.deviations}\n\nRefused at receipt: {reason}".strip()
                if receipt.condition_on_receipt == SampleReceipt.Condition.INTACT:
                    receipt.condition_on_receipt = SampleReceipt.Condition.OTHER
                receipt.save()

            capture_esignature(
                signer=request.user,
                meaning=ESignature.Meaning.REJECTED,
                signed_entity_type="Sample",
                signed_entity_id=sample.id,
            )

        return Response(SampleDetailSerializer(sample).data)

    @action(detail=True, methods=["post"], url_path="receipt-consultation")
    def receipt_consultation(self, request, pk=None):
        """
        POST /samples/{id}/receipt-consultation/ — record what the customer
        said about a deviation found on receipt (ISO/IEC 17025:2017 7.4.3).

        This is the gate-opener: until it exists, check_can_begin_work
        refuses to let a nonconforming item start prep. `outcome` is
        mandatory because the standard asks for the outcome of the
        consultation, not the fact of it -- "called them" is not a record.

        Setting `authorised_despite_deviation` is what creates the
        reporting obligation, so `disclaimer_text` becomes mandatory with
        it: 7.4.3 wants the report to say *which results may be affected*,
        and a disclaimer that does not name them discharges nothing.

        Refuses outright on a conforming receipt. A consultation recorded
        against an item that arrived intact would sit in the record
        implying a doubt that was never raised, and would silently
        pre-open the gate for a later deviation.
        """
        sample = self.get_object()
        receipt = getattr(sample, "receipt", None)
        if receipt is None:
            raise ValidationError({
                "detail": "This sample has no receipt record yet. Receive it first.",
            })
        if receipt.is_conforming:
            raise ValidationError({
                "detail": "This item conformed on receipt, so there is nothing to consult the customer about.",
            })

        body = body_dict(request)
        outcome = str_param(body.get("outcome"), "outcome").strip()
        if not outcome:
            raise ValidationError({
                "outcome": (
                    "Required: what the customer instructed. ISO/IEC 17025:2017 7.4.3 requires the "
                    "outcome of the consultation to be recorded, not merely that it happened."
                )
            })

        authorised = bool_param(body.get("authorised_despite_deviation"), "authorised_despite_deviation", default=False)
        disclaimer = str_param(body.get("disclaimer_text"), "disclaimer_text").strip()
        if authorised and not disclaimer:
            raise ValidationError({
                "disclaimer_text": (
                    "Required when the customer authorises testing despite a deviation: ISO/IEC "
                    "17025:2017 7.4.3 requires the report to state which results may be affected."
                )
            })

        receipt.customer_consulted_at = (
            datetime_param(body.get("consulted_at"), "consulted_at", not_future=True) or timezone.now()
        )
        receipt.consultation_outcome = outcome
        receipt.customer_authorised_despite_deviation = authorised
        receipt.disclaimer_text = disclaimer
        receipt.save()

        return Response(SampleReceiptSerializer(receipt).data)

    @action(detail=True, methods=["post"], url_path="start-prep")
    def start_prep(self, request, pk=None):
        """
        FR-C1-13. Also the point where ISO/IEC 17025:2017 7.4.3's "consult
        the customer before proceeding" is enforced -- see
        receipt_services.check_can_begin_work for why the gate is here and
        not on receive.
        """
        sample = self.get_object()
        try:
            receipt_services.check_can_begin_work(sample)
        except receipt_services.ReceiptDeviationUnresolved as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        _run_transition(sample, "start_prep")
        return Response(SampleSerializer(sample).data)

    @action(detail=True, methods=["post"], url_path="start-testing")
    def start_testing(self, request, pk=None):
        sample = self.get_object()
        _run_transition(sample, "start_testing")
        return Response(SampleSerializer(sample).data)

    @action(detail=True, methods=["post"], url_path="submit-for-review")
    def submit_for_review(self, request, pk=None):
        sample = self.get_object()
        _run_transition(sample, "submit_for_review")
        return Response(SampleSerializer(sample).data)


    # --- FR-C1-02 labelling (ISO/IEC 17025:2017 7.4.2) ---

    @action(detail=True, methods=["post"], renderer_classes=[PdfRenderer, JSONRenderer])
    def labels(self, request, pk=None):
        """
        POST /samples/{id}/labels/ — container labels for this sample, as a
        PDF, one page per container.

        Rendered on the spot rather than queued. A report is worth a job and
        a poll; a label is printed by somebody standing at a bench with a
        cooler open in front of them, and "create a job, poll, download" is
        not a workflow that survives contact with that. Nothing is stored
        either -- see apps/samples/labels.py, but briefly: a stale label is
        worse than no label, because it is a container confidently asserting
        something the record no longer says.

        `copies` overrides the container count for the case the count does
        not cover -- a bottle whose label came off in the fridge.
        """
        sample = self.get_object()
        copies = int_param(body_dict(request).get("copies"), "copies")
        if copies is not None and copies < 1:
            raise ValidationError({"copies": "Must be at least 1."})

        return print_labels_response(
            render=lambda: label_services.render_container_labels([sample], copies=copies),
            kind=LabelPrintEvent.Kind.CONTAINER,
            request=request,
            filename=f"labels-{sample.unique_sample_code}.pdf",
            sample=sample,
        )

    @action(
        detail=False, methods=["post"], url_path="print-labels",
        renderer_classes=[PdfRenderer, JSONRenderer],
    )
    def print_labels(self, request, pk=None):
        """
        POST /samples/print-labels/ — container labels for several samples
        in one PDF.

        The endpoint that makes the feature usable: booking in a delivery of
        twelve samples and printing them one at a time is how a receiving
        bench goes back to a marker pen. One render, one print event per
        sample, so the register still answers "was this container labelled,
        and by whom" for each one individually.
        """
        ids = body_dict(request).get("samples")
        if not isinstance(ids, list) or not ids:
            raise ValidationError({"samples": "Required: a non-empty list of sample ids."})

        requested = [int_param(i, "samples") for i in ids]
        found = {s.id: s for s in self.get_queryset().filter(pk__in=requested)}

        missing = [i for i in requested if i not in found]
        if missing:
            # Named rather than silently skipped: a batch that quietly
            # prints eleven of the twelve labels asked for is a sample that
            # goes into a fridge unlabelled.
            raise ValidationError({"samples": f"No such sample(s): {sorted(set(missing))}."})

        # In the order the caller asked for them, not the model's
        # newest-first default. The list a receiving clerk sends is the
        # order the containers are lined up in on the bench, and labels
        # coming off the printer in some other order is how the third
        # bottle gets the second one's identity. dict.fromkeys drops a
        # repeated id rather than printing that sample twice.
        samples = [found[i] for i in dict.fromkeys(requested)]

        reason = str_param(body_dict(request).get("reason"), "reason")
        try:
            with transaction.atomic():
                pdf_bytes, pages = label_services.render_container_labels(samples)
                for sample in samples:
                    label_services.record_print(
                        kind=LabelPrintEvent.Kind.CONTAINER,
                        printed_by=request.user,
                        copies=sample.container_count or 1,
                        reason=reason,
                        sample=sample,
                    )
        except label_services.ReprintNeedsReason as exc:
            raise ValidationError({"reason": str(exc)}) from exc
        except BarcodeTooWide as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        return pdf_response(pdf_bytes, f"labels-{len(samples)}-samples.pdf")

    # --- FR-C4/C5 review and approval (Blueprint Section 6 endpoint table) ---

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        """
        POST /samples/{id}/review — FR-C4-04. Records a ReviewAction and its
        e-signature. Does not itself move Sample.status; a Sample only
        reaches approved/under_investigation via approve/reject below, once
        at least one ReviewAction exists.
        """
        sample = self.get_object()
        if sample.status != Sample.Status.UNDER_REVIEW:
            raise ValidationError(
                f"Sample must be 'under_review' to record a ReviewAction (currently '{sample.status}')."
            )

        review_action = ReviewAction.objects.create(
            sample=sample,
            reviewer=request.user,
            action=ReviewAction.Action.REVIEWED,
            comments=str_param(body_dict(request).get("comments"), "comments"),
        )
        signature = capture_esignature(
            signer=request.user,
            meaning=ESignature.Meaning.REVIEWED,
            signed_entity_type="Sample",
            signed_entity_id=sample.id,
        )
        review_action.e_signature = signature
        review_action.save(update_fields=["e_signature"])
        return Response(ReviewActionSerializer(review_action).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """
        POST /samples/{id}/approve — FR-C5-01 to C5-04. Runs the
        segregation-of-duties guard (Blueprint Section 2.1 item 3a) before
        the FSM transition, so a rejected guard never leaves Sample.status
        changed.
        """
        sample = self.get_object()
        try:
            check_can_approve(sample, request.user)
        except SegregationOfDutiesError as exc:
            raise ValidationError(str(exc))

        _run_transition(sample, "approve")

        signature = capture_esignature(
            signer=request.user,
            meaning=ESignature.Meaning.APPROVED,
            signed_entity_type="Sample",
            signed_entity_id=sample.id,
        )
        approval_action = ApprovalAction.objects.create(
            sample=sample,
            approver=request.user,
            disposition=ApprovalAction.Disposition.APPROVED,
            e_signature=signature,
        )
        return Response(ApprovalActionSerializer(approval_action).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """
        POST /samples/{id}/reject — routes to under_investigation per
        ISO/IEC 17025:2017 7.10 (Blueprint Section 2.1 item 3a, closes
        Section 13 gap 12), not directly to retest_pending.
        """
        sample = self.get_object()
        _run_transition(sample, "reject")

        signature = capture_esignature(
            signer=request.user,
            meaning=ESignature.Meaning.REJECTED,
            signed_entity_type="Sample",
            signed_entity_id=sample.id,
        )
        approval_action = ApprovalAction.objects.create(
            sample=sample,
            approver=request.user,
            disposition=ApprovalAction.Disposition.REJECTED,
            e_signature=signature,
        )
        return Response(ApprovalActionSerializer(approval_action).data, status=status.HTTP_201_CREATED)

    # --- ISO 7.10 nonconforming-work resolution (QA Officer / Lab Supervisor only) ---

    @action(detail=True, methods=["post"], url_path="authorize-retest")
    def authorize_retest(self, request, pk=None):
        sample = self.get_object()
        _run_transition(sample, "authorize_retest")
        return Response(SampleSerializer(sample).data)

    @action(detail=True, methods=["post"])
    def dispose(self, request, pk=None):
        sample = self.get_object()
        _run_transition(sample, "dispose")
        capture_esignature(
            signer=request.user,
            meaning=ESignature.Meaning.DISPOSED,
            signed_entity_type="Sample",
            signed_entity_id=sample.id,
        )
        return Response(SampleSerializer(sample).data)

    @action(detail=True, methods=["post"], url_path="requeue-for-retest")
    def requeue_for_retest(self, request, pk=None):
        sample = self.get_object()
        _run_transition(sample, "requeue_for_retest")
        return Response(SampleSerializer(sample).data)
