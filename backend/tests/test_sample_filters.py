"""
GET /samples/?status= and ?service_line= (apps/samples/views.py
SampleViewSet.get_queryset). Regression test for a real bug: DRF silently
ignores unrecognized query params rather than erroring, so before
get_queryset() was overridden to filter on them, ?status=under_review
returned every sample regardless -- the Staff Console's Review Queue
(frontend/src/pages/ReviewQueue.tsx) depends on this actually filtering.
"""

import pytest

from apps.samples.models import Sample, ServiceLine
from tests.factories import SampleFactory, StaffUserFactory

pytestmark = pytest.mark.django_db


def test_status_filter_returns_only_matching_samples(login_as_staff):
    SampleFactory(status=Sample.Status.PRE_REGISTERED)
    under_review = SampleFactory(status=Sample.Status.UNDER_REVIEW)
    client = login_as_staff(StaffUserFactory())

    response = client.get("/api/v1/samples/?status=under_review")

    assert response.status_code == 200
    ids = {s["id"] for s in response.data["results"]}
    assert ids == {under_review.id}


def test_service_line_filter_returns_only_matching_samples(login_as_staff):
    SampleFactory(service_line=ServiceLine.FAILURE_ANALYSIS)
    water = SampleFactory(service_line=ServiceLine.WATER_ENVIRONMENTAL)
    client = login_as_staff(StaffUserFactory())

    response = client.get("/api/v1/samples/?service_line=water_environmental")

    assert response.status_code == 200
    ids = {s["id"] for s in response.data["results"]}
    assert ids == {water.id}


def test_no_filter_returns_everything(login_as_staff):
    SampleFactory(status=Sample.Status.PRE_REGISTERED)
    SampleFactory(status=Sample.Status.UNDER_REVIEW)
    client = login_as_staff(StaffUserFactory())

    response = client.get("/api/v1/samples/")

    assert response.status_code == 200
    assert response.data["count"] == 2
