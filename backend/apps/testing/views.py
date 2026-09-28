"""
TestMethod/TestRequest/TestResult endpoints (Blueprint Section 6: Test
Requests / Results resource group).
"""

from django.db.models import Case, F, IntegerField, Value, When
from django.utils import timezone
from django_fsm import TransitionNotAllowed
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.accounts.permissions import roles_required
from apps.audit.oss import upload_object
from apps.common.params import body_dict, int_param
from apps.equipment.models import Instrument
from apps.samples import labels as label_services
from apps.samples.models import LabelPrintEvent, Sample
from apps.samples.views import LABEL_PRINT_ROLES, print_labels_response
from apps.testing import holding_times
from apps.testing.ingestion import (
    IngestionError,
    assert_certified,
    checksum,
    object_key_for,
    parser_for,
)
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


# Methods are controlled data, not ordinary master data: specification_limits
# decide whether a result is in or out of specification. Same pair as
# DOCUMENT_WRITE_ROLES -- QA owns the controlled set, the supervisor can act
# when QA is unavailable.
TEST_METHOD_WRITE_ROLES = (RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR)


class TestMethodViewSet(viewsets.ModelViewSet):
    """
    Master data (Blueprint Section 3.2, D-1-5), and controlled data: a
    TestMethod carries the specification_limits a result is judged against,
    so editing one changes which results pass. ISO/IEC 17025 Section 7.2
    puts methods under the same control as documented procedures, which is
    why writes here take the same roles as DocumentViewSet rather than the
    bare IsAuthenticated this had.

    Reading stays open to any authenticated staff member -- an analyst needs
    to see the method they are running.
    """

    queryset = TestMethod.objects.all()
    serializer_class = TestMethodSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsAuthenticated(), roles_required(*TEST_METHOD_WRITE_ROLES)()]


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

    def get_queryset(self):
        """
        ?sample= (Sample detail's Test Requests panel), ?status= --
        comma-separated, so the Staff Console's Testing Queue can ask for
        "needs an analyst" (assigned,in_progress) in one request -- and
        ?overdue=true for work already past its holding time. Same class
        of gap as SampleViewSet before it grew this override: DRF ignores
        unrecognized query params rather than erroring, so without this a
        client-sent filter would silently do nothing server-side.

        Results come back in _QUEUE_ORDER (below) rather than the model's
        newest-first default. A testing queue sorted by creation date is a
        list of what was booked in; sorted by deadline it is a statement of
        what to do next, which is the only version worth putting in front
        of an analyst.
        """
        qs = super().get_queryset()
        sample_id = int_param(self.request.query_params.get("sample"), "sample")
        if sample_id is not None:
            qs = qs.filter(sample_id=sample_id)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__in=status_param.split(","))
        if self.request.query_params.get("overdue") == "true":
            qs = qs.filter(
                status__in=holding_times.OUTSTANDING_STATUSES, due_at__lt=timezone.now(),
            )
        return qs.order_by(*self._QUEUE_ORDER)

    # Priority is a TextChoices, so ordering by the column sorts it
    # alphabetically -- emergency, routine, rush -- which puts routine work
    # ahead of a rush. An explicit rank fixes that without making the API
    # send integers at clients that have to display words.
    _PRIORITY_RANK = Case(
        When(sample__priority=Sample.Priority.EMERGENCY, then=Value(0)),
        When(sample__priority=Sample.Priority.RUSH, then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    )

    # What an analyst should pick up next, in the order the two constraints
    # actually bind:
    #
    #   1. Priority, because it is what the customer was sold.
    #   2. Holding-time deadline, soonest first -- and this is the half that
    #      makes the queue a control rather than a list. Nulls last, since a
    #      method with no holding time has nothing being lost by waiting.
    #   3. Creation order, so the sort is total and the page is stable
    #      between reads.
    #
    # Priority above due_at is a deliberate choice and not an obvious one.
    # It is right because a breach is not silent -- the hourly sweep
    # (apps/notifications/tasks.sweep_holding_times) chases anything about
    # to expire regardless of where it sits here, so the queue does not have
    # to be the only thing standing between an analysis and its deadline.
    _QUEUE_ORDER = (_PRIORITY_RANK, F("due_at").asc(nulls_last=True), "created_at")

    _ROLE_MAP = {
        "start": (RoleName.ANALYST,),
        "submit_for_review": (RoleName.ANALYST,),
        "flag_nonconforming": (RoleName.REVIEWER, RoleName.QA_OFFICER),
        "authorize_retest": (RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR),
        "resume_testing": (RoleName.ANALYST,),
        # Ingesting a file creates results, so it is gated like entering
        # them by hand.
        "ingest": (RoleName.ANALYST,),
        "complete": (RoleName.REVIEWER, RoleName.APPROVER, RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR),
        "label": LABEL_PRINT_ROLES,
    }

    def get_permissions(self):
        roles = self._ROLE_MAP.get(self.action)
        if roles:
            return [IsAuthenticated(), roles_required(*roles)()]
        return [IsAuthenticated()]

    @action(detail=True, methods=["post"])
    def label(self, request, pk=None):
        """
        POST /test-requests/{id}/label/ — a worksheet label for the portion
        taken to run this analysis.

        ISO/IEC 17025:2017 7.4.2 requires the identification system to
        accommodate subdivision of an item, and this is it: the barcode
        still carries the parent sample code, so scanning a tube on the
        bench lands on the same record scanning the bottle does, while the
        suffix and the method name tell the analyst which of the three
        tubes in front of them is which.
        """
        test_request = self.get_object()
        copies = int_param(body_dict(request).get("copies"), "copies") or 1
        if copies < 1:
            raise ValidationError({"copies": "Must be at least 1."})

        return print_labels_response(
            render=lambda: label_services.render_worksheet_labels(test_request, copies=copies),
            kind=LabelPrintEvent.Kind.WORKSHEET,
            request=request,
            filename=f"worksheet-{test_request.sample.unique_sample_code}-{test_request.id}.pdf",
            test_request=test_request,
        )

    @action(detail=True, methods=["get", "post"])
    def results(self, request, pk=None):
        """GET/POST /test-requests/{id}/results — FR-C3-03, FR-C3-06."""
        test_request = self.get_object()
        if request.method == "GET":
            results = test_request.results.all()
            return Response(TestResultSerializer(results, many=True, context={"request": request}).data)

        serializer = TestResultSerializer(
            data={**body_dict(request), "test_request": test_request.id},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser])
    def ingest(self, request, pk=None):
        """
        POST /test-requests/{id}/ingest — an instrument export file in,
        TestResult rows out (Blueprint Section 11).

        Synchronous, unlike report generation. An analyst uploading an
        export is standing at the instrument waiting to learn whether the
        file was accepted; answering "queued" and making them poll for a
        parse error they could have been told about immediately is worse
        than holding the request for the second it takes. Report generation
        is fire-and-forget and genuinely slow, which is why that one is a
        task and this one isn't.

        The raw file is stored before parsing, and stored even though the
        parse may fail: ALCOA traceability (Section 7.3) wants the artifact
        the lab actually received, including the one that turned out to be
        malformed.
        """
        test_request = self.get_object()
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "No file was uploaded."})

        content = upload.read()
        if not content:
            raise ValidationError({"file": "Uploaded file is empty."})

        digest = checksum(content)
        if test_request.results.filter(raw_file_checksum_sha256=digest).exists():
            # Re-uploading the same export would double every result on the
            # request. In a regulated record that is a data-integrity
            # incident, not a convenience.
            return Response(
                {
                    "detail": "This exact file has already been ingested for this test request.",
                    "checksum_sha256": digest,
                },
                status=status.HTTP_409_CONFLICT,
            )

        instrument = None
        instrument_id = int_param(body_dict(request).get("instrument"), "instrument")
        if instrument_id is not None:
            instrument = Instrument.objects.filter(pk=instrument_id).first()
            if instrument is None:
                raise ValidationError({"instrument": f"No instrument with id {instrument_id}."})

        try:
            assert_certified(request.user, test_request.test_method)
        except IngestionError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        key = object_key_for(test_request, digest)
        upload_object(key, content, content_type=upload.content_type or "text/csv")

        try:
            rows = parser_for(instrument)(content, test_request.test_method)
        except IngestionError as exc:
            # 400 with the parser's own message: "row 4: value 'n/a' is not
            # numeric" is actionable, "could not parse file" is not.
            raise ValidationError({"detail": str(exc)}) from exc

        created = TestResult.objects.bulk_create(
            [
                TestResult(
                    test_request=test_request,
                    entered_by=request.user,
                    instrument=instrument,
                    raw_file_id=key,
                    raw_file_checksum_sha256=digest,
                    **row,
                )
                for row in rows
            ]
        )

        return Response(
            {
                "created": len(created),
                "raw_file_id": key,
                "checksum_sha256": digest,
                "results": TestResultSerializer(created, many=True, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )

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
