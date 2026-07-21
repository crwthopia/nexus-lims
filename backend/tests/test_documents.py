"""FR-D1-03 document version approval (apps/documents/views.py DocumentVersionViewSet.approve)."""

import pytest

from apps.documents.models import DocumentVersion
from tests.factories import DocumentFactory, DocumentVersionFactory, StaffUserFactory

pytestmark = pytest.mark.django_db


def test_approving_a_version_archives_prior_current_and_syncs_document(login_as_staff):
    document = DocumentFactory()
    v1 = DocumentVersionFactory(document=document, version_number=1)
    qa = StaffUserFactory(roles=["qa_officer"])
    client = login_as_staff(qa)

    approve_v1 = client.post(f"/api/v1/document-versions/{v1.id}/approve/")
    assert approve_v1.status_code == 200
    v1.refresh_from_db()
    document.refresh_from_db()
    assert v1.is_current
    assert v1.approved_by_id == qa.id
    assert document.current_version_id == v1.id

    v2 = DocumentVersionFactory(document=document, version_number=2)
    approve_v2 = client.post(f"/api/v1/document-versions/{v2.id}/approve/")
    assert approve_v2.status_code == 200

    v1.refresh_from_db()
    v2.refresh_from_db()
    document.refresh_from_db()
    assert v1.is_current is False  # archived, not deleted
    assert DocumentVersion.objects.filter(pk=v1.pk).exists()
    assert v2.is_current is True
    assert document.current_version_id == v2.id


def test_write_requires_qa_officer_or_lab_supervisor_role(login_as_staff):
    analyst = StaffUserFactory(roles=["analyst"])
    client = login_as_staff(analyst)

    response = client.post("/api/v1/documents/", {"title": "New SOP", "type": "sop"}, format="json")

    assert response.status_code == 403
