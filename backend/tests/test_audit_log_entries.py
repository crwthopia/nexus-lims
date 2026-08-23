"""
FR-E17-01: every create/update/delete on a regulated entity writes an
AuditLogEntry naming the actor.

The table, its monthly partitioning and its three actor types were built
and nothing populated them. Measured before this existed: a staff edit, a
customer self-enrolment and a system-issued credit note produced zero rows
between them, and the two non-staff writes were anonymous in
django-simple-history as well -- correctly, since its history_user is a
ForeignKey to StaffUser and cannot hold anyone else.

The actor tests are the point of the file. Recording *that* something
changed was never the hard part; recording *who* changed it is what
AuditLogEntry.actor_type exists for and what nothing else in the system can
express.
"""

import pytest

from apps.accounts.models import Role
from apps.audit.models import AuditLogEntry
from apps.reporting.models import Report
from apps.samples.models import Sample
from apps.testing.models import TestMethod
from tests.factories import (
    CustomerUserFactory, OrderFactory, RoleFactory, SampleFactory, StaffUserFactory,
    TestMethodFactory,
)

pytestmark = pytest.mark.django_db


def entries_for(instance, **filters):
    return AuditLogEntry.objects.filter(
        entity_type=type(instance).__name__, entity_id=instance.pk, **filters
    )


def qa_officer():
    user = StaffUserFactory()
    user.roles.add(RoleFactory(name=Role.RoleName.QA_OFFICER))
    return user


def approved_sample():
    sample = SampleFactory(order=OrderFactory())
    Sample.objects.filter(pk=sample.pk).update(status=Sample.Status.APPROVED)
    sample.refresh_from_db()
    return sample


# --- Who ------------------------------------------------------------------

def test_a_staff_write_is_attributed_to_that_member_of_staff(login_as_staff):
    staff = qa_officer()
    method = TestMethodFactory(specification_limits={"pH": {"min": 6.5, "max": 8.5}})
    client = login_as_staff(staff)

    client.patch(
        f"/api/v1/test-methods/{method.pk}/",
        {"specification_limits": {"pH": {"min": 0, "max": 14}}},
        format="json",
    )

    entry = entries_for(method, field_changed="specification_limits").get()
    assert entry.actor_type == AuditLogEntry.ActorType.STAFF
    assert entry.actor_id == staff.pk


def test_a_system_write_is_attributed_to_the_system():
    """
    A task has no request, so the actor comes from the task_prerun handler
    in config/celery.py. Before that, this row would have said 'staff' --
    whatever the last request on this thread happened to leave behind.
    """
    from config.celery import app

    method = TestMethodFactory(name="before")

    @app.task(name="tests.rename_method")
    def _rename(pk):
        m = TestMethod.objects.get(pk=pk)
        m.name = "after"
        m.save()

    _rename.apply(args=[method.pk]).get()

    entry = entries_for(method, field_changed="name").get()
    assert entry.actor_type == AuditLogEntry.ActorType.SYSTEM
    assert entry.actor_id is None


def test_the_report_pipeline_records_its_own_transitions(monkeypatch):
    """
    These moved through QuerySet.update(), which sends no signals: a report
    went pending -> generating -> ready and left one history row saying
    'pending'. Both transitions are now recorded, and attributed to the
    system rather than to nobody.
    """
    from apps.reporting.tasks import generate_report_pdf

    sample = approved_sample()
    report = Report.objects.create(
        sample=sample, order=sample.order,
        report_type=Report.ReportType.WATER_ENVIRONMENTAL_COA,
        generated_by=StaffUserFactory(), version=1,
    )
    monkeypatch.setattr(
        "apps.reporting.tasks.upload_object",
        lambda key, data, content_type="application/octet-stream", bucket=None: key,
    )

    generate_report_pdf.apply(args=[report.pk]).get()

    statuses = list(
        entries_for(report, field_changed="status").values_list("new_value", flat=True)
    )
    assert Report.Status.GENERATING in statuses
    assert Report.Status.READY in statuses
    assert all(
        e.actor_type == AuditLogEntry.ActorType.SYSTEM
        for e in entries_for(report, field_changed="status")
    )


def test_a_task_run_inside_a_request_is_still_the_system(login_as_staff):
    """
    The case the task_prerun actor guards, and the only one that
    distinguishes it from the ContextVar default.

    In production tasks reach a worker via .delay(), where nothing has ever
    set an actor and the default already says system. But a task executed
    in-process -- CELERY_TASK_ALWAYS_EAGER, a direct .apply(), a management
    command inside a request -- runs in the *caller's* context. Without the
    handler resetting it, every row that task wrote would name the staff
    member who happened to trigger it, which is a plausible-looking lie
    rather than a missing record.
    """
    from config.celery import app

    staff = qa_officer()
    method = TestMethodFactory(name="before")
    client = login_as_staff(staff)

    @app.task(name="tests.rename_from_request")
    def _rename(pk):
        m = TestMethod.objects.get(pk=pk)
        m.name = "after"
        m.save()

    # Simulate the in-process case: a staff actor is live, and the task runs
    # without leaving that context.
    from apps.audit.context import set_actor

    token = set_actor(AuditLogEntry.ActorType.STAFF, staff.pk)
    try:
        _rename.apply(args=[method.pk]).get()
    finally:
        from apps.audit.context import reset_actor

        reset_actor(token)

    entry = entries_for(method, field_changed="name").get()
    assert entry.actor_type == AuditLogEntry.ActorType.SYSTEM, (
        f"task wrote as {entry.actor_type} (actor_id={entry.actor_id}) -- "
        "the caller's actor leaked into the task"
    )
    assert entry.actor_id is None


