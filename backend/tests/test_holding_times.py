"""
Holding-time deadlines and the sweep that chases them (FR-C3-05).

`holding_time` sat on TestMethod and Sample since the schema was written,
serialized and used by nothing -- no deadline, no ordering, no alarm. These
tests are the ones that make it a control.

The three decisions in apps/testing/holding_times.py are each tested
directly, because each could reasonably have gone the other way and the
wrong choice is silently non-compliant rather than broken:

  * the clock starts at collection, not receipt (a bottle that spent two
    days in a courier's van has spent two days of its holding time);
  * where both a method and a sample holding time exist, the shorter binds;
  * a retest does not restart the clock.

ISO/IEC 17025:2017 7.4.1 is the clause underneath: the laboratory has to
protect the integrity of an item while it holds it, and a result produced
after the holding time expires is nonconforming work (7.10), not a late
result.
"""

import datetime

import pytest
from django.utils import timezone

from apps.notifications.models import NotificationRecord
from apps.samples.models import Sample
from apps.testing import holding_times
from apps.testing.models import TestRequest
from tests.factories import (
    SampleFactory,
    StaffUserFactory,
    TestMethodFactory,
    TestRequestFactory,
)
from tests.helpers import reload

pytestmark = pytest.mark.django_db

HOURS_24 = datetime.timedelta(hours=24)
HOURS_48 = datetime.timedelta(hours=48)


def _received_sample(*, collected=None, holding_time=None, **kwargs):
    """A sample already through intake, with an explicit receipt time."""
    return SampleFactory(
        status=Sample.Status.RECEIVED,
        received_at=timezone.now() - datetime.timedelta(hours=2),
        collection_datetime=collected,
        holding_time=holding_time,
        **kwargs,
    )


# --- what the deadline is counted from --------------------------------------


def test_the_clock_starts_at_collection_not_receipt():
    """
    The bottle spent 20 hours in transit. Counting from receipt would give
    it a deadline 20 hours later than the method actually allows.
    """
    collected = timezone.now() - datetime.timedelta(hours=20)
    sample = _received_sample(collected=collected)
    method = TestMethodFactory(holding_time=HOURS_24)
    test_request = TestRequestFactory(sample=sample, test_method=method)

    holding_times.apply_to(test_request)

    assert reload(test_request).due_at == collected + HOURS_24
    assert reload(test_request).due_at_basis == TestRequest.DueBasis.COLLECTION


def test_receipt_is_the_fallback_and_says_so():
    """
    A deadline counted from receipt is optimistic, so the basis is recorded
    rather than left for a reader to assume.
    """
    sample = _received_sample(collected=None)
    method = TestMethodFactory(holding_time=HOURS_24)
    test_request = TestRequestFactory(sample=sample, test_method=method)

    holding_times.apply_to(test_request)

    test_request = reload(test_request)
    assert test_request.due_at == sample.received_at + HOURS_24
    assert test_request.due_at_basis == TestRequest.DueBasis.RECEIPT


def test_a_sample_with_no_clock_yet_has_no_deadline():
    sample = SampleFactory(status=Sample.Status.PRE_REGISTERED, collection_datetime=None)
    assert sample.received_at is None
    test_request = TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=HOURS_24))

    holding_times.apply_to(test_request)

    assert reload(test_request).due_at is None
    assert reload(test_request).due_at_basis == ""


def test_a_method_with_no_holding_time_has_no_deadline():
    """Most of the Failure Analysis line. A fabricated default would put it on a countdown nobody asked for."""
    sample = _received_sample(collected=timezone.now())
    test_request = TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=None))

    holding_times.apply_to(test_request)

    assert reload(test_request).due_at is None


# --- which duration binds ---------------------------------------------------


def test_the_shorter_of_the_two_holding_times_binds():
    """
    The method's comes from the procedure, the sample's from its container
    and preservation. Both apply, so the item has to satisfy both.
    """
    collected = timezone.now()
    sample = _received_sample(collected=collected, holding_time=HOURS_24)
    method = TestMethodFactory(holding_time=HOURS_48)
    test_request = TestRequestFactory(sample=sample, test_method=method)

    holding_times.apply_to(test_request)

    assert reload(test_request).due_at == collected + HOURS_24


