"""
TestMethod/TestRequest/TestResult endpoints (Blueprint Section 6: Test
Requests / Results resource group).
"""

from django_fsm import TransitionNotAllowed
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.accounts.permissions import roles_required
from apps.testing.models import TestMethod, TestRequest, TestResult
from apps.testing.serializers import TestMethodSerializer, TestRequestSerializer, TestResultSerializer

RoleName = Role.RoleName


def _run_transition(test_request, method_name):
    try:
        getattr(test_request, method_name)()
    except TransitionNotAllowed as exc:
        raise ValidationError(
            f"Cannot perform '{method_name}' while TestRequest is '{test_request.status}': {exc}"
        )
    test_request.save()


class TestMethodViewSet(viewsets.ModelViewSet):
    queryset = TestMethod.objects.all()
    serializer_class = TestMethodSerializer
    permission_classes = [IsAuthenticated]


class TestResultViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Read-only at the top level; creation happens exclusively through
    TestRequestViewSet.results (POST /test-requests/{id}/results, matching
    the Blueprint Section 6 endpoint table), so entered_by/is_out_of_spec
    are always derived server-side rather than settable via a generic
    top-level POST.
    """

    queryset = TestResult.objects.select_related("test_request", "entered_by", "instrument")
    serializer_class = TestResultSerializer
    permission_classes = [IsAuthenticated]


class TestRequestViewSet(viewsets.ModelViewSet):
    queryset = TestRequest.objects.select_related("sample", "test_method", "assigned_analyst", "assigned_instrument")
    serializer_class = TestRequestSerializer
    permission_classes = [IsAuthenticated]

    _ROLE_MAP = {
        "start": (RoleName.ANALYST,),
        "submit_for_review": (RoleName.ANALYST,),
        "flag_nonconforming": (RoleName.REVIEWER, RoleName.QA_OFFICER),
        "authorize_retest": (RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR),
        "resume_testing": (RoleName.ANALYST,),
        "complete": (RoleName.REVIEWER, RoleName.APPROVER, RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR),
    }

    def get_permissions(self):
        roles = self._ROLE_MAP.get(self.action)
        if roles:
            return [IsAuthenticated(), roles_required(*roles)()]
        return [IsAuthenticated()]

    @action(detail=True, methods=["get", "post"])
    def results(self, request, pk=None):
        """GET/POST /test-requests/{id}/results — FR-C3-03, FR-C3-06."""
        test_request = self.get_object()
        if request.method == "GET":
            results = test_request.results.all()
            return Response(TestResultSerializer(results, many=True, context={"request": request}).data)

        serializer = TestResultSerializer(
            data={**request.data, "test_request": test_request.id},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        test_request = self.get_object()
        _run_transition(test_request, "start")
        return Response(TestRequestSerializer(test_request).data)

    @action(detail=True, methods=["post"], url_path="submit-for-review")
    def submit_for_review(self, request, pk=None):
        test_request = self.get_object()
        _run_transition(test_request, "submit_for_review")
        return Response(TestRequestSerializer(test_request).data)

    @action(detail=True, methods=["post"], url_path="flag-nonconforming")
    def flag_nonconforming(self, request, pk=None):
        test_request = self.get_object()
        _run_transition(test_request, "flag_nonconforming")
        return Response(TestRequestSerializer(test_request).data)

    @action(detail=True, methods=["post"], url_path="authorize-retest")
    def authorize_retest(self, request, pk=None):
        test_request = self.get_object()
        _run_transition(test_request, "authorize_retest")
        return Response(TestRequestSerializer(test_request).data)

    @action(detail=True, methods=["post"], url_path="resume-testing")
    def resume_testing(self, request, pk=None):
        test_request = self.get_object()
        _run_transition(test_request, "resume_testing")
        return Response(TestRequestSerializer(test_request).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        test_request = self.get_object()
        _run_transition(test_request, "complete")
        return Response(TestRequestSerializer(test_request).data)
