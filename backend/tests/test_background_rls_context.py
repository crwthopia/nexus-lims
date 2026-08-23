"""
Background jobs must be able to see the rows they operate on.

Every RLS policy here is written against two Postgres session variables set
by RLSContextMiddleware. Nothing set them off-request, so a Celery worker's
connection had neither, both policies failed closed, and every
RLS-protected table read as empty inside a task. `generate_report_pdf`
raised Report.DoesNotExist for a report that existed -- no Certificate of
Analysis could be produced by a worker at all.

`worker_connection` below reproduces that state. A real worker's variables
are unset (NULL); it sets them to the explicit deny values instead, which
reaches the identical policy outcome without tripping the separate
`''::bigint` failure described in apps/common/rls.py. What matters is that
the connection has no staff bypass and no customer, which is what a worker
had.
"""

import datetime

import pytest
from django.db import connection
from django.utils import timezone

from apps.audit.tasks import run_retention_sweep
from apps.common.rls import system_rls_context
from apps.reporting.models import Report
from apps.samples.models import Order, Sample
from apps.training.models import CreditNote, Enrollment
from apps.training.tasks import check_session_capacity
from tests.factories import (
    CustomerUserFactory, EnrollmentFactory, InvoiceFactory, OrderFactory,
    SampleFactory, StaffUserFactory, TrainingSessionFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def worker_connection():
    """Strips the staff bypass conftest applies, leaving a task's own context."""

    def _strip():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('rls.is_staff', 'false', false), "
                "set_config('rls.customer_id', '0', false)"
            )

    return _strip


def _ready_report():
    order = OrderFactory(customer=CustomerUserFactory())
    sample = SampleFactory(order=order)
    Sample.objects.filter(pk=sample.pk).update(status=Sample.Status.APPROVED)
    return Report.objects.create(
        sample=sample,
        order=order,
        report_type=Report.ReportType.WATER_ENVIRONMENTAL_COA,
        generated_by=StaffUserFactory(),
        version=1,
    )


def test_a_task_sees_rls_protected_rows(worker_connection):
    """The regression: without the task_prerun handler this count is 0."""
    _ready_report()
    worker_connection()

    from config.celery import app

    @app.task(name="tests.count_rls_tables")
    def _count():
        return (Report.objects.count(), Sample.objects.count(), Order.objects.count())

    reports, samples, orders = _count.apply().get()

    assert reports > 0, "a task cannot see report rows -- RLS context missing"
    assert samples > 0, "a task cannot see sample rows -- RLS context missing"
    assert orders > 0, "a task cannot see order rows -- RLS context missing"


def test_report_generation_finds_its_report_in_a_worker(worker_connection, monkeypatch):
    """
    The concrete failure this closes: generate_report_pdf fetches by pk and
    raised DoesNotExist on a row that existed.
    """
    report = _ready_report()
    worker_connection()

    from apps.reporting.tasks import generate_report_pdf

    # Object storage is stubbed the same way test_report_generation.py does
    # it: this test is about whether the task can *find* its row, not about
    # the upload. The PDF is still really rendered.
    monkeypatch.setattr(
        "apps.reporting.tasks.upload_object",
        lambda key, data, content_type="application/octet-stream", bucket=None: key,
    )

    generate_report_pdf.apply(args=[report.pk]).get()

    report.refresh_from_db()
    assert report.status == Report.Status.READY, (
        f"task did not produce the report (status {report.status!r}, "
        f"reason {report.failure_reason!r})"
    )


def test_the_capacity_task_reads_and_writes_rls_tables_off_request(worker_connection):
    """
    The beat task that touches the most RLS-protected tables at once: it
    reads `enrollment`, reads `invoice` to total what was paid, and writes
    `credit_note`. All three carry policies, and the write is governed by
    them too -- these policies are FOR ALL with no separate WITH CHECK, so
    USING applies to the INSERT as well.

    Set up to actually reach that path rather than merely to run: a session
    inside its cancellation window, under its minimum, with one confirmed
    and paid enrollment. An earlier version of this test just called the
    task and asserted nothing; the conditions were never met, so it passed
    without touching a single protected table and survived deleting the fix
    it was meant to guard.
    """
    session = TrainingSessionFactory(
        min_capacity=5,
        cancellation_threshold_days=7,
        start_date=timezone.now() + datetime.timedelta(days=3),
    )
    enrollment = EnrollmentFactory(session=session, status=Enrollment.Status.CONFIRMED)
    InvoiceFactory(enrollment=enrollment, order=None, amount="5000.00", status="paid")
    worker_connection()

    check_session_capacity.apply().get()

    with system_rls_context():
        assert CreditNote.objects.filter(source_enrollment=enrollment).exists(), (
            "the task did not issue a credit note -- it could not see or write "
            "the RLS-protected rows it needs"
        )


def test_the_retention_sweep_runs_off_request(worker_connection):
    """Companion beat task; reads report/enrollment, writes audit rows."""
    _ready_report()
    worker_connection()

    run_retention_sweep.apply().get()


def test_system_rls_context_denies_again_on_exit(worker_connection):
    """The context manager is not a one-way door -- it restores default-deny."""
    from apps.common.rls import system_rls_context

    _ready_report()
    worker_connection()

    with system_rls_context():
        assert Report.objects.count() > 0

    assert Report.objects.count() == 0, "context manager leaked staff visibility"