# --- What -----------------------------------------------------------------

def test_a_create_is_recorded_once_not_once_per_field(login_as_staff):
    client = login_as_staff(qa_officer())

    response = client.post(
        "/api/v1/test-methods/",
        {"name": "New Method", "method_reference": "SOP-9"},
        format="json",
    )

    created = TestMethod.objects.get(pk=response.json()["id"])
    assert entries_for(created).count() == 1
    assert entries_for(created).get().reason == "created"


def test_an_update_records_the_old_and_new_value(login_as_staff):
    method = TestMethodFactory(method_reference="SOP-0001")
    client = login_as_staff(qa_officer())

    client.patch(
        f"/api/v1/test-methods/{method.pk}/",
        {"method_reference": "SOP-0002"},
        format="json",
    )

    entry = entries_for(method, field_changed="method_reference").get()
    assert entry.old_value == "SOP-0001"
    assert entry.new_value == "SOP-0002"


def test_only_the_fields_that_changed_are_recorded(login_as_staff):
    """
    A row per save regardless of what moved buries the changes that matter.
    """
    method = TestMethodFactory(name="Unchanged", method_reference="SOP-0001")
    client = login_as_staff(qa_officer())

    client.patch(
        f"/api/v1/test-methods/{method.pk}/",
        {"name": "Unchanged", "method_reference": "SOP-0002"},
        format="json",
    )

    changed = set(entries_for(method, reason="updated").values_list("field_changed", flat=True))
    assert changed == {"method_reference"}


def test_a_save_that_changes_nothing_writes_nothing(login_as_staff):
    method = TestMethodFactory(name="Same")
    client = login_as_staff(qa_officer())
    before = entries_for(method).count()

    client.patch(f"/api/v1/test-methods/{method.pk}/", {"name": "Same"}, format="json")

    assert entries_for(method).count() == before


def test_a_delete_is_recorded(login_as_staff):
    method = TestMethodFactory()
    pk = method.pk
    client = login_as_staff(qa_officer())

    client.delete(f"/api/v1/test-methods/{pk}/")

    assert AuditLogEntry.objects.filter(
        entity_type="TestMethod", entity_id=pk, reason="deleted"
    ).exists()


# --- Scope ----------------------------------------------------------------

def test_an_unaudited_model_writes_nothing(login_as_staff):
    """
    Billing, training and documents are out of scope for now. Pinned so the
    boundary is a decision rather than something discovered later.
    """
    from apps.audit.signals import AUDITED_MODELS

    assert ("billing", "Invoice") not in AUDITED_MODELS
    assert ("training", "Enrollment") not in AUDITED_MODELS

    customer = CustomerUserFactory()
    order = OrderFactory(customer=customer)

    assert not AuditLogEntry.objects.filter(
        entity_type="Order", entity_id=order.pk
    ).exists()


def test_the_context_default_matches_the_models_own_enum():
    """
    apps/audit/context.py cannot import models at module scope, so it uses
    the string literal 'system'. If the enum ever changes, this fails rather
    than every system-attributed row quietly becoming invalid.
    """
    from apps.audit.context import get_actor

    assert get_actor().actor_type == AuditLogEntry.ActorType.SYSTEM


# --- The customer actor ----------------------------------------------------
#
# Asserted against the middleware directly rather than through an endpoint,
# because nothing a customer can write is in AUDITED_MODELS yet: the portal's
# only writes are enrollments and credit-note applications, both out of scope
# for now. So the CUSTOMER branch would otherwise ship untested and break
# silently the day Enrollment is added. These tests cover the derivation; the
# ones above cover the recording.

def _actor_during_request(request):
    """Runs the middleware over `request` and returns the actor it set."""
    from apps.accounts.middleware import RLSContextMiddleware
    from apps.audit.context import get_actor

    seen = {}

    def _capture(_request):
        seen["actor"] = get_actor()

        class _Response:
            pass

        return _Response()

    RLSContextMiddleware(_capture)(request)
    return seen["actor"]


def _request_for(path="/api/v1/test-methods/", user=None, customer_id=None):
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    request = RequestFactory().get(path)
    request.user = user or AnonymousUser()
    request.session = {"customer_user_id": customer_id} if customer_id else {}
    return request


def test_a_customer_session_is_derived_as_the_customer_actor():
    customer = CustomerUserFactory()

    actor = _actor_during_request(_request_for(customer_id=customer.pk))

    assert actor.actor_type == AuditLogEntry.ActorType.CUSTOMER
    assert actor.actor_id == customer.pk


def test_a_staff_session_is_derived_as_the_staff_actor():
    staff = StaffUserFactory()

    actor = _actor_during_request(_request_for(user=staff))

    assert actor.actor_type == AuditLogEntry.ActorType.STAFF
    assert actor.actor_id == staff.pk


def test_the_actor_does_not_survive_the_response():
    """
    A ContextVar left set outside its request attributes the next write to
    whoever ran before it. Reset is the difference between an audit trail
    and a plausible-looking one.
    """
    from apps.audit.context import get_actor

    staff = StaffUserFactory()
    _actor_during_request(_request_for(user=staff))

    assert get_actor().actor_id is None
    assert get_actor().actor_type == AuditLogEntry.ActorType.SYSTEM
