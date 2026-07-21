"""
FR-C3-02 competency check and FR-C3-08 OOS auto-flag
(apps/testing/serializers.py TestResultSerializer), exercised through the
real POST /test-requests/{id}/results/ action.
"""

import datetime

import pytest
from django.utils import timezone

from tests.factories import StaffUserFactory, StandardReagentFactory, TestRequestFactory

pytestmark = pytest.mark.django_db


def _post_result(client, test_request, **payload):
    return client.post(f"/api/v1/test-requests/{test_request.id}/results/", payload, format="json")


def test_uncertified_analyst_is_blocked_from_entering_a_result(login_as_staff):
    test_request = TestRequestFactory()
    analyst = StaffUserFactory(roles=["analyst"])  # no instrument_certifications for this method
    client = login_as_staff(analyst)

    response = _post_result(client, test_request, data_type="float", value="5.0")

    assert response.status_code == 400
    assert "not certified" in str(response.data).lower()


def test_certified_analyst_can_enter_result(login_as_staff):
    test_request = TestRequestFactory()
    analyst = StaffUserFactory(roles=["analyst"], instrument_certifications=[test_request.test_method])
    client = login_as_staff(analyst)

    response = _post_result(client, test_request, data_type="float", value="5.0")

    assert response.status_code == 201
    assert response.data["entered_by"] == analyst.id


def test_out_of_spec_value_is_auto_flagged(login_as_staff):
    test_method = TestRequestFactory().test_method
    test_method.specification_limits = {"min": 0, "max": 10}
    test_method.save(update_fields=["specification_limits"])
    test_request = TestRequestFactory(test_method=test_method)
    analyst = StaffUserFactory(roles=["analyst"], instrument_certifications=[test_method])
    client = login_as_staff(analyst)

    in_spec = _post_result(client, test_request, data_type="float", value="5.0")
    assert in_spec.status_code == 201
    assert in_spec.data["is_out_of_spec"] is False

    out_of_spec = _post_result(client, test_request, data_type="float", value="15.0")
    assert out_of_spec.status_code == 201
    assert out_of_spec.data["is_out_of_spec"] is True


def test_client_supplied_is_out_of_spec_is_ignored(login_as_staff):
    """is_out_of_spec is read-only: a client can't smuggle a false in-spec flag past the server-side computation."""
    test_method = TestRequestFactory().test_method
    test_method.specification_limits = {"min": 0, "max": 10}
    test_method.save(update_fields=["specification_limits"])
    test_request = TestRequestFactory(test_method=test_method)
    analyst = StaffUserFactory(roles=["analyst"], instrument_certifications=[test_method])
    client = login_as_staff(analyst)

    response = _post_result(client, test_request, data_type="float", value="15.0", is_out_of_spec=False)

    assert response.status_code == 201
    assert response.data["is_out_of_spec"] is True


def test_expired_standard_reagent_is_rejected(login_as_staff):
    test_request = TestRequestFactory()
    analyst = StaffUserFactory(roles=["analyst"], instrument_certifications=[test_request.test_method])
    expired_reagent = StandardReagentFactory(expiry_date=timezone.localdate() - datetime.timedelta(days=1))
    client = login_as_staff(analyst)

    response = _post_result(
        client, test_request, data_type="float", value="1.0", standard_reagents=[expired_reagent.id]
    )

    assert response.status_code == 400
    assert "active, non-expired" in str(response.data).lower()
