"""
Sample FSM transitions (Blueprint Section 2.1 item 3a) driven through the
real API actions, not by calling the @transition methods directly -- the
role gate (SampleViewSet._ROLE_MAP) and the illegal-transition-to-400
translation both live at the view layer.
"""

import pytest

from apps.samples.models import Sample
from tests.factories import SampleFactory, StaffUserFactory
from tests.helpers import reload

pytestmark = pytest.mark.django_db


def _post(client, sample, action):
    return client.post(f"/api/v1/samples/{sample.id}/{action}/")


def test_full_intake_to_review_happy_path(login_as_staff):
    sample = SampleFactory(status=Sample.Status.PRE_REGISTERED)
    receiver = StaffUserFactory(roles=["sample_receiver"])
    analyst = StaffUserFactory(roles=["analyst"])

    client = login_as_staff(receiver)
    assert _post(client, sample, "register").status_code == 200
    assert _post(client, sample, "receive").status_code == 200

    client = login_as_staff(analyst)
    assert _post(client, sample, "start-prep").status_code == 200
    assert _post(client, sample, "start-testing").status_code == 200
    response = _post(client, sample, "submit-for-review")
    assert response.status_code == 200
    assert response.data["status"] == Sample.Status.UNDER_REVIEW

    assert reload(sample).status == Sample.Status.UNDER_REVIEW


def test_illegal_transition_returns_400_and_leaves_status_unchanged(login_as_staff):
    sample = SampleFactory(status=Sample.Status.PRE_REGISTERED)
    approver = StaffUserFactory(roles=["approver"])
    client = login_as_staff(approver)

    response = _post(client, sample, "approve")

    assert response.status_code == 400
    assert reload(sample).status == Sample.Status.PRE_REGISTERED


def test_role_gate_blocks_wrong_role(login_as_staff):
    sample = SampleFactory(status=Sample.Status.PRE_REGISTERED)
    analyst = StaffUserFactory(roles=["analyst"])  # not sample_receiver
    client = login_as_staff(analyst)

    response = _post(client, sample, "register")

    assert response.status_code == 403
    assert reload(sample).status == Sample.Status.PRE_REGISTERED


def test_reject_routes_to_under_investigation_not_retest_pending(login_as_staff):
    """ISO/IEC 17025:2017 7.10 nonconforming-work routing (closes Blueprint Section 13 gap 12)."""
    sample = SampleFactory(status=Sample.Status.UNDER_REVIEW)
    approver = StaffUserFactory(roles=["approver"])
    client = login_as_staff(approver)

    response = _post(client, sample, "reject")

    assert response.status_code == 201
    assert reload(sample).status == Sample.Status.UNDER_INVESTIGATION


def test_investigation_resolution_requeues_into_testing(login_as_staff):
    sample = SampleFactory(status=Sample.Status.UNDER_INVESTIGATION)
    qa = StaffUserFactory(roles=["qa_officer"])
    client = login_as_staff(qa)

    assert _post(client, sample, "authorize-retest").status_code == 200
    assert reload(sample).status == Sample.Status.RETEST_PENDING

    response = _post(client, sample, "requeue-for-retest")
    assert response.status_code == 200
    assert reload(sample).status == Sample.Status.IN_TESTING
