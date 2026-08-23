"""
Report PDF pipeline (Blueprint Section 2.1a): the FR-C6-03 creation guard,
the Celery task that renders and stores the document, and the download
endpoint that hands out a presigned URL.

The rendering half is tested against real WeasyPrint -- these assertions read
bytes out of an actual PDF -- because the failure this pipeline is most
likely to have is a template rendering to something malformed, and a mocked
renderer cannot see that. Object storage is stubbed in the tests that aren't
about object storage; the one that *is* talks to MinIO, in the same style as
test_audit_retention.py.
"""

import pytest

from apps.accounts.models import Role
from apps.reporting.models import Report
from apps.reporting.rendering import ReportTemplateMissing, render_report_html
from apps.reporting.tasks import build_report_context, generate_report_pdf, object_key_for
from apps.samples.models import Sample
from tests.factories import (
    OrderFactory,
    RoleFactory,
    SampleFactory,
    StaffUserFactory,
    TestMethodFactory,
    TestRequestFactory,
    TestResultFactory,
)

pytestmark = pytest.mark.django_db


def approved_sample(**kwargs):
    """A Sample in `approved`, which FR-C6-03 requires before a report exists."""
    sample = SampleFactory(**kwargs)
    Sample.objects.filter(pk=sample.pk).update(status=Sample.Status.APPROVED)
    sample.refresh_from_db()
    return sample


def report_issuer():
    """
    Staff who may issue a report. POST /reports/ takes REPORT_WRITE_ROLES
    (apps/reporting/views.py) -- issuing a certificate is the lab publishing
    a result, not something any authenticated account should do. The read and
    download tests below deliberately keep using a bare StaffUserFactory,
    since those stay open to any staff member.
    """
    issuer = StaffUserFactory()
    issuer.roles.add(RoleFactory(name=Role.RoleName.APPROVER))
    return issuer


def make_report(sample=None, order=None, report_type=Report.ReportType.WATER_ENVIRONMENTAL_COA):
    return Report.objects.create(
        sample=sample, order=order, report_type=report_type, generated_by=StaffUserFactory(),
    )


# --- Creation guard --------------------------------------------------------

