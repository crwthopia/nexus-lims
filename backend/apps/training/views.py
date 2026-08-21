"""
Training/Enrollment/CreditNote endpoints (Blueprint Section 6: Training,
Credit Notes resource groups; Section 3.6, 4.3, 5.1, 5.2). Course/session
browsing is public (AllowAny) -- Blueprint Section 4.3: "Customer browses
Training catalog on Portal" happens before the customer necessarily has an
account; everything that commits money, personal data, or a credit balance
(enrolling, applying a credit) requires the relevant session.
"""

import csv

from django.http import HttpResponse
from django_fsm import TransitionNotAllowed
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.accounts.authentication import CustomerSessionAuthentication
from apps.accounts.models import Role
from apps.accounts.permissions import IsCustomerAuthenticated, roles_required
from apps.common.params import body_dict, int_param
from apps.training import services
from apps.training.models import CreditNote, Enrollment, TrainingCourse, TrainingSession
from apps.training.serializers import (
    CreditNoteSerializer,
    CustomerEnrollmentSerializer,
    EnrollmentSerializer,
    TrainingCourseSerializer,
    TrainingSessionSerializer,
)

RoleName = Role.RoleName
TRAINING_WRITE_ROLES = (RoleName.TRAINING_COORDINATOR, RoleName.LAB_SUPERVISOR, RoleName.SYSTEM_ADMINISTRATOR)


def _run_transition(instance, method_name):
    try:
        getattr(instance, method_name)()
    except TransitionNotAllowed as exc:
        raise ValidationError(f"Cannot perform '{method_name}' while status is '{instance.status}': {exc}")
    instance.save()


def _get_target_enrollment(request):
    enrollment_id = int_param(body_dict(request).get("enrollment"), "enrollment")
    if not enrollment_id:
        raise ValidationError("'enrollment' is required: the target Enrollment to apply this credit note to.")
    try:
        return Enrollment.objects.get(pk=enrollment_id)
    except Enrollment.DoesNotExist as exc:
        raise ValidationError("No such enrollment.") from exc


class TrainingCourseViewSet(viewsets.ModelViewSet):
    queryset = TrainingCourse.objects.all()
    serializer_class = TrainingCourseSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsAuthenticated(), roles_required(*TRAINING_WRITE_ROLES)()]


class TrainingSessionViewSet(viewsets.ModelViewSet):
    queryset = TrainingSession.objects.select_related("course", "instructor").prefetch_related("enrollments")
    serializer_class = TrainingSessionSerializer

    def get_queryset(self):
        """?status=, ?course= -- same filtering-gap pattern already fixed on Sample/TestRequest/Investigation/Instrument."""
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__in=status_param.split(","))
        course_id = int_param(self.request.query_params.get("course"), "course")
        if course_id is not None:
            qs = qs.filter(course_id=course_id)
        return qs

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsAuthenticated(), roles_required(*TRAINING_WRITE_ROLES)()]

    @action(detail=True, methods=["post"], url_path="start-session")
    def start_session(self, request, pk=None):
        session = self.get_object()
        _run_transition(session, "start_session")
        return Response(TrainingSessionSerializer(session).data)

    @action(detail=True, methods=["post"], url_path="complete-session")
    def complete_session(self, request, pk=None):
        session = self.get_object()
        _run_transition(session, "complete_session")
        return Response(TrainingSessionSerializer(session).data)

    @action(detail=True, methods=["post"], url_path="cancel-session")
    def cancel_session(self, request, pk=None):
        session = self.get_object()
        _run_transition(session, "cancel_session")
        return Response(TrainingSessionSerializer(session).data)

    @action(detail=True, methods=["get"], url_path="attendee-export")
    def attendee_export(self, request, pk=None):
        """
        GET /training-sessions/{id}/attendee-export/ -- Blueprint Section
        3.6/5.1 CPD Attendee Export CSV (name, PRC license number, course
        title, session date, CPD units). CustomerUser has no name field
        under the current schema (apps/accounts/models.py), so email is
        used as the attendee identifier column instead.
        """
        session = self.get_object()
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="attendee-export-session-{session.id}.csv"'
        writer = csv.writer(response)
        writer.writerow(["attendee_email", "prc_license_number", "course_title", "session_date", "cpd_units_earned"])
        for enrollment in session.enrollments.select_related("customer").filter(
            status__in=[Enrollment.Status.CONFIRMED, Enrollment.Status.COMPLETED]
        ):
            writer.writerow([
                enrollment.customer.email,
                enrollment.customer.prc_license_number or "",
                session.course.title,
                session.start_date.date().isoformat(),
                session.course.cpd_units,
            ])
        return response


