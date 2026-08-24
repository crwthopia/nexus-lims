"""
ISO/IEC 17025:2017 7.11.3(e): system failures, and the immediate and
corrective actions, are recorded.

Three things are being tested, and they are different claims:

  the recorder   writes a durable row, coalesces a repeat, and never raises
                 -- a failure recorder that can itself fail is a second
                 outage;
  the wiring     the places that already detected failures now record them,
                 including the two that swallow the error and so never reach
                 Celery's task_failure signal;
  the workflow   a failure cannot be closed with nothing written against it,
                 which is the half of the clause a status column alone
                 does not satisfy.
"""

import pytest
from django.db import DatabaseError, connection, transaction

from apps.audit import failures as failures_module
from apps.audit.failures import record_failure
from apps.audit.models import SystemFailure
from tests.factories import StaffUserFactory

pytestmark = pytest.mark.django_db

Component = SystemFailure.Component
Severity = SystemFailure.Severity
ImmediateAction = SystemFailure.ImmediateAction
Status = SystemFailure.Status


def _a_failure(**overrides):
    return record_failure(
        overrides.pop("component", Component.OBJECT_STORAGE),
        overrides.pop("summary", "archive_object raised EndpointConnectionError"),
        detail=overrides.pop("detail", "TestResult#4: could not connect"),
        severity=overrides.pop("severity", Severity.DEGRADED),
        immediate_action=overrides.pop("immediate_action", ImmediateAction.RETRY_SCHEDULED),
        **overrides,
    )


# --- The recorder ---------------------------------------------------------

def test_a_failure_is_recorded_with_what_the_system_did_about_it():
    failure = _a_failure()

    assert failure.component == Component.OBJECT_STORAGE
    assert failure.severity == Severity.DEGRADED
    # The half of 7.11.3(e) the system answers by itself.
    assert failure.immediate_action == ImmediateAction.RETRY_SCHEDULED
    # The half a person owes, deliberately empty until they write it.
    assert failure.corrective_action == ""
    assert failure.status == Status.OPEN
    assert failure.occurrences == 1


def test_a_repeat_bumps_the_counter_rather_than_writing_a_second_row():
    """A failing dependency probed every few seconds must not be thousands of rows."""
    first = _a_failure()
    for _ in range(4):
        _a_failure()

    assert SystemFailure.objects.count() == 1
    first.refresh_from_db()
    assert first.occurrences == 5
    assert first.last_seen_at > first.first_seen_at or first.last_seen_at is not None


def test_a_different_failure_is_its_own_row():
    _a_failure()
    _a_failure(summary="archive_object raised ClientError")

    assert SystemFailure.objects.count() == 2


def test_a_recurrence_after_acknowledgement_opens_a_new_row():
    """
    The rule the whole dedup design turns on. A failure coming back after
    somebody looked at it is the most useful thing this table can say, so it
    must not be absorbed into the row they already signed off.
    """
    first = _a_failure()
    first.status = Status.ACKNOWLEDGED
    first.save(update_fields=["status"])

    second = _a_failure()

    assert second.pk != first.pk
    assert SystemFailure.objects.count() == 2
    first.refresh_from_db()
    assert first.occurrences == 1


def test_a_recurrence_after_closure_opens_a_new_row():
    first = _a_failure()
    first.status = Status.CLOSED
    first.corrective_action = "Credentials rotated."
    first.save(update_fields=["status", "corrective_action"])

    second = _a_failure()

    assert second.pk != first.pk


def test_recording_a_failure_never_raises(monkeypatch):
    """
    The first rule of the module: recording a failure must not cause one.
    If this ever raises, a degraded dependency becomes a 500 and a task that
    failed once fails twice, with the second traceback hiding the first.
    """
    def _explode(*args, **kwargs):
        raise DatabaseError("the database is exactly what is down")

    monkeypatch.setattr(SystemFailure.objects, "filter", _explode)

    assert record_failure(Component.DATABASE, "anything at all") is None


def test_the_summary_is_what_decides_coalescing_not_the_detail():
    _a_failure(detail="TestResult#1")
    _a_failure(detail="TestResult#2")

    assert SystemFailure.objects.count() == 1


# --- The wiring -----------------------------------------------------------

def test_the_health_probe_component_names_are_real_enum_members():
    """
    apps/common/health.py refers to components by string rather than by
    importing the model, so the probes keep the fewest import-time
    dependencies in the process. This is the check that keeps those strings
    honest -- a renamed enum member would otherwise leave health.py writing
    a component nothing recognises.
    """
    from apps.common import health

    valid_components = set(Component.values)
    assert set(health._COMPONENTS.values()) <= valid_components
    assert health._REMOVED_FROM_ROTATION in set(ImmediateAction.values)


