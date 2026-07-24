"""
Training discounts, credit notes (Blueprint Section 3.6), and the automated
capacity-check Celery task (apps/training/tasks.py check_session_capacity,
called directly as a plain function rather than via .delay() -- the standard
way to unit-test a Celery task's logic without a broker/worker).
"""

import datetime

import pytest
from django.utils import timezone

from apps.training import services
from apps.training.models import CreditNote, Enrollment, TrainingSession
from apps.training.tasks import check_session_capacity
from tests.factories import (
    CustomerUserFactory,
    DocumentFactory,
    EnrollmentFactory,
    InvoiceFactory,
    StaffUserFactory,
    TrainingCourseFactory,
    TrainingSessionFactory,
)
from tests.helpers import reload

pytestmark = pytest.mark.django_db


def test_compute_discount_only_applies_student_discount_when_eligible():
    course = TrainingCourseFactory(student_discount_pct="15.00")
    ineligible_customer = CustomerUserFactory()
    eligible_customer = CustomerUserFactory(school_id_document=DocumentFactory())

    assert services.compute_discount(ineligible_customer, course) == 0
    assert services.compute_discount(eligible_customer, course) == course.student_discount_pct


def test_apply_credit_note_rejects_a_different_customers_enrollment():
    credit_note = _available_credit_note()
    other_customers_enrollment = EnrollmentFactory()

    with pytest.raises(services.CreditNoteApplyError, match="different customer"):
        services.apply_credit_note(credit_note, other_customers_enrollment)


def test_apply_credit_note_rejects_already_applied_note():
    credit_note = _available_credit_note()
    credit_note.status = CreditNote.Status.APPLIED
    credit_note.save(update_fields=["status"])
    same_customer_enrollment = EnrollmentFactory(customer=credit_note.customer)

    with pytest.raises(services.CreditNoteApplyError, match="not available"):
        services.apply_credit_note(credit_note, same_customer_enrollment)


def test_apply_credit_note_success_marks_applied():
    credit_note = _available_credit_note()
    target = EnrollmentFactory(customer=credit_note.customer)

    services.apply_credit_note(credit_note, target)

    credit_note.refresh_from_db()
    assert credit_note.status == CreditNote.Status.APPLIED
    assert credit_note.applied_to_enrollment_id == target.id


def _available_credit_note():
    from tests.factories import CreditNoteFactory

    return CreditNoteFactory(status=CreditNote.Status.AVAILABLE)


def test_check_session_capacity_flags_and_issues_credit_note_for_paid_enrollment():
    session = TrainingSessionFactory(
        min_capacity=5,
        cancellation_threshold_days=7,
        start_date=timezone.now() + datetime.timedelta(days=3),  # inside the 7-day threshold window
    )
    enrollment = EnrollmentFactory(session=session, status=Enrollment.Status.CONFIRMED)
    InvoiceFactory(enrollment=enrollment, order=None, amount="5000.00", status="paid")

    result = check_session_capacity()

    assert result["sessions_flagged"] == 1
    assert reload(session).status == TrainingSession.Status.PENDING_RESCHEDULE
    enrollment = reload(enrollment)
    assert enrollment.status == Enrollment.Status.RESCHEDULED
    credit_note = CreditNote.objects.get(source_enrollment=enrollment)
    assert credit_note.amount == 5000
    assert credit_note.customer_id == enrollment.customer_id


def test_check_session_capacity_issues_no_credit_note_when_nothing_was_paid():
    session = TrainingSessionFactory(
        min_capacity=5,
        cancellation_threshold_days=7,
        start_date=timezone.now() + datetime.timedelta(days=3),
    )
    enrollment = EnrollmentFactory(session=session, status=Enrollment.Status.CONFIRMED)

    check_session_capacity()

    enrollment = reload(enrollment)
    assert enrollment.status == Enrollment.Status.RESCHEDULED
    assert not CreditNote.objects.filter(source_enrollment=enrollment).exists()


def test_check_session_capacity_ignores_healthy_sessions():
    session = TrainingSessionFactory(
        min_capacity=1,
        cancellation_threshold_days=7,
        start_date=timezone.now() + datetime.timedelta(days=3),
    )
    EnrollmentFactory(session=session, status=Enrollment.Status.CONFIRMED)

    result = check_session_capacity()

    assert result["sessions_flagged"] == 0
    assert reload(session).status == TrainingSession.Status.SCHEDULED


def test_session_fsm_actions_are_reachable_over_the_api(login_as_staff):
    """TrainingSessionViewSet previously exposed no way to reach start_session/complete_session/cancel_session at all."""
    session = TrainingSessionFactory(status=TrainingSession.Status.SCHEDULED)
    coordinator = StaffUserFactory(roles=["training_coordinator"])
    client = login_as_staff(coordinator)

    assert client.post(f"/api/v1/training-sessions/{session.id}/start-session/").status_code == 200
    assert reload(session).status == TrainingSession.Status.IN_PROGRESS

    response = client.post(f"/api/v1/training-sessions/{session.id}/complete-session/")
    assert response.status_code == 200
    assert reload(session).status == TrainingSession.Status.COMPLETED


def test_session_fsm_actions_require_training_write_role(login_as_staff):
    session = TrainingSessionFactory(status=TrainingSession.Status.SCHEDULED)
    client = login_as_staff(StaffUserFactory())

    response = client.post(f"/api/v1/training-sessions/{session.id}/start-session/")

    assert response.status_code == 403


def test_enrollment_session_filter_returns_only_that_sessions_enrollments(login_as_staff):
    session = TrainingSessionFactory()
    matching = EnrollmentFactory(session=session)
    EnrollmentFactory()  # different session
    client = login_as_staff(StaffUserFactory())

    response = client.get(f"/api/v1/enrollments/?session={session.id}")

    assert response.status_code == 200
    ids = {e["id"] for e in response.data["results"]}
    assert ids == {matching.id}


def test_training_session_status_filter_supports_comma_separated_values(login_as_staff):
    scheduled = TrainingSessionFactory(status=TrainingSession.Status.SCHEDULED)
    cancelled = TrainingSessionFactory(status=TrainingSession.Status.CANCELLED)
    client = login_as_staff(StaffUserFactory())

    response = client.get("/api/v1/training-sessions/?status=scheduled")

    assert response.status_code == 200
    ids = {s["id"] for s in response.data["results"]}
    assert scheduled.id in ids
    assert cancelled.id not in ids
