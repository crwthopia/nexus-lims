"""
GET /test-requests/?sample= and ?status= (apps/testing/views.py
TestRequestViewSet.get_queryset). Same class of gap as SampleViewSet had
before its own status/service_line filter was added: DRF silently ignores
unrecognized query params, so without this override neither filter did
anything server-side. Needed by the Staff Console's Testing Queue
(?status=assigned,in_progress) and Sample detail's Test Requests panel
(?sample=).
"""

import pytest

from apps.testing.models import TestRequest
from tests.factories import SampleFactory, StaffUserFactory, TestRequestFactory

pytestmark = pytest.mark.django_db


def test_sample_filter_returns_only_that_samples_requests(login_as_staff):
    sample = SampleFactory()
    matching = TestRequestFactory(sample=sample)
    TestRequestFactory()  # different sample
    client = login_as_staff(StaffUserFactory())

    response = client.get(f"/api/v1/test-requests/?sample={sample.id}")

    assert response.status_code == 200
    ids = {tr["id"] for tr in response.data["results"]}
    assert ids == {matching.id}


def test_status_filter_supports_comma_separated_values(login_as_staff):
    assigned = TestRequestFactory(status=TestRequest.Status.ASSIGNED)
    in_progress = TestRequestFactory(status=TestRequest.Status.IN_PROGRESS)
    TestRequestFactory(status=TestRequest.Status.COMPLETED)
    client = login_as_staff(StaffUserFactory())

    response = client.get("/api/v1/test-requests/?status=assigned,in_progress")

    assert response.status_code == 200
    ids = {tr["id"] for tr in response.data["results"]}
    assert ids == {assigned.id, in_progress.id}