def test_a_failing_readiness_check_is_recorded(monkeypatch, client):
    def _redis_is_down():
        raise ConnectionError("Error 111 connecting to redis:6379. Connection refused.")

    monkeypatch.setattr("apps.common.health._check_redis", _redis_is_down)

    response = client.get("/readyz")

    assert response.status_code == 503
    failure = SystemFailure.objects.get(component=Component.TASK_BROKER)
    assert failure.immediate_action == ImmediateAction.REMOVED_FROM_ROTATION
    assert "ConnectionError" in failure.summary


def test_repeated_readiness_failures_are_one_row(monkeypatch, client):
    """A load balancer probes constantly; the register must not drown in it."""
    monkeypatch.setattr(
        "apps.common.health._check_redis",
        lambda: (_ for _ in ()).throw(ConnectionError("refused")),
    )

    for _ in range(5):
        client.get("/readyz")

    assert SystemFailure.objects.filter(component=Component.TASK_BROKER).count() == 1


def test_a_celery_task_failure_is_recorded():
    """
    The signal receiver is what covers tasks nobody remembered to wrap --
    including report generation, which marks its own row and re-raises.
    """
    from config.celery import _record_task_failure

    class _Sender:
        name = "apps.reporting.tasks.generate_report_pdf"

    _record_task_failure(
        sender=_Sender(), task_id="abc-123", exception=ValueError("template exploded"), einfo=None,
    )

    failure = SystemFailure.objects.get(component=Component.REPORT_GENERATION)
    assert failure.summary == "apps.reporting.tasks.generate_report_pdf raised ValueError"
    assert failure.immediate_action == ImmediateAction.MARKED_FAILED
    assert "abc-123" in failure.detail


def test_an_unknown_task_is_recorded_as_a_scheduled_task():
    from config.celery import _record_task_failure

    class _Sender:
        name = "apps.something.tasks.added_later"

    _record_task_failure(sender=_Sender(), task_id="x", exception=RuntimeError("boom"), einfo=None)

    assert SystemFailure.objects.filter(component=Component.SCHEDULED_TASK).exists()


def test_object_storage_being_unconfigured_during_the_sweep_is_recorded(monkeypatch):
    """
    The retention sweep swallows this deliberately so the rest of the sweep
    carries on, which means the task succeeds and task_failure never fires.
    A retention action that silently did not happen is exactly what
    7.11.3(e) exists for.
    """
    from apps.audit import tasks
    from apps.audit.oss import OSSNotConfiguredError

    monkeypatch.setattr(tasks, "_object_key_for", lambda *a: "reports/x.pdf")
    monkeypatch.setattr(
        tasks, "archive_object",
        lambda key: (_ for _ in ()).throw(OSSNotConfiguredError("OSS_ENDPOINT is not set")),
    )

    assert tasks._move_to_cold_storage_tier("Report", 7) is False

    failure = SystemFailure.objects.get(component=Component.OBJECT_STORAGE)
    assert failure.severity == Severity.DEGRADED
    assert failure.immediate_action == ImmediateAction.RETRY_SCHEDULED


def test_an_unhandled_request_exception_is_recorded_against_the_route_not_the_path():
    """
    Fingerprinting on the path would file one broken endpoint as one failure
    per row it was called with.
    """
    from apps.audit.failures import record_request_exception

    class _Match:
        route = "api/v1/samples/<pk>/"

    class _Request:
        method = "GET"
        resolver_match = _Match()

    try:
        raise KeyError("missing")
    except KeyError:
        record_request_exception(request=_Request())

    failure = SystemFailure.objects.get(component=Component.API_REQUEST)
    assert failure.summary == "GET api/v1/samples/<pk>/ raised KeyError"
    assert failure.immediate_action == ImmediateAction.REQUEST_REJECTED


# --- The workflow ---------------------------------------------------------

def test_any_authenticated_staff_can_read_the_register(login_as_staff):
    _a_failure()
    client = login_as_staff(StaffUserFactory(roles=["analyst"]))

    response = client.get("/api/v1/system-failures/")

    assert response.status_code == 200
    assert response.data["count"] == 1


def test_acknowledging_requires_qa_officer_or_lab_supervisor(login_as_staff):
    failure = _a_failure()
    client = login_as_staff(StaffUserFactory(roles=["analyst"]))

    response = client.post(f"/api/v1/system-failures/{failure.id}/acknowledge/")

    assert response.status_code == 403


def test_acknowledging_records_who_and_when(login_as_staff):
    failure = _a_failure()
    qa = StaffUserFactory(roles=["qa_officer"])
    client = login_as_staff(qa)

    response = client.post(f"/api/v1/system-failures/{failure.id}/acknowledge/")

    assert response.status_code == 200
    failure.refresh_from_db()
    assert failure.status == Status.ACKNOWLEDGED
    assert failure.acknowledged_by == qa
    assert failure.acknowledged_at is not None


