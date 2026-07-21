"""
Segregation-of-duties guard (Blueprint Section 2.1 item 3a, ASTM E1578-18
6.6.1): apps.review.services.check_can_approve, exercised through the real
POST /samples/{id}/review and /approve actions so the guard's actual wiring
into SampleViewSet.approve is what's under test, not the function in
isolation.
"""

import pytest

from apps.samples.models import Sample, ServiceLine
from tests.factories import SampleFactory, StaffUserFactory
from tests.helpers import reload

pytestmark = pytest.mark.django_db


def test_water_environmental_same_reviewer_and_approver_is_blocked(login_as_staff):
    sample = SampleFactory(service_line=ServiceLine.WATER_ENVIRONMENTAL, status=Sample.Status.UNDER_REVIEW)
    dual_role_staff = StaffUserFactory(roles=["reviewer", "approver"])

    client = login_as_staff(dual_role_staff)
    review_response = client.post(f"/api/v1/samples/{sample.id}/review/", {"comments": "looks fine"})
    assert review_response.status_code == 201

    approve_response = client.post(f"/api/v1/samples/{sample.id}/approve/")

    assert approve_response.status_code == 400
    assert "different person" in str(approve_response.data).lower()
    assert reload(sample).status == Sample.Status.UNDER_REVIEW  # guard runs before the FSM transition


def test_water_environmental_different_approver_succeeds(login_as_staff):
    sample = SampleFactory(service_line=ServiceLine.WATER_ENVIRONMENTAL, status=Sample.Status.UNDER_REVIEW)
    reviewer = StaffUserFactory(roles=["reviewer"])
    approver = StaffUserFactory(roles=["approver"])

    client = login_as_staff(reviewer)
    assert client.post(f"/api/v1/samples/{sample.id}/review/", {"comments": "ok"}).status_code == 201

    client = login_as_staff(approver)
    response = client.post(f"/api/v1/samples/{sample.id}/approve/")

    assert response.status_code == 201
    assert reload(sample).status == Sample.Status.APPROVED


def test_failure_analysis_self_approve_bypass_permitted(login_as_staff):
    sample = SampleFactory(service_line=ServiceLine.FAILURE_ANALYSIS, status=Sample.Status.UNDER_REVIEW)
    dual_role_staff = StaffUserFactory(roles=["reviewer", "approver"])

    client = login_as_staff(dual_role_staff)
    assert client.post(f"/api/v1/samples/{sample.id}/review/", {"comments": "ok"}).status_code == 201

    response = client.post(f"/api/v1/samples/{sample.id}/approve/")

    assert response.status_code == 201
    assert reload(sample).status == Sample.Status.APPROVED