def test_the_shorter_binds_in_the_other_direction_too():
    collected = timezone.now()
    sample = _received_sample(collected=collected, holding_time=HOURS_48)
    method = TestMethodFactory(holding_time=HOURS_24)
    test_request = TestRequestFactory(sample=sample, test_method=method)

    holding_times.apply_to(test_request)

    assert reload(test_request).due_at == collected + HOURS_24


def test_either_duration_alone_is_enough():
    collected = timezone.now()
    sample = _received_sample(collected=collected, holding_time=HOURS_24)
    test_request = TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=None))

    holding_times.apply_to(test_request)

    assert reload(test_request).due_at == collected + HOURS_24


# --- when the deadline gets computed ----------------------------------------


def test_receiving_a_sample_dates_the_requests_already_booked_against_it(login_as_staff):
    """A test request is routinely booked before the sample turns up."""
    sample = SampleFactory(status=Sample.Status.REGISTERED, collection_datetime=None)
    test_request = TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=HOURS_24))
    assert test_request.due_at is None

    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))
    response = client.post(f"/api/v1/samples/{sample.id}/receive/", {}, format="json")

    assert response.status_code == 200, response.data
    assert reload(test_request).due_at is not None
    assert reload(test_request).due_at_basis == TestRequest.DueBasis.RECEIPT


def test_a_request_booked_after_receipt_dates_itself(login_as_staff):
    collected = timezone.now() - datetime.timedelta(hours=3)
    sample = _received_sample(collected=collected)
    method = TestMethodFactory(holding_time=HOURS_24)
    client = login_as_staff(StaffUserFactory(roles=["analyst"]))

    response = client.post(
        "/api/v1/test-requests/", {"sample": sample.id, "test_method": method.id}, format="json"
    )

    assert response.status_code == 201, response.data
    assert response.data["due_at"] is not None
    assert TestRequest.objects.get(pk=response.data["id"]).due_at == collected + HOURS_24


def test_correcting_the_collection_time_moves_the_deadline(login_as_staff):
    """
    The call site that is easiest to forget: nothing about a PATCH to a
    sample looks like it touches the testing queue.
    """
    sample = _received_sample(collected=timezone.now() - datetime.timedelta(hours=1))
    test_request = TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=HOURS_24))
    holding_times.apply_to(test_request)

    corrected = timezone.now() - datetime.timedelta(hours=30)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))
    response = client.patch(
        f"/api/v1/samples/{sample.id}/", {"collection_datetime": corrected.isoformat()}, format="json"
    )

    assert response.status_code == 200, response.data
    assert reload(test_request).due_at == corrected + HOURS_24


def test_an_unrelated_patch_leaves_the_deadline_alone(login_as_staff):
    sample = _received_sample(collected=timezone.now())
    test_request = TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=HOURS_24))
    holding_times.apply_to(test_request)
    before = reload(test_request).due_at

    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))
    response = client.patch(
        f"/api/v1/samples/{sample.id}/", {"sampling_point": "Outfall B"}, format="json"
    )

    assert response.status_code == 200, response.data
    assert reload(test_request).due_at == before


def test_a_retest_does_not_restart_the_clock():
    """The sample was collected once, and re-queueing a test does not un-collect it."""
    collected = timezone.now() - datetime.timedelta(hours=20)
    sample = _received_sample(collected=collected)
    test_request = TestRequestFactory(
        sample=sample,
        test_method=TestMethodFactory(holding_time=HOURS_24),
        status=TestRequest.Status.RETEST_PENDING,
    )
    holding_times.apply_to(test_request)

    holding_times.apply_to(reload(test_request))

    assert reload(test_request).due_at == collected + HOURS_24


