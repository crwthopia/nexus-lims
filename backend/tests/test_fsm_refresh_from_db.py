"""
Regression test for a latent bug found while writing this test suite:
Sample, TestRequest, TrainingSession, and Enrollment all declare a
django-fsm-2 FSMField(protected=True) but didn't mix in
django_fsm.FSMModelMixin. Model.refresh_from_db() does a plain setattr()
for every concrete field, and the protected FSM descriptor rejects any
second direct assignment on an existing instance -- so calling
refresh_from_db() on any of these raised AttributeError: "Direct status
modification is not allowed", even though no application code happened to
call it. FSMModelMixin (now applied to all four models) teaches
refresh_from_db() to skip protected FSM fields instead of reassigning them.
"""

import pytest

from apps.samples.models import Sample
from apps.testing.models import TestRequest
from apps.training.models import Enrollment, TrainingSession
from tests.factories import EnrollmentFactory, SampleFactory, TestRequestFactory, TrainingSessionFactory

pytestmark = pytest.mark.django_db


def test_sample_refresh_from_db_does_not_raise():
    sample = SampleFactory(status=Sample.Status.PRE_REGISTERED)
    sample.refresh_from_db()
    assert sample.status == Sample.Status.PRE_REGISTERED


def test_test_request_refresh_from_db_does_not_raise():
    test_request = TestRequestFactory()
    test_request.refresh_from_db()
    assert test_request.status == TestRequest.Status.ASSIGNED


def test_training_session_refresh_from_db_does_not_raise():
    session = TrainingSessionFactory()
    session.refresh_from_db()
    assert session.status == TrainingSession.Status.SCHEDULED


def test_enrollment_refresh_from_db_does_not_raise():
    enrollment = EnrollmentFactory()
    enrollment.refresh_from_db()
    assert enrollment.status == Enrollment.Status.CONFIRMED
