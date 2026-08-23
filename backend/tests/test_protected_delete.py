"""
A delete refused by the schema must be a 409, not a 500.

on_delete=PROTECT raises django.db.models.deletion.ProtectedError, which
DRF does not recognise, so it escaped as an unhandled exception. Three
routes did this -- DELETE on test-methods, training-sessions and
training-courses -- each reachable by a fully authorised member of staff
doing something reasonable: retiring a method that has been used,
cancelling a course somebody enrolled in.

The status matters beyond tidiness. A 500 tells the caller the server is
broken and puts a traceback in the log for an outcome the schema
deliberately arranged; a 409 tells them the request was fine and the
current state of other records is what stopped it.
"""

import pytest

from apps.accounts.models import Role
from apps.testing.models import TestMethod
from tests.factories import (
    CustomerUserFactory, EnrollmentFactory, OrderFactory, RoleFactory, SampleFactory,
    StaffUserFactory, TestMethodFactory, TestRequestFactory, TrainingCourseFactory,
    TrainingSessionFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def privileged(login_as_staff):
    """Every role, so nothing below is confused with an authorisation failure."""
    user = StaffUserFactory()
    for name in Role.RoleName.values:
        user.roles.add(RoleFactory(name=name))
    return login_as_staff(user)


def test_deleting_a_referenced_test_method_is_a_conflict(privileged):
    method = TestMethodFactory()
    TestRequestFactory(sample=SampleFactory(order=OrderFactory()), test_method=method)

    response = privileged.delete(f"/api/v1/test-methods/{method.pk}/")

    assert response.status_code == 409, (
        f"expected 409, got {response.status_code} -- an uncaught ProtectedError is a 500"
    )
    assert TestMethod.objects.filter(pk=method.pk).exists()


def test_the_conflict_names_what_is_blocking_it(privileged):
    """A bare refusal leaves the caller guessing which relationship stopped them."""
    method = TestMethodFactory()
    test_request = TestRequestFactory(
        sample=SampleFactory(order=OrderFactory()), test_method=method
    )

    body = privileged.delete(f"/api/v1/test-methods/{method.pk}/").json()

    assert "referenced_by" in body
    assert str(test_request) in body["referenced_by"]


def test_deleting_a_referenced_training_session_is_a_conflict(privileged):
    session = TrainingSessionFactory()
    EnrollmentFactory(session=session, customer=CustomerUserFactory())

    assert privileged.delete(f"/api/v1/training-sessions/{session.pk}/").status_code == 409


def test_deleting_a_referenced_training_course_is_a_conflict(privileged):
    course = TrainingCourseFactory()
    TrainingSessionFactory(course=course)

    assert privileged.delete(f"/api/v1/training-courses/{course.pk}/").status_code == 409


def test_an_unreferenced_row_still_deletes(privileged):
    """
    The positive control: the handler must not turn every delete into a
    conflict, only the ones the schema actually refuses.
    """
    method = TestMethodFactory()

    assert privileged.delete(f"/api/v1/test-methods/{method.pk}/").status_code == 204
    assert not TestMethod.objects.filter(pk=method.pk).exists()


def test_ordinary_errors_are_untouched_by_the_handler(privileged):
    """
    The handler wraps DRF's own, so everything DRF already handled must
    still come back the same way -- a missing row is a 404, not a 409.
    """
    assert privileged.delete("/api/v1/test-methods/99999999/").status_code == 404
    assert privileged.post("/api/v1/test-methods/", {}, format="json").status_code == 400