def test_recomputing_an_unchanged_deadline_reports_no_change():
    sample = _received_sample(collected=timezone.now())
    test_request = TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=HOURS_24))

    assert holding_times.apply_to(test_request) is True
    assert holding_times.apply_to(test_request) is False


# --- overdue ----------------------------------------------------------------


def test_outstanding_work_past_its_deadline_is_overdue():
    sample = _received_sample(collected=timezone.now() - HOURS_48)
    test_request = TestRequestFactory(
        sample=sample, test_method=TestMethodFactory(holding_time=HOURS_24),
        status=TestRequest.Status.IN_PROGRESS,
    )
    holding_times.apply_to(test_request)

    assert reload(test_request).is_overdue


def test_a_completed_test_is_never_overdue():
    """
    This answers "is something being lost right now". A test finished late
    is a 7.10 matter an investigation should already be carrying, not a
    queue entry to keep flagging forever.
    """
    sample = _received_sample(collected=timezone.now() - HOURS_48)
    test_request = TestRequestFactory(
        sample=sample, test_method=TestMethodFactory(holding_time=HOURS_24),
        status=TestRequest.Status.COMPLETED,
    )
    holding_times.apply_to(test_request)

    assert not reload(test_request).is_overdue


def test_a_test_with_no_deadline_is_never_overdue():
    test_request = TestRequestFactory(
        sample=_received_sample(), test_method=TestMethodFactory(holding_time=None),
        status=TestRequest.Status.IN_PROGRESS,
    )

    assert not reload(test_request).is_overdue


# --- the queue: what to pick up next ----------------------------------------