def test_a_failure_cannot_be_closed_without_a_corrective_action(login_as_staff):
    """
    The rule that makes this a 7.11.3(e) register rather than a list of
    things that stopped being annoying.
    """
    failure = _a_failure()
    client = login_as_staff(StaffUserFactory(roles=["qa_officer"]))

    response = client.post(f"/api/v1/system-failures/{failure.id}/close/")

    assert response.status_code == 400
    assert "corrective_action" in response.data
    failure.refresh_from_db()
    assert failure.status == Status.OPEN


def test_whitespace_is_not_a_corrective_action(login_as_staff):
    failure = _a_failure()
    client = login_as_staff(StaffUserFactory(roles=["qa_officer"]))

    response = client.post(
        f"/api/v1/system-failures/{failure.id}/close/", {"corrective_action": "   "}, format="json",
    )

    assert response.status_code == 400


def test_closing_with_a_corrective_action_records_who_and_when(login_as_staff):
    failure = _a_failure()
    qa = StaffUserFactory(roles=["qa_officer"])
    client = login_as_staff(qa)

    response = client.post(
        f"/api/v1/system-failures/{failure.id}/close/",
        {"corrective_action": "OSS credentials rotated and the endpoint corrected in the deployment env."},
        format="json",
    )

    assert response.status_code == 200
    failure.refresh_from_db()
    assert failure.status == Status.CLOSED
    assert failure.closed_by == qa
    assert failure.closed_at is not None
    assert "credentials rotated" in failure.corrective_action


def test_a_corrective_action_already_written_is_enough_to_close(login_as_staff):
    """PATCH it now, close it later -- the check is on the stored value, not on this request's body."""
    failure = _a_failure()
    client = login_as_staff(StaffUserFactory(roles=["qa_officer"]))
    client.patch(
        f"/api/v1/system-failures/{failure.id}/",
        {"corrective_action": "Dependency restored; no lasting effect."},
        format="json",
    )

    response = client.post(f"/api/v1/system-failures/{failure.id}/close/")

    assert response.status_code == 200


def test_status_cannot_be_patched_directly(login_as_staff):
    failure = _a_failure()
    client = login_as_staff(StaffUserFactory(roles=["qa_officer"]))

    response = client.patch(
        f"/api/v1/system-failures/{failure.id}/", {"status": Status.CLOSED}, format="json",
    )

    assert response.status_code == 400
    failure.refresh_from_db()
    assert failure.status == Status.OPEN


def test_what_the_system_did_cannot_be_edited_afterwards(login_as_staff):
    """immediate_action is a fact about the failure, not an opinion about it."""
    failure = _a_failure()
    client = login_as_staff(StaffUserFactory(roles=["qa_officer"]))

    client.patch(
        f"/api/v1/system-failures/{failure.id}/",
        {"immediate_action": ImmediateAction.NONE, "summary": "nothing happened"},
        format="json",
    )

    failure.refresh_from_db()
    assert failure.immediate_action == ImmediateAction.RETRY_SCHEDULED
    assert failure.summary != "nothing happened"


def test_the_register_has_no_create_or_delete_endpoint(login_as_staff):
    failure = _a_failure()
    client = login_as_staff(StaffUserFactory(roles=["qa_officer"]))

    assert client.post("/api/v1/system-failures/", {}, format="json").status_code == 405
    assert client.delete(f"/api/v1/system-failures/{failure.id}/").status_code == 405


def test_the_database_refuses_to_delete_a_recorded_failure():
    """The API has no destroy route; this is the ring behind it (migration 0005)."""
    failure = _a_failure()

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM system_failure WHERE id = %s", [failure.pk])

    assert SystemFailure.objects.filter(pk=failure.pk).exists()


def test_the_register_cannot_be_truncated():
    _a_failure()

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("TRUNCATE system_failure")

    assert SystemFailure.objects.exists()


def test_a_corrective_action_is_attributed_by_history(login_as_staff):
    """
    UPDATE is not revoked on this table -- it cannot be, the corrective
    action is written later -- so what makes it trustworthy is attribution
    rather than immutability.
    """
    failure = _a_failure()
    qa = StaffUserFactory(roles=["qa_officer"])
    client = login_as_staff(qa)

    client.post(
        f"/api/v1/system-failures/{failure.id}/close/",
        {"corrective_action": "Broker restarted; capacity increased."},
        format="json",
    )

    latest = failure.history.first()
    assert latest.corrective_action == "Broker restarted; capacity increased."
    assert latest.history_user == qa


def test_the_machine_counter_bump_writes_no_history():
    """
    The one deliberate use of the QuerySet.update() caveat in
    apps/audit/signals.py: occurrences moving during an outage is not a
    change anybody needs attributed, and a history row per probe would bury
    the ones that matter.
    """
    failure = _a_failure()
    before = failure.history.count()

    _a_failure()
    _a_failure()

    assert failure.history.count() == before
    failure.refresh_from_db()
    assert failure.occurrences == 3