class EnrollmentViewSet(viewsets.ModelViewSet):
    """Staff-facing: full visibility/management, e.g. registering a walk-in or correcting a discount."""

    queryset = Enrollment.objects.select_related("session__course", "customer")
    serializer_class = EnrollmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """?session=, ?status= -- needed by the Staff Console's Training Session detail enrollee list."""
        qs = super().get_queryset()
        session_id = int_param(self.request.query_params.get("session"), "session")
        if session_id is not None:
            qs = qs.filter(session_id=session_id)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__in=status_param.split(","))
        return qs

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy", "complete", "cancel"):
            return [IsAuthenticated(), roles_required(*TRAINING_WRITE_ROLES)()]
        return [IsAuthenticated()]

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """POST /enrollments/{id}/complete/ -- Training Coordinator marks attendance/completion (Section 4.3), issues the CPD certificate."""
        enrollment = self.get_object()
        _run_transition(enrollment, "mark_completed")
        enrollment.certificate_issued = True
        enrollment.save(update_fields=["certificate_issued"])
        return Response(EnrollmentSerializer(enrollment).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        enrollment = self.get_object()
        _run_transition(enrollment, "cancel")
        return Response(EnrollmentSerializer(enrollment).data)


class CustomerEnrollmentViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """GET/POST /my/enrollments/ -- customer self-enrollment (Blueprint Section 5.2 "My Trainings")."""

    serializer_class = CustomerEnrollmentSerializer
    authentication_classes = [CustomerSessionAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get_queryset(self):
        return Enrollment.objects.filter(customer=self.request.user).select_related("session__course")

    def perform_create(self, serializer):
        session = serializer.validated_data["session"]
        discount = services.compute_discount(self.request.user, session.course)
        serializer.save(customer=self.request.user, discount_applied=discount)


class CreditNoteViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /credit-notes/?customer_id= -- Blueprint Section 6's exact query param."""

    queryset = CreditNote.objects.select_related("customer", "source_enrollment", "applied_to_enrollment")
    serializer_class = CreditNoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        customer_id = int_param(self.request.query_params.get("customer_id"), "customer_id")
        if customer_id is not None:
            qs = qs.filter(customer_id=customer_id)
        return qs

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        """POST /credit-notes/{id}/apply/ -- staff applying a credit on a customer's behalf (e.g. over the phone)."""
        if not (request.user.is_superuser or request.user.roles.filter(name__in=TRAINING_WRITE_ROLES).exists()):
            raise PermissionDenied("Applying a credit note requires a Training Coordinator role.")
        credit_note = self.get_object()
        target_enrollment = _get_target_enrollment(request)
        try:
            services.apply_credit_note(credit_note, target_enrollment)
        except services.CreditNoteApplyError as exc:
            raise ValidationError(str(exc))
        return Response(CreditNoteSerializer(credit_note).data)


class CustomerCreditNoteViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /my/credit-notes/ -- Blueprint Section 6: "Customer (own)"."""

    serializer_class = CreditNoteSerializer
    authentication_classes = [CustomerSessionAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get_queryset(self):
        return CreditNote.objects.filter(customer=self.request.user)

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        """POST /my/credit-notes/{id}/apply/ -- Blueprint Section 5.2: "a redeem action to apply the credit toward a future session enrollment"."""
        credit_note = self.get_object()
        target_enrollment = _get_target_enrollment(request)
        try:
            services.apply_credit_note(credit_note, target_enrollment)
        except services.CreditNoteApplyError as exc:
            raise ValidationError(str(exc))
        return Response(CreditNoteSerializer(credit_note).data)
