"""
Well-typed input that is nonsense anyway.

The two malformed-input suites cover shape and type: a body that is not an
object, an id that is not a number. This one covers the tier past them --
input that passes every type check and still describes something that
cannot be true. A calibration due before it was performed. A session that
ends before it starts. A minimum enrollment above the maximum.

The distinction that decides what is tested here: a value is refused when
no reading of the business makes it valid, and left alone when refusing it
would be inventing policy. A negative invoice is the first kind -- money
owed *to* a customer in the column meaning money owed *by* them, and this
system already has CreditNote for that. A zero invoice is the second: a
fully discounted enrollment is a real thing to bill at 0.00. The gaps
deliberately left open are listed in the README's known gaps, because they
are NASAT's call and not a developer's.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.testing.ingestion import IngestionError, compute_out_of_spec
from apps.testing.models import TestResult
from tests.factories import (
    InstrumentFactory,
    OrderFactory,
    RoleFactory,
    StaffUserFactory,
    TestMethodFactory,
    TrainingCourseFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def any_staff(login_as_staff):
    user = StaffUserFactory(is_superuser=True)
    for role in Role.RoleName.values:
        user.roles.add(RoleFactory(name=role))
    return login_as_staff(user)


# --- Specification limits (FR-C3-08) --------------------------------------
#
# The most consequential of these. specification_limits is a JSONField, so
# it accepted anything, and a non-numeric limit is a *stored* fault: every
# later result entry and every file ingestion for that method raised
# TypeError comparing a float to a string. One bad write broke a whole test
# method until someone corrected the data.

@pytest.mark.parametrize(
    ("limits", "expected_error"),
    [
        ({"min": "abc"}, "must be a number"),
        ({"max": None}, "must be a number"),
        ({"min": [1]}, "must be a number"),
        ({"min": 10, "max": 1}, "above 'max'"),
        ("not-an-object", "Expected an object"),
    ],
)
def test_a_test_method_cannot_store_unusable_specification_limits(any_staff, limits, expected_error):
    response = any_staff.post(
        "/api/v1/test-methods/",
        {"name": "Lead", "method_reference": "ASTM-1", "specification_limits": limits},
        format="json",
    )

    assert response.status_code == 400
    assert expected_error in str(response.json()["specification_limits"])


@pytest.mark.parametrize("limits", [{"min": 0, "max": 10}, {"min": 0}, {"max": 10}, {}, {"min": "0", "max": "5"}])
def test_usable_specification_limits_are_still_accepted(any_staff, limits):
    # Including strings that are numbers: an integration writing "0" rather
    # than 0 is doing nothing wrong, and float() reads both.
    response = any_staff.post(
        "/api/v1/test-methods/",
        {"name": "Lead", "method_reference": "ASTM-1", "specification_limits": limits},
        format="json",
    )

    assert response.status_code == 201


def test_a_min_above_max_would_have_flagged_every_result(any_staff):
    # Why min > max is refused rather than tolerated: nothing crashes, so
    # the only symptom is every result the method ever produces coming out
    # flagged -- which reads as a process in crisis rather than as a typo.
    method = TestMethodFactory(specification_limits={"min": 10, "max": 1})

    assert compute_out_of_spec(method, TestResult.DataType.FLOAT, "5") is True


def test_a_malformed_limit_refuses_the_result_rather_than_skipping_the_check():
    # Degrading to "no limit" would be worse than the crash it replaces:
    # the result would enter the record unflagged, which is the outcome
    # FR-C3-08 exists to prevent. So it is an error, and it names the
    # misconfiguration rather than the Python type mismatch.
    method = TestMethodFactory(specification_limits={"min": "abc"})

    with pytest.raises(IngestionError, match="malformed specification limit"):
        compute_out_of_spec(method, TestResult.DataType.FLOAT, "5")


# --- Calibration (FR-E3-02) -----------------------------------------------

def test_a_calibration_cannot_fall_due_before_it_was_performed(any_staff):
    instrument = InstrumentFactory()
    now = timezone.now()

    response = any_staff.post(
        "/api/v1/calibration-records/",
        {
            "instrument": instrument.id,
            "performed_at": now.isoformat(),
            "result": "pass",
            "next_due_date": (now - timedelta(days=30)).date().isoformat(),
        },
        format="json",
    )

    # Such a record reports the instrument as overdue the moment it is
    # calibrated, which is the opposite of what logging it is for.
    assert response.status_code == 400
    assert "next_due_date" in response.json()


def test_a_calibration_cannot_be_recorded_as_performed_in_the_future(any_staff):
    instrument = InstrumentFactory()
    later = timezone.now() + timedelta(days=365)

    response = any_staff.post(
        "/api/v1/calibration-records/",
        {
            "instrument": instrument.id,
            "performed_at": later.isoformat(),
            "result": "pass",
            "next_due_date": (later + timedelta(days=365)).date().isoformat(),
        },
        format="json",
    )

    # The record carries a `result`, and a calibration that has not happened
    # cannot have passed.
    assert response.status_code == 400
    assert "performed_at" in response.json()


def test_an_ordinary_calibration_is_still_accepted(any_staff):
    instrument = InstrumentFactory()
    now = timezone.now()

    response = any_staff.post(
        "/api/v1/calibration-records/",
        {
            "instrument": instrument.id,
            "performed_at": (now - timedelta(hours=1)).isoformat(),
            "result": "pass",
            "next_due_date": (now + timedelta(days=365)).date().isoformat(),
        },
        format="json",
    )

    assert response.status_code == 201


def test_a_calibration_due_the_same_day_it_was_performed_is_allowed(any_staff):
    # The boundary: same-day is degenerate but not contradictory, and a
    # strict > would reject a legitimate same-day recheck.
    #
    # "Today" is the lab's today. TIME_ZONE is Asia/Manila, so for the eight
    # hours of each UTC day where the two calendars disagree, a UTC date
    # here is yesterday as far as the serializer is concerned -- which made
    # this test fail only between 16:00 and 24:00 UTC.
    instrument = InstrumentFactory()
    now = timezone.now()
    today_local = timezone.localtime(now).date()

    response = any_staff.post(
        "/api/v1/calibration-records/",
        {
            "instrument": instrument.id,
            "performed_at": (now - timedelta(hours=1)).isoformat(),
            "result": "pass",
            "next_due_date": today_local.isoformat(),
        },
        format="json",
    )

    assert response.status_code == 201


# --- Training sessions ----------------------------------------------------

def _session_payload(course, **overrides):
    now = timezone.now()
    payload = {
        "course": course.id,
        "start_date": (now + timedelta(days=10)).isoformat(),
        "end_date": (now + timedelta(days=12)).isoformat(),
        "capacity": 20,
        "min_capacity": 5,
        "cancellation_threshold_days": 7,
    }
    payload.update(overrides)
    return payload


def test_a_session_cannot_end_before_it_starts(any_staff):
    course = TrainingCourseFactory()
    now = timezone.now()

    response = any_staff.post(
        "/api/v1/training-sessions/",
        _session_payload(
            course,
            start_date=(now + timedelta(days=10)).isoformat(),
            end_date=(now + timedelta(days=5)).isoformat(),
        ),
        format="json",
    )

    assert response.status_code == 400
    assert "end_date" in response.json()


def test_a_session_minimum_cannot_exceed_its_capacity(any_staff):
    course = TrainingCourseFactory()

    response = any_staff.post(
        "/api/v1/training-sessions/",
        _session_payload(course, capacity=5, min_capacity=50),
        format="json",
    )

    # min_capacity is the threshold below which the scheduled task cancels
    # the session, so this schedules one guaranteed to cancel itself however
    # well it sells.
    assert response.status_code == 400
    assert "min_capacity" in response.json()


def test_an_ordinary_session_is_still_accepted(any_staff):
    course = TrainingCourseFactory()

    response = any_staff.post("/api/v1/training-sessions/", _session_payload(course), format="json")

    assert response.status_code == 201


def test_a_single_day_session_is_allowed(any_staff):
    # start == end is a same-day course, not a contradiction.
    course = TrainingCourseFactory()
    day = (timezone.now() + timedelta(days=10)).isoformat()

    response = any_staff.post(
        "/api/v1/training-sessions/",
        _session_payload(course, start_date=day, end_date=day),
        format="json",
    )

    assert response.status_code == 201


def test_a_session_whose_minimum_equals_its_capacity_is_allowed(any_staff):
    # Degenerate (it must sell out to run) but a coherent thing to want.
    course = TrainingCourseFactory()

    response = any_staff.post(
        "/api/v1/training-sessions/", _session_payload(course, capacity=8, min_capacity=8), format="json"
    )

    assert response.status_code == 201


# --- Invoicing ------------------------------------------------------------

def test_an_invoice_cannot_be_negative(any_staff):
    order = OrderFactory()

    response = any_staff.post(
        "/api/v1/invoices/", {"order": order.id, "amount": "-500.00"}, format="json"
    )

    assert response.status_code == 400
    assert "credit note" in str(response.json()["amount"]).lower()


def test_a_zero_invoice_is_deliberately_still_allowed(any_staff):
    # Not an oversight: a fully discounted or fully credit-noted enrollment
    # is a real thing to invoice at 0.00. Refusing it would be inventing
    # policy rather than enforcing arithmetic.
    order = OrderFactory()

    response = any_staff.post(
        "/api/v1/invoices/", {"order": order.id, "amount": "0.00"}, format="json"
    )

    assert response.status_code == 201
