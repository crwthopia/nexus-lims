"""
Customer Portal reports route (GET /my/reports/ and its download action).

The isolation assertions here are the point of the file. `report` was a
staff-only table until this route existed, so this is the first time a
customer-authenticated request reaches it, and the boundary is asserted at
both layers the project relies on everywhere else: through the API, and
directly against the database connection with the ORM out of the picture
(apps/reporting/migrations/0003 added the RLS policy this proves).
"""

import pytest
from django.db import connection

from apps.reporting.models import Report
from apps.samples.models import Sample
from tests.factories import CustomerUserFactory, OrderFactory, SampleFactory, StaffUserFactory

pytestmark = pytest.mark.django_db


def ready_report(customer=None, sample=None, order=None, status=Report.Status.READY, version=1):
    """A Report belonging to `customer`, in `status`, with a plausible object key."""
    if sample is None and order is None:
        order = OrderFactory(customer=customer or CustomerUserFactory())
        sample = SampleFactory(order=order)
        Sample.objects.filter(pk=sample.pk).update(status=Sample.Status.APPROVED)
    report = Report.objects.create(
        sample=sample,
        order=order,
        report_type=Report.ReportType.WATER_ENVIRONMENTAL_COA,
        generated_by=StaffUserFactory(),
        version=version,
    )
    Report.objects.filter(pk=report.pk).update(
        status=status,
        file_id=f"reports/water_environmental_coa/{report.pk}-v{version}.pdf" if status == Report.Status.READY else "",
    )
    report.refresh_from_db()
    return report


# --- Isolation -------------------------------------------------------------

def test_a_customer_sees_only_their_own_reports(login_as_customer):
    mine = CustomerUserFactory()
    theirs = CustomerUserFactory()
    my_report = ready_report(customer=mine)
    ready_report(customer=theirs)
    client = login_as_customer(mine)

    response = client.get("/api/v1/my/reports/")

    assert response.status_code == 200
    assert [r["id"] for r in response.json()["results"]] == [my_report.pk]


def test_another_customers_report_is_a_404_not_a_403(login_as_customer):
    # 403 would confirm the report exists. The scoped queryset makes it
    # indistinguishable from an id that was never issued.
    mine = CustomerUserFactory()
    theirs = ready_report(customer=CustomerUserFactory())
    client = login_as_customer(mine)

    assert client.get(f"/api/v1/my/reports/{theirs.pk}/").status_code == 404
    assert client.get(f"/api/v1/my/reports/{theirs.pk}/download/").status_code == 404


def test_the_database_policy_isolates_reports_without_the_orm(monkeypatch):
    """
    The ORM filter removed from the picture entirely: set the RLS session
    variables by hand, exactly as RLSContextMiddleware does, and run a raw
    SELECT. This is what makes the viewset's filter defense in depth rather
    than the only thing standing between two customers.
    """
    customer_a = CustomerUserFactory()
    customer_b = CustomerUserFactory()
    report_a = ready_report(customer=customer_a)
    ready_report(customer=customer_b)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('rls.is_staff', 'false', false), set_config('rls.customer_id', %s, false)",
            [str(customer_a.id)],
        )
        cursor.execute("SELECT id FROM report")
        assert {row[0] for row in cursor.fetchall()} == {report_a.pk}

        # No customer context: default deny, not "everything".
        cursor.execute(
            "SELECT set_config('rls.is_staff', 'false', false), set_config('rls.customer_id', '0', false)"
        )
        cursor.execute("SELECT id FROM report")
        assert cursor.fetchall() == []

        # Staff bypass still works, or the Staff Console's Reports screen goes blank.
        cursor.execute(
            "SELECT set_config('rls.is_staff', 'true', false), set_config('rls.customer_id', '0', false)"
        )
        cursor.execute("SELECT id FROM report")
        assert len(cursor.fetchall()) == 2


def test_a_training_certificate_reaches_its_customer_through_the_order(login_as_customer):
    # A COA hangs off a sample; a CPD certificate hangs off an order only.
    # The RLS policy and the queryset both have to cover that second path.
    mine = CustomerUserFactory()
    order = OrderFactory(customer=mine)
    certificate = Report.objects.create(
        order=order,
        report_type=Report.ReportType.TRAINING_CPD_CERTIFICATE,
        generated_by=StaffUserFactory(),
    )
    Report.objects.filter(pk=certificate.pk).update(
        status=Report.Status.READY, file_id="reports/training_cpd_certificate/1-v1.pdf"
    )
    client = login_as_customer(mine)

    response = client.get("/api/v1/my/reports/")

    assert [r["id"] for r in response.json()["results"]] == [certificate.pk]


def test_staff_cannot_use_the_customer_route(login_as_staff):
    # The two identity domains stay separate here as everywhere else.
    ready_report()
    client = login_as_staff(StaffUserFactory())

    response = client.get("/api/v1/my/reports/")

    assert response.status_code in (401, 403)


def test_the_route_requires_authentication(api_client):
    ready_report()

    assert api_client.get("/api/v1/my/reports/").status_code in (401, 403)


# --- What a customer is shown ----------------------------------------------

def test_only_ready_reports_are_listed(login_as_customer):
    # pending/generating/failed are lab-internal states; a customer seeing a
    # failed row just files a support ticket about something already known.
    mine = CustomerUserFactory()
    order = OrderFactory(customer=mine)
    visible = ready_report(customer=mine)
    for hidden_status in (Report.Status.PENDING, Report.Status.GENERATING, Report.Status.FAILED):
        sample = SampleFactory(order=order)
        Sample.objects.filter(pk=sample.pk).update(status=Sample.Status.APPROVED)
        ready_report(sample=sample, order=order, status=hidden_status)
    client = login_as_customer(mine)

    response = client.get("/api/v1/my/reports/")

    assert [r["id"] for r in response.json()["results"]] == [visible.pk]


def test_internal_fields_are_not_exposed(login_as_customer):
    mine = CustomerUserFactory()
    ready_report(customer=mine)
    client = login_as_customer(mine)

    row = client.get("/api/v1/my/reports/").json()["results"][0]

    # file_id is an object-storage key; generated_by/failure_reason name staff
    # and internal errors. None of it belongs in a customer payload.
    assert "file_id" not in row
    assert "generated_by" not in row
    assert "failure_reason" not in row
    assert row["sample_code"]


def test_download_returns_a_presigned_url(login_as_customer, monkeypatch):
    mine = CustomerUserFactory()
    report = ready_report(customer=mine)
    monkeypatch.setattr(
        "apps.reporting.views.presigned_url",
        lambda key, **kw: f"https://oss.example/{key}?signature=abc",
    )
    client = login_as_customer(mine)

    response = client.get(f"/api/v1/my/reports/{report.pk}/download/")

    assert response.status_code == 200
    body = response.json()
    assert report.file_id in body["url"]
    assert body["expires_in"] > 0
