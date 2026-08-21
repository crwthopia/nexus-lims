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

from django_fsm import TransitionNotAllowed
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.authentication import CustomerSessionAuthentication
from apps.accounts.models import ESignature, Role
from apps.accounts.permissions import IsCustomerAuthenticated, roles_required
from apps.accounts.services import capture_esignature
from apps.common.params import body_dict, int_param, str_param
from apps.review.models import ApprovalAction, ReviewAction
from apps.review.serializers import ApprovalActionSerializer, ReviewActionSerializer
from apps.review.services import SegregationOfDutiesError, check_can_approve
from apps.samples.models import ChainOfCustodyEvent, Order, Sample
from apps.samples.serializers import (
    ChainOfCustodyEventSerializer,
    OrderSerializer,
    SampleDetailSerializer,
    SampleSerializer,
)

RoleName = Role.RoleName


def _run_transition(sample, method_name):
    """Runs a django-fsm-2 @transition method, translating TransitionNotAllowed into an HTTP 400."""
    try:
        getattr(sample, method_name)()
    except TransitionNotAllowed as exc:
        raise ValidationError(
            f"Cannot perform '{method_name}' while Sample is '{sample.status}': {exc}"
        )
    sample.save()


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.select_related("customer")
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]


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

    def get_queryset(self):
        return Order.objects.filter(customer=self.request.user)


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
        ?status= (e.g. the Staff Console's Review Queue: ?status=under_review)
        and ?service_line= -- DRF ignores unrecognized query params rather
        than erroring, so without this override these silently did nothing
        server-side even though a client sent them.
        """
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        service_line = self.request.query_params.get("service_line")
        if service_line:
            qs = qs.filter(service_line=service_line)
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

    # --- FR-C1 intake transitions ---

    @action(detail=True, methods=["post"])
    def register(self, request, pk=None):
        sample = self.get_object()
        _run_transition(sample, "register")
        return Response(SampleSerializer(sample).data)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """FR-C1-09: physical sample arrives; also opens the chain-of-custody timeline."""
        sample = self.get_object()
        _run_transition(sample, "receive")
        ChainOfCustodyEvent.objects.create(
            sample=sample,
            to_holder=request.user,
            to_location=str_param(body_dict(request).get("location"), "location", max_length=255),
            event_type=ChainOfCustodyEvent.EventType.RECEIPT,
        )
        return Response(SampleSerializer(sample).data)

    @action(detail=True, methods=["post"], url_path="start-prep")
    def start_prep(self, request, pk=None):
        sample = self.get_object()
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
