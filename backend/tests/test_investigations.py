"""FR-E9-01: closing an Investigation is only possible via POST .../close/, which sets closed_at atomically."""

import pytest

from apps.investigations.models import Investigation
from tests.factories import InvestigationFactory, SampleFactory, StaffUserFactory

pytestmark = pytest.mark.django_db


def test_close_sets_status_and_closed_at_atomically(login_as_staff):
    investigation = InvestigationFactory(status=Investigation.Status.CAPA_IN_PROGRESS)
    qa = StaffUserFactory(roles=["qa_officer"])
    client = login_as_staff(qa)

    assert investigation.closed_at is None

    response = client.post(f"/api/v1/investigations/{investigation.id}/close/")

    assert response.status_code == 200
    investigation.refresh_from_db()
    assert investigation.status == Investigation.Status.CLOSED
    assert investigation.closed_at is not None


def test_cannot_close_an_already_closed_investigation(login_as_staff):
    investigation = InvestigationFactory(status=Investigation.Status.CLOSED)
    qa = StaffUserFactory(roles=["qa_officer"])
    client = login_as_staff(qa)

    response = client.post(f"/api/v1/investigations/{investigation.id}/close/")

    assert response.status_code == 400


def test_write_requires_qa_officer_or_lab_supervisor_role(login_as_staff):
    investigation = InvestigationFactory()
    analyst = StaffUserFactory(roles=["analyst"])
    client = login_as_staff(analyst)

    response = client.post(f"/api/v1/investigations/{investigation.id}/close/")

    assert response.status_code == 403


def test_status_filter_supports_comma_separated_values(login_as_staff):
    open_inv = InvestigationFactory(status=Investigation.Status.OPEN)
    closed_inv = InvestigationFactory(status=Investigation.Status.CLOSED)
    client = login_as_staff(StaffUserFactory())

    response = client.get("/api/v1/investigations/?status=open")

    assert response.status_code == 200
    ids = {i["id"] for i in response.data["results"]}
    assert open_inv.id in ids
    assert closed_inv.id not in ids


def test_related_sample_filter_returns_only_that_samples_investigations(login_as_staff):
    sample = SampleFactory()
    matching = InvestigationFactory(related_sample=sample)
    InvestigationFactory()  # different sample
    client = login_as_staff(StaffUserFactory())

    response = client.get(f"/api/v1/investigations/?related_sample={sample.id}")

    assert response.status_code == 200
    ids = {i["id"] for i in response.data["results"]}
    assert ids == {matching.id}


def test_related_sample_code_is_included_for_display(login_as_staff):
    sample = SampleFactory(unique_sample_code="NASAT-999999")
    investigation = InvestigationFactory(related_sample=sample)
    client = login_as_staff(StaffUserFactory())

    response = client.get(f"/api/v1/investigations/{investigation.id}/")

    assert response.status_code == 200
    assert response.data["related_sample_code"] == "NASAT-999999"
