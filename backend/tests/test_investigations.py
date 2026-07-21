"""FR-E9-01: closing an Investigation is only possible via POST .../close/, which sets closed_at atomically."""

import pytest

from apps.investigations.models import Investigation
from tests.factories import InvestigationFactory, StaffUserFactory

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