def _queued(client, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    response = client.get(f"/api/v1/test-requests/?{query}" if query else "/api/v1/test-requests/")
    assert response.status_code == 200, response.data
    return [tr["id"] for tr in response.data["results"]]


def test_the_queue_leads_with_the_soonest_deadline(login_as_staff):
    """Creation order is what was booked in; deadline order is what to do next."""
    collected = timezone.now()
    later = TestRequestFactory(
        sample=_received_sample(collected=collected),
        test_method=TestMethodFactory(holding_time=HOURS_48),
    )
    sooner = TestRequestFactory(
        sample=_received_sample(collected=collected),
        test_method=TestMethodFactory(holding_time=HOURS_24),
    )
    for tr in (later, sooner):
        holding_times.apply_to(tr)

    assert _queued(login_as_staff(StaffUserFactory())) == [sooner.id, later.id]


def test_work_with_no_deadline_sorts_last(login_as_staff):
    """A method with no holding time has nothing being lost by waiting."""
    dated = TestRequestFactory(
        sample=_received_sample(collected=timezone.now()),
        test_method=TestMethodFactory(holding_time=HOURS_48),
    )
    holding_times.apply_to(dated)
    undated = TestRequestFactory(test_method=TestMethodFactory(holding_time=None))

    assert _queued(login_as_staff(StaffUserFactory())) == [dated.id, undated.id]


def test_priority_outranks_the_deadline(login_as_staff):
    """
    A rush sample goes first even with more holding time left, because the
    sweep chases the deadline regardless of where it sits in this list.
    """
    collected = timezone.now()
    routine = TestRequestFactory(
        sample=_received_sample(collected=collected, priority=Sample.Priority.ROUTINE),
        test_method=TestMethodFactory(holding_time=HOURS_24),
    )
    rush = TestRequestFactory(
        sample=_received_sample(collected=collected, priority=Sample.Priority.RUSH),
        test_method=TestMethodFactory(holding_time=HOURS_48),
    )
    for tr in (routine, rush):
        holding_times.apply_to(tr)

    assert _queued(login_as_staff(StaffUserFactory())) == [rush.id, routine.id]


def test_priority_ranks_by_urgency_not_alphabetically(login_as_staff):
    """
    The trap this guards: ordering by the TextChoices column sorts
    emergency, routine, rush -- putting routine work ahead of a rush.
    """
    collected = timezone.now()
    requests = {
        priority: TestRequestFactory(
            sample=_received_sample(collected=collected, priority=priority),
            test_method=TestMethodFactory(holding_time=HOURS_24),
        )
        for priority in (Sample.Priority.ROUTINE, Sample.Priority.RUSH, Sample.Priority.EMERGENCY)
    }
    for tr in requests.values():
        holding_times.apply_to(tr)

    assert _queued(login_as_staff(StaffUserFactory())) == [
        requests[Sample.Priority.EMERGENCY].id,
        requests[Sample.Priority.RUSH].id,
        requests[Sample.Priority.ROUTINE].id,
    ]


def test_the_overdue_filter_returns_only_live_breaches(login_as_staff):
    breached = TestRequestFactory(
        sample=_received_sample(collected=timezone.now() - HOURS_48),
        test_method=TestMethodFactory(holding_time=HOURS_24),
        status=TestRequest.Status.IN_PROGRESS,
    )
    finished_late = TestRequestFactory(
        sample=_received_sample(collected=timezone.now() - HOURS_48),
        test_method=TestMethodFactory(holding_time=HOURS_24),
        status=TestRequest.Status.COMPLETED,
    )
    in_time = TestRequestFactory(
        sample=_received_sample(collected=timezone.now()),
        test_method=TestMethodFactory(holding_time=HOURS_48),
        status=TestRequest.Status.IN_PROGRESS,
    )
    for tr in (breached, finished_late, in_time):
        holding_times.apply_to(tr)

    assert _queued(login_as_staff(StaffUserFactory()), overdue="true") == [breached.id]


# --- the sweep (ISO/IEC 17025:2017 7.4.1) -----------------------------------


def _sweep():
    from apps.notifications.tasks import sweep_holding_times

    return sweep_holding_times()


def _subjects():
    return [n.subject for n in NotificationRecord.objects.filter(
        kind=NotificationRecord.Kind.HOLDING_TIME_DUE
    )]


def test_the_sweep_warns_before_the_deadline(login_as_staff, settings):
    settings.HOLDING_TIME_WARNING_HOURS = 6
    analyst = StaffUserFactory(roles=["analyst"])
    test_request = TestRequestFactory(
        sample=_received_sample(collected=timezone.now() - datetime.timedelta(hours=20)),
        test_method=TestMethodFactory(holding_time=HOURS_24),
        assigned_analyst=analyst,
    )
    holding_times.apply_to(test_request)

    result = _sweep()

    assert result["at_risk"] == 1
    assert result["breached"] == 0
    assert any("expires" in s for s in _subjects())
    assert NotificationRecord.objects.filter(
        kind=NotificationRecord.Kind.HOLDING_TIME_DUE, recipient=analyst.email
    ).exists()


def test_the_sweep_leaves_work_outside_the_horizon_alone(settings):
    settings.HOLDING_TIME_WARNING_HOURS = 6
    test_request = TestRequestFactory(
        sample=_received_sample(collected=timezone.now()),
        test_method=TestMethodFactory(holding_time=HOURS_48),
        assigned_analyst=StaffUserFactory(roles=["analyst"]),
    )
    holding_times.apply_to(test_request)

    assert _sweep() == {"at_risk": 0, "breached": 0, "queued": 0}


def test_a_breach_also_reaches_qa(settings):
    """Deciding what a breach means for the result is QA's call, not the analyst's."""
    settings.HOLDING_TIME_WARNING_HOURS = 6
    analyst = StaffUserFactory(roles=["analyst"])
    qa = StaffUserFactory(roles=["qa_officer"])
    test_request = TestRequestFactory(
        sample=_received_sample(collected=timezone.now() - HOURS_48),
        test_method=TestMethodFactory(holding_time=HOURS_24),
        assigned_analyst=analyst,
        status=TestRequest.Status.IN_PROGRESS,
    )
    holding_times.apply_to(test_request)

    result = _sweep()

    assert result["breached"] == 1
    told = set(
        NotificationRecord.objects.filter(
            kind=NotificationRecord.Kind.HOLDING_TIME_DUE
        ).values_list("recipient", flat=True)
    )
    assert told == {analyst.email, qa.email}
    assert any("EXPIRED" in s for s in _subjects())


def test_an_unassigned_analysis_falls_back_to_the_analyst_roles(settings):
    """More in need of a message, not less."""
    settings.HOLDING_TIME_WARNING_HOURS = 6
    analyst = StaffUserFactory(roles=["analyst"])
    supervisor = StaffUserFactory(roles=["lab_supervisor"])
    test_request = TestRequestFactory(
        sample=_received_sample(collected=timezone.now() - datetime.timedelta(hours=20)),
        test_method=TestMethodFactory(holding_time=HOURS_24),
        assigned_analyst=None,
    )
    holding_times.apply_to(test_request)

    _sweep()

    told = set(
        NotificationRecord.objects.filter(
            kind=NotificationRecord.Kind.HOLDING_TIME_DUE
        ).values_list("recipient", flat=True)
    )
    assert told == {analyst.email, supervisor.email}


def test_the_sweep_does_not_repeat_the_same_warning(settings):
    """Nightly-sweep discipline: without the dedupe key this mails daily until somebody acts."""
    settings.HOLDING_TIME_WARNING_HOURS = 6
    test_request = TestRequestFactory(
        sample=_received_sample(collected=timezone.now() - datetime.timedelta(hours=20)),
        test_method=TestMethodFactory(holding_time=HOURS_24),
        assigned_analyst=StaffUserFactory(roles=["analyst"]),
    )
    holding_times.apply_to(test_request)

    first = _sweep()
    second = _sweep()

    assert first["queued"] == 1
    assert second["queued"] == 0


def test_a_breach_is_a_new_message_after_a_warning(settings):
    """
    The warning and the breach say different things, so the second is not
    suppressed by the first -- the dedupe key carries which one it is.
    """
    settings.HOLDING_TIME_WARNING_HOURS = 6
    sample = _received_sample(collected=timezone.now() - datetime.timedelta(hours=20))
    test_request = TestRequestFactory(
        sample=sample,
        test_method=TestMethodFactory(holding_time=HOURS_24),
        assigned_analyst=StaffUserFactory(roles=["analyst"]),
    )
    holding_times.apply_to(test_request)
    assert _sweep()["queued"] == 1

    # The deadline passes.
    TestRequest.objects.filter(pk=test_request.pk).update(
        due_at=timezone.now() - datetime.timedelta(minutes=5)
    )

    breach = _sweep()

    assert breach["breached"] == 1
    assert breach["queued"] == 1


def test_completed_work_is_not_swept(settings):
    settings.HOLDING_TIME_WARNING_HOURS = 6
    test_request = TestRequestFactory(
        sample=_received_sample(collected=timezone.now() - HOURS_48),
        test_method=TestMethodFactory(holding_time=HOURS_24),
        status=TestRequest.Status.COMPLETED,
        assigned_analyst=StaffUserFactory(roles=["analyst"]),
    )
    holding_times.apply_to(test_request)

    assert _sweep()["at_risk"] == 0


def test_the_sweep_message_names_the_sample_and_the_basis(settings):
    """The body is built at send time from the row -- see apps/notifications/messages.py."""
    from apps.notifications.messages import build_body

    settings.HOLDING_TIME_WARNING_HOURS = 6
    sample = _received_sample(collected=timezone.now() - datetime.timedelta(hours=20))
    test_request = TestRequestFactory(
        sample=sample,
        test_method=TestMethodFactory(holding_time=HOURS_24),
        assigned_analyst=StaffUserFactory(roles=["analyst"]),
    )
    holding_times.apply_to(test_request)
    _sweep()

    record = NotificationRecord.objects.get(kind=NotificationRecord.Kind.HOLDING_TIME_DUE)
    body = build_body(record)

    assert sample.unique_sample_code in body
    assert "Time of collection" in body
    assert f"/test-requests/{test_request.id}" in body