def test_report_cannot_be_created_for_an_unapproved_sample(login_as_staff):
    sample = SampleFactory()  # pre_registered
    client = login_as_staff(report_issuer())

    response = client.post(
        "/api/v1/reports/",
        {"sample": sample.pk, "report_type": Report.ReportType.WATER_ENVIRONMENTAL_COA},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "approved" in str(response.json()).lower()
    assert Report.objects.count() == 0


def test_creating_a_report_starts_it_pending_with_no_file(login_as_staff):
    # The POST returns before any rendering happens -- the whole reason this
    # is a background job rather than inline in the request.
    sample = approved_sample()
    client = login_as_staff(report_issuer())

    response = client.post(
        "/api/v1/reports/",
        {"sample": sample.pk, "report_type": Report.ReportType.WATER_ENVIRONMENTAL_COA},
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == Report.Status.PENDING
    assert body["file_id"] == ""


def test_a_client_supplied_file_id_and_status_are_ignored(login_as_staff):
    # file_id is a pointer into the shared bucket; honouring a caller's value
    # would let one customer's report be attached to another's.
    sample = approved_sample()
    client = login_as_staff(report_issuer())

    response = client.post(
        "/api/v1/reports/",
        {
            "sample": sample.pk,
            "report_type": Report.ReportType.WATER_ENVIRONMENTAL_COA,
            "file_id": "reports/somebody-elses-report.pdf",
            "status": Report.Status.READY,
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    report = Report.objects.get(pk=response.json()["id"])
    assert report.file_id == ""
    assert report.status == Report.Status.PENDING


# --- Rendering -------------------------------------------------------------

def test_a_coa_renders_the_sample_and_its_results():
    sample = approved_sample(unique_sample_code="WE-2026-0042", client_reference="JOB-118")
    method = TestMethodFactory(name="Total Coliform", specification_limits={"max": 1.1})
    request = TestRequestFactory(sample=sample, test_method=method)
    TestResultFactory(test_request=request, value="0.4", unit="MPN/100mL")
    report = make_report(sample=sample)

    html = render_report_html(report, build_report_context(report))

    assert "WE-2026-0042" in html
    assert "Total Coliform" in html
    assert "0.4" in html
    assert "MPN/100mL" in html
    assert "≤ 1.1" in html


def test_a_multi_analyte_coa_labels_each_row():
    # The reason the analyte field exists reaches the document: a COA listing
    # twelve numbers without saying which element each one is would be
    # unusable to the customer receiving it.
    sample = approved_sample()
    method = TestMethodFactory(name="Heavy Metals (ICP-MS)")
    request = TestRequestFactory(sample=sample, test_method=method)
    TestResultFactory(test_request=request, analyte="Lead", value="0.4", unit="mg/L")
    TestResultFactory(test_request=request, analyte="Cadmium", value="0.1", unit="mg/L")
    report = make_report(sample=sample)

    html = render_report_html(report, build_report_context(report))

    assert "Lead" in html
    assert "Cadmium" in html
    assert "Parameter" in html  # the column header


def test_an_out_of_spec_result_is_marked_in_the_document():
    # A COA that doesn't distinguish an OOS result from a passing one is
    # actively misleading, so assert it on the rendered output.
    sample = approved_sample()
    TestResultFactory(test_request=TestRequestFactory(sample=sample), value="9.9", is_out_of_spec=True)
    report = make_report(sample=sample)

    html = render_report_html(report, build_report_context(report))

    assert "OOS" in html
    assert 'class="oos"' in html


def test_every_report_type_has_a_template():
    # A report_type with no template is otherwise only discoverable when
    # somebody requests that type in production.
    order = OrderFactory()
    sample = approved_sample()
    for report_type, _label in Report.ReportType.choices:
        report = make_report(sample=sample, order=order, report_type=report_type)

        html = render_report_html(report, build_report_context(report))

        # The product name, which every template inherits from _base.html.
        # Its absence means the type resolved to something that is not one
        # of ours, which is the failure this walk exists to catch.
        assert "NexusLIMS" in html


def test_an_unknown_report_type_raises_rather_than_falling_back():
    # Substituting a different template would produce an official-looking
    # document that says the wrong thing.
    report = make_report(sample=approved_sample())
    report.report_type = "no_such_type"

    with pytest.raises(ReportTemplateMissing):
        render_report_html(report, build_report_context(report))


def test_templates_are_marked_as_drafts():
    # Until QA authors the real layouts, nothing this pipeline emits may look
    # like an issued document.
    report = make_report(sample=approved_sample())

    html = render_report_html(report, build_report_context(report))

    assert "DRAFT TEMPLATE" in html
    assert "Not valid for issue" in html


def test_a_missing_context_key_fails_loudly():
    # StrictUndefined: a template referencing a field the context doesn't
    # supply must raise, not silently print an empty results column.
    from jinja2 import UndefinedError

    from apps.reporting.rendering import _env

    template = _env.from_string("{{ nonexistent_field }}")

    with pytest.raises(UndefinedError):
        template.render()


# --- Generation task -------------------------------------------------------

def test_it_produces_a_real_pdf_and_marks_the_report_ready(monkeypatch):
    sample = approved_sample()
    TestResultFactory(test_request=TestRequestFactory(sample=sample), value="1.0")
    report = make_report(sample=sample)
    uploaded = {}

    def fake_upload(key, data, content_type="application/octet-stream", bucket=None):
        uploaded.update(key=key, data=data, content_type=content_type)
        return key

    monkeypatch.setattr("apps.reporting.tasks.upload_object", fake_upload)

    result_key = generate_report_pdf(report.pk)

    report.refresh_from_db()
    assert report.status == Report.Status.READY
    assert report.file_id == result_key == object_key_for(report)
    assert report.failure_reason == ""
    # A real PDF, not merely a non-empty string.
    assert uploaded["data"].startswith(b"%PDF-")
    assert len(uploaded["data"]) > 1000
    assert uploaded["content_type"] == "application/pdf"


def test_the_object_key_is_versioned_so_a_correction_cannot_overwrite_the_issued_pdf():
    # FR-E17-01/03: a corrected report is a new row with a higher version. If
    # both shared a key, issuing the correction would silently replace the
    # document the customer already holds.
    sample = approved_sample()
    first = make_report(sample=sample)
    second = make_report(sample=sample)
    Report.objects.filter(pk=second.pk).update(version=2)
    second.refresh_from_db()

    assert object_key_for(first) != object_key_for(second)
    assert object_key_for(second).endswith("-v2.pdf")


def test_a_failure_is_recorded_on_the_row_and_re_raised(monkeypatch):
    report = make_report(sample=approved_sample())

    def boom(*args, **kwargs):
        raise RuntimeError("object storage exploded")

    monkeypatch.setattr("apps.reporting.tasks.upload_object", boom)

    with pytest.raises(RuntimeError):
        generate_report_pdf(report.pk)

    report.refresh_from_db()
    # Both halves matter: the row is what the Reports screen reads, the
    # exception is what surfaces in Celery's own monitoring.
    assert report.status == Report.Status.FAILED
    assert "object storage exploded" in report.failure_reason
    assert report.file_id == ""


def test_a_missing_template_fails_the_report_rather_than_hanging_it():
    report = make_report(sample=approved_sample())
    Report.objects.filter(pk=report.pk).update(report_type="no_such_type")

    with pytest.raises(ReportTemplateMissing):
        generate_report_pdf(report.pk)

    report.refresh_from_db()
    assert report.status == Report.Status.FAILED
    assert "no_such_type" in report.failure_reason


# --- Download endpoint -----------------------------------------------------

def test_a_pending_report_answers_409_with_its_status(login_as_staff):
    report = make_report(sample=approved_sample())
    client = login_as_staff(StaffUserFactory())

    response = client.get(f"/api/v1/reports/{report.pk}/download/")

    # 409 rather than 404: the report exists, it just isn't finished, and a
    # polling client has to tell those apart.
    assert response.status_code == 409
    assert response.json()["status"] == Report.Status.PENDING


def test_a_failed_report_reports_why(login_as_staff):
    report = make_report(sample=approved_sample())
    Report.objects.filter(pk=report.pk).update(
        status=Report.Status.FAILED, failure_reason="TemplateSyntaxError: unexpected '%'",
    )
    client = login_as_staff(StaffUserFactory())

    response = client.get(f"/api/v1/reports/{report.pk}/download/")

    assert response.status_code == 409
    assert "TemplateSyntaxError" in response.json()["failure_reason"]


def test_a_ready_report_returns_a_presigned_url(login_as_staff, monkeypatch):
    report = make_report(sample=approved_sample())
    Report.objects.filter(pk=report.pk).update(
        status=Report.Status.READY, file_id="reports/water_environmental_coa/1-v1.pdf",
    )
    monkeypatch.setattr(
        "apps.reporting.views.presigned_url",
        lambda key, **kw: f"https://oss.example/{key}?signature=abc",
    )
    client = login_as_staff(StaffUserFactory())

    response = client.get(f"/api/v1/reports/{report.pk}/download/")

    assert response.status_code == 200
    body = response.json()
    assert body["url"].startswith("https://oss.example/reports/water_environmental_coa/1-v1.pdf")
    assert body["expires_in"] > 0


def test_download_requires_authentication(api_client):
    report = make_report(sample=approved_sample())

    response = api_client.get(f"/api/v1/reports/{report.pk}/download/")

    assert response.status_code in (401, 403)


def test_status_filter_actually_filters(login_as_staff):
    # Same class of bug the Review Queue and Testing Queue both surfaced.
    sample = approved_sample()
    ready = make_report(sample=sample)
    Report.objects.filter(pk=ready.pk).update(status=Report.Status.READY)
    make_report(sample=sample)  # stays pending
    client = login_as_staff(StaffUserFactory())

    response = client.get("/api/v1/reports/?status=ready")

    ids = [r["id"] for r in response.json()["results"]]
    assert ids == [ready.pk]


# --- Real object storage ---------------------------------------------------
# Needs a running MinIO, like test_audit_retention.py's OSS test. CI provides
# one; see the README's Running the test suite section.

def test_the_pipeline_uploads_a_retrievable_pdf():
    from django.conf import settings

    from apps.audit.oss import ensure_bucket, get_client

    ensure_bucket()
    sample = approved_sample()
    TestResultFactory(test_request=TestRequestFactory(sample=sample), value="2.5")
    report = make_report(sample=sample)

    key = generate_report_pdf(report.pk)

    stored = get_client().get_object(Bucket=settings.OSS_BUCKET_NAME, Key=key)
    body = stored["Body"].read()
    assert body.startswith(b"%PDF-")
    assert stored["ContentType"] == "application/pdf"
    report.refresh_from_db()
    assert report.status == Report.Status.READY


def test_the_list_includes_display_fields_a_ui_can_render(login_as_staff):
    # Without these a Reports screen sees only FK ids and has to issue a
    # request per row to show a sample code.
    staff = StaffUserFactory(display_name="R. Santos")
    sample = approved_sample(unique_sample_code="WE-2026-0100")
    Report.objects.create(
        sample=sample,
        report_type=Report.ReportType.WATER_ENVIRONMENTAL_COA,
        generated_by=staff,
    )
    client = login_as_staff(StaffUserFactory())

    row = client.get("/api/v1/reports/").json()["results"][0]

    assert row["sample_code"] == "WE-2026-0100"
    assert row["generated_by_display_name"] == "R. Santos"
