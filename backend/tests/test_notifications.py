"""
Email notifications: queueing, delivery, deduplication, and the two rules
that stop this becoming a nuisance or a leak.

The design claims being tested, in order of how much damage each would do
if it were wrong:

  no leaks       a customer's report is a link, never the document, and an
                 out-of-spec *value* never appears in a staff mailbox
                 (ISO/IEC 17025:2017 4.2). Email is not a channel the lab
                 controls once it has sent.
  no floods      a nightly sweep must not chase the same instrument every
                 night, and a dependency failing every few seconds must not
                 be an email every few seconds.
  no loops       an email failure is recorded as a system failure, and a
                 system failure normally sends an email. That must not
                 recurse.
  nothing lost   queued in the caller's transaction, sent only after it
                 commits -- so a rolled-back reschedule sends nothing, and
                 a committed one always sends.
"""

import smtplib

import pytest
from django.core import mail
from django.db import transaction
from django.utils import timezone

from apps.audit.failures import record_failure
from apps.audit.models import SystemFailure
from apps.notifications.messages import BODY_BUILDERS, NotificationEntityGone, build_body
from apps.notifications.models import NotificationRecord
from apps.notifications.notify import notify, notify_each, staff_emails_for_roles
from apps.samples.models import Sample
from apps.notifications.tasks import (
    is_transient,
    notify_sample_progress,
    retry_failed_notifications,
    retry_stalled_notifications,
    send_notification,
    send_open_failure_digest,
    send_sample_progress_digests,
    sweep_calibration_due,
)
from tests.factories import (
    CustomerUserFactory,
    InstrumentFactory,
    OrderFactory,
    SampleFactory,
    StaffUserFactory,
    TestResultFactory,
)
from tests.helpers import deliver_queued_notifications

pytestmark = pytest.mark.django_db

Kind = NotificationRecord.Kind
Status = NotificationRecord.Status


def _record_status_change(sample, status, when=None):
    """
    The audit row a real status change writes (apps/audit/signals.py).

    The digest reads the ledger rather than the samples, because a sample
    sitting in `received` cannot say whether it arrived today or last week.
    These tests force status with a queryset update -- which sends no signals
    by design -- so the ledger row has to be written explicitly here.

    Raw INSERT rather than the ORM because `timestamp` is auto_now_add, and
    a test that needs a row dated three days ago cannot set it any other way:
    migration 0004 revoked UPDATE on this table, so ageing it afterwards is
    refused. That refusal is the append-only ledger doing its job -- INSERT
    is the only door, for tests as much as for the application.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO audit_log_entry
                (actor_type, entity_type, entity_id, field_changed, old_value, new_value, reason, "timestamp")
            VALUES ('system', 'Sample', %s, 'status', NULL, %s, '', %s)
            """,
            [sample.pk, status, when or timezone.now()],
        )


# --- Queueing and delivery -------------------------------------------------

def test_a_notification_is_a_row_before_it_is_an_email():
    record = notify(Kind.SYSTEM_FAILURE, "qa@nasatlabs.test", "subject", dedupe_key="k1")

    assert record.status == Status.PENDING
    assert record.sent_at is None
    # Nothing has gone over the network: the send waits for the commit that
    # a test never makes.
    assert mail.outbox == []


def test_delivering_marks_the_row_sent():
    customer = CustomerUserFactory()
    record = notify(
        Kind.CUSTOMER_DUPLICATE_REGISTRATION, customer.email, "subject", dedupe_key="k2", entity=customer,
    )

    send_notification(record.pk)

    record.refresh_from_db()
    assert record.status == Status.SENT
    assert record.sent_at is not None
    assert len(mail.outbox) == 1


def test_redelivery_does_not_send_a_second_email():
    """Celery is at-least-once: a task that succeeded and lost its ack runs again."""
    customer = CustomerUserFactory()
    record = notify(
        Kind.CUSTOMER_DUPLICATE_REGISTRATION, customer.email, "subject", dedupe_key="k3", entity=customer,
    )

    send_notification(record.pk)
    assert send_notification(record.pk) == "already-sent"

    assert len(mail.outbox) == 1


def test_a_transient_failure_is_recorded_and_left_for_the_retry_sweep(monkeypatch):
    """
    Not re-raised, deliberately. Re-raising makes it a Celery task failure
    and therefore a SystemFailure, and alarming QA about a thirty-second SMTP
    hiccup the next sweep will fix is how a register of real problems turns
    into noise people filter.
    """
    customer = CustomerUserFactory()
    record = notify(
        Kind.CUSTOMER_DUPLICATE_REGISTRATION, customer.email, "subject", dedupe_key="k4", entity=customer,
    )
    monkeypatch.setattr(
        "apps.notifications.tasks.send_mail",
        lambda **kwargs: (_ for _ in ()).throw(OSError("connection refused")),
    )

    assert send_notification(record.pk) == "retry-scheduled"

    record.refresh_from_db()
    assert record.status == Status.FAILED
    assert record.attempts == 1
    assert record.last_attempt_at is not None
    assert "connection refused" in record.failure_reason
    assert not SystemFailure.objects.filter(component=SystemFailure.Component.EMAIL).exists()


def test_a_notification_about_a_deleted_record_is_dropped_not_retried_forever():
    customer = CustomerUserFactory()
    record = notify(
        Kind.CUSTOMER_EMAIL_VERIFICATION, customer.email, "subject", dedupe_key="k5", entity=customer,
    )
    customer.delete()

    assert send_notification(record.pk) == "entity-gone"

    record.refresh_from_db()
    # ABANDONED, not FAILED: FAILED now means "will be retried", and retrying
    # against a row that no longer exists is what this branch prevents.
    assert record.status == Status.ABANDONED
    assert mail.outbox == []


# --- Deduplication ---------------------------------------------------------

def test_the_same_dedupe_key_queues_once():
    first = notify(Kind.CALIBRATION_DUE, "a@nasatlabs.test", "s", dedupe_key="same")
    second = notify(Kind.CALIBRATION_DUE, "a@nasatlabs.test", "s", dedupe_key="same")

    assert first is not None
    assert second is None
    assert NotificationRecord.objects.filter(dedupe_key="same").count() == 1


def test_a_duplicate_does_not_poison_the_callers_transaction():
    """
    In Postgres a failed statement aborts the whole transaction unless it is
    contained. If the IntegrityError were not caught inside its own atomic
    block, a sweep hitting one already-sent notification would take every
    later write in the same transaction down with it.
    """
    notify(Kind.CALIBRATION_DUE, "a@nasatlabs.test", "s", dedupe_key="dup")

    with transaction.atomic():
        assert notify(Kind.CALIBRATION_DUE, "a@nasatlabs.test", "s", dedupe_key="dup") is None
        # The transaction is still usable, which is the whole point.
        StaffUserFactory()


def test_each_recipient_gets_their_own_row():
    records = notify_each(
        Kind.SYSTEM_FAILURE, ["a@nasatlabs.test", "b@nasatlabs.test"], "s", dedupe_key="multi",
    )

    assert len(records) == 2
    assert {r.recipient for r in records} == {"a@nasatlabs.test", "b@nasatlabs.test"}


# --- Recipients ------------------------------------------------------------

def test_recipients_resolve_from_roles_not_a_configured_list():
    qa = StaffUserFactory(roles=["qa_officer"])
    StaffUserFactory(roles=["analyst"])

    assert staff_emails_for_roles("qa_officer") == [qa.email]


def test_an_inactive_staff_member_is_not_mailed():
    leaver = StaffUserFactory(roles=["qa_officer"])
    leaver.is_active = False
    leaver.save(update_fields=["is_active"])

    assert staff_emails_for_roles("qa_officer") == []


# --- Confidentiality (ISO/IEC 17025:2017 4.2) ------------------------------

def test_a_customer_is_sent_a_link_not_their_report():
    customer = CustomerUserFactory()
    order = OrderFactory(customer=customer)
    sample = SampleFactory(order=order)
    from apps.reporting.models import Report

    report = Report.objects.create(
        sample=sample, report_type=Report.ReportType.WATER_ENVIRONMENTAL_COA, status=Report.Status.READY,
        file_id="reports/water_environmental_coa/1-v1.pdf",
        generated_by=StaffUserFactory(roles=["approver"]),
    )
    record = notify(Kind.REPORT_READY, customer.email, "ready", dedupe_key="rr", entity=report)

    send_notification(record.pk)

    body = mail.outbox[0].body
    assert "not attached" in body
    # The OSS object key is an internal locator and a presigned-URL input.
    assert report.file_id not in body


def test_an_out_of_spec_value_does_not_travel_by_email():
    """
    The alert says which result to look at, never what it measured. A value
    in a mailbox is an uncontrolled copy of a regulated measurement.
    """
    result = TestResultFactory(value="41.7", is_out_of_spec=True)

    record = notify(Kind.RESULT_OUT_OF_SPEC, "qa@nasatlabs.test", "oos", dedupe_key="oos1", entity=result)
    send_notification(record.pk)

    assert str(result.value) not in mail.outbox[0].body


def test_the_body_is_not_stored_on_the_row():
    customer = CustomerUserFactory()
    record = notify(
        Kind.CUSTOMER_DUPLICATE_REGISTRATION, customer.email, "subject", dedupe_key="nobody", entity=customer,
    )
    send_notification(record.pk)

    record.refresh_from_db()
    stored = {f.name for f in NotificationRecord._meta.get_fields() if hasattr(f, "attname")}
    assert "body" not in stored
    assert record.subject == "subject"


# --- Every kind can actually be rendered -----------------------------------

def test_every_kind_has_a_message_builder():
    """A kind added to the enum with no builder is a silently empty email."""
    missing = set(Kind.values) - {k.value if hasattr(k, "value") else k for k in BODY_BUILDERS}

    assert missing == set(), f"NotificationRecord.Kind members with no body builder: {sorted(missing)}"


# --- System failure alerts -------------------------------------------------

def test_a_failed_system_failure_alerts_qa():
    qa = StaffUserFactory(roles=["qa_officer"])

    record_failure(
        SystemFailure.Component.REPORT_GENERATION,
        "generate_report_pdf raised ValueError",
        severity=SystemFailure.Severity.FAILED,
    )

    queued = NotificationRecord.objects.filter(kind=Kind.SYSTEM_FAILURE)
    assert queued.count() == 1
    assert queued.first().recipient == qa.email


def test_a_degraded_failure_waits_for_the_digest_rather_than_paging_anyone():
    StaffUserFactory(roles=["qa_officer"])

    record_failure(
        SystemFailure.Component.OBJECT_STORAGE,
        "retention archival skipped: object storage is not configured",
        severity=SystemFailure.Severity.DEGRADED,
    )

    assert not NotificationRecord.objects.filter(kind=Kind.SYSTEM_FAILURE).exists()


def test_a_recurring_failure_emails_once_not_once_per_occurrence():
    """
    The reason the register deduplicates at all. A dependency probed every
    few seconds would otherwise be an email every few seconds, all night.
    """
    StaffUserFactory(roles=["qa_officer"])

    for _ in range(5):
        record_failure(
            SystemFailure.Component.DATABASE,
            "readiness check 'database' failed with OperationalError",
            severity=SystemFailure.Severity.FAILED,
        )

    assert NotificationRecord.objects.filter(kind=Kind.SYSTEM_FAILURE).count() == 1
    assert SystemFailure.objects.get(component=SystemFailure.Component.DATABASE).occurrences == 5


def test_an_email_failure_does_not_try_to_send_an_email_about_it():
    """
    The loop that has to not exist: email fails -> SystemFailure -> alert by
    email -> fails. Deduplication would stop it after a hop or two, but a
    loop that terminates by accident is not a design.
    """
    StaffUserFactory(roles=["qa_officer"])

    record_failure(
        SystemFailure.Component.EMAIL,
        "send_notification raised SMTPException",
        severity=SystemFailure.Severity.FAILED,
    )

    assert not NotificationRecord.objects.filter(kind=Kind.SYSTEM_FAILURE).exists()
    # The failure itself is still recorded -- it is the *notification* that
    # is suppressed, not the evidence.
    assert SystemFailure.objects.filter(component=SystemFailure.Component.EMAIL).exists()


def test_a_failure_with_nobody_to_tell_is_still_recorded():
    record_failure(
        SystemFailure.Component.REPORT_GENERATION, "boom", severity=SystemFailure.Severity.FAILED,
    )

    assert SystemFailure.objects.count() == 1
    assert not NotificationRecord.objects.exists()


# --- Sweeps ----------------------------------------------------------------

def test_the_calibration_sweep_chases_the_custodian():
    custodian = StaffUserFactory(roles=["instrument_custodian"])
    instrument = InstrumentFactory(
        custodian=custodian, calibration_due_date=timezone.localdate() + timezone.timedelta(days=3),
    )

    sweep_calibration_due()

    queued = NotificationRecord.objects.filter(kind=Kind.CALIBRATION_DUE)
    assert queued.count() == 1
    assert queued.first().recipient == custodian.email
    assert queued.first().entity_id == instrument.id


def test_the_calibration_sweep_does_not_chase_the_same_instrument_every_night():
    custodian = StaffUserFactory(roles=["instrument_custodian"])
    InstrumentFactory(
        custodian=custodian, calibration_due_date=timezone.localdate() + timezone.timedelta(days=3),
    )

    for _ in range(4):
        sweep_calibration_due()

    assert NotificationRecord.objects.filter(kind=Kind.CALIBRATION_DUE).count() == 1


def test_rescheduling_a_calibration_is_a_new_notification():
    """The key carries the due date, so the thing being chased has changed."""
    custodian = StaffUserFactory(roles=["instrument_custodian"])
    instrument = InstrumentFactory(
        custodian=custodian, calibration_due_date=timezone.localdate() + timezone.timedelta(days=3),
    )
    sweep_calibration_due()

    instrument.calibration_due_date = timezone.localdate() + timezone.timedelta(days=10)
    instrument.save(update_fields=["calibration_due_date"])
    sweep_calibration_due()

    assert NotificationRecord.objects.filter(kind=Kind.CALIBRATION_DUE).count() == 2


def test_an_instrument_not_yet_due_is_left_alone():
    StaffUserFactory(roles=["instrument_custodian"])
    InstrumentFactory(calibration_due_date=timezone.localdate() + timezone.timedelta(days=365))

    sweep_calibration_due()

    assert not NotificationRecord.objects.filter(kind=Kind.CALIBRATION_DUE).exists()


def test_a_retired_instrument_is_left_alone():
    from apps.equipment.models import Instrument

    StaffUserFactory(roles=["instrument_custodian"])
    InstrumentFactory(
        status=Instrument.Status.RETIRED,
        calibration_due_date=timezone.localdate() - timezone.timedelta(days=30),
    )

    sweep_calibration_due()

    assert not NotificationRecord.objects.filter(kind=Kind.CALIBRATION_DUE).exists()


def test_an_instrument_with_no_custodian_falls_back_to_the_role():
    """An uncalibrated instrument nobody owns needs the message more, not less."""
    holder = StaffUserFactory(roles=["instrument_custodian"])
    InstrumentFactory(custodian=None, calibration_due_date=timezone.localdate())

    sweep_calibration_due()

    assert NotificationRecord.objects.get(kind=Kind.CALIBRATION_DUE).recipient == holder.email


def test_the_digest_is_not_sent_when_nothing_is_open():
    """A daily 'nothing to report' trains people to delete it unread."""
    StaffUserFactory(roles=["qa_officer"])

    send_open_failure_digest()

    assert not NotificationRecord.objects.filter(kind=Kind.OPEN_FAILURE_DIGEST).exists()


def test_the_digest_lists_what_is_still_open():
    qa = StaffUserFactory(roles=["qa_officer"])
    record_failure(
        SystemFailure.Component.OBJECT_STORAGE, "OSS unreachable", severity=SystemFailure.Severity.DEGRADED,
    )

    send_open_failure_digest()
    deliver_queued_notifications()

    digest = next(m for m in mail.outbox if "still open" in m.subject)
    assert digest.to == [qa.email]
    assert "OSS unreachable" in digest.body


def test_the_digest_goes_out_once_a_day_however_often_the_task_runs():
    StaffUserFactory(roles=["qa_officer"])
    record_failure(
        SystemFailure.Component.OBJECT_STORAGE, "OSS unreachable", severity=SystemFailure.Severity.DEGRADED,
    )

    send_open_failure_digest()
    send_open_failure_digest()

    assert NotificationRecord.objects.filter(kind=Kind.OPEN_FAILURE_DIGEST).count() == 1


def test_a_closed_failure_drops_out_of_the_digest():
    StaffUserFactory(roles=["qa_officer"])
    failure = record_failure(
        SystemFailure.Component.OBJECT_STORAGE, "OSS unreachable", severity=SystemFailure.Severity.DEGRADED,
    )
    failure.status = SystemFailure.Status.CLOSED
    failure.corrective_action = "Endpoint corrected."
    failure.save(update_fields=["status", "corrective_action"])

    send_open_failure_digest()

    assert not NotificationRecord.objects.filter(kind=Kind.OPEN_FAILURE_DIGEST).exists()


# --- Surviving a broker outage ---------------------------------------------

def test_a_broker_outage_does_not_fail_the_request_that_queued_the_notification(monkeypatch):
    """
    Moving the send out of the request removed SMTP from the request path.
    It must not have put the broker there instead: an unguarded .delay()
    runs inline via on_commit, so Redis being down would 500 a registration
    for the same reason the old inline send_mail did.
    """
    monkeypatch.setattr(
        "apps.notifications.tasks.send_notification.delay",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("Error 111 connecting to redis:6379")),
    )

    record = notify(Kind.CALIBRATION_DUE, "custodian@nasatlabs.test", "s", dedupe_key="broker-down")

    assert record is not None
    record.refresh_from_db()
    assert record.status == Status.PENDING


def test_a_stalled_notification_is_re_enqueued_once_the_broker_returns(monkeypatch):
    record = notify(Kind.CALIBRATION_DUE, "custodian@nasatlabs.test", "s", dedupe_key="stalled")
    NotificationRecord.objects.filter(pk=record.pk).update(
        created_at=timezone.now() - timezone.timedelta(hours=2)
    )

    enqueued = []
    monkeypatch.setattr(
        "apps.notifications.tasks.send_notification.delay", lambda pk: enqueued.append(pk),
    )

    assert retry_stalled_notifications() == {"requeued": 1}
    assert enqueued == [record.pk]


def test_a_notification_still_within_the_stall_window_is_left_alone():
    """An ordinary queue backlog is not a stall."""
    notify(Kind.CALIBRATION_DUE, "custodian@nasatlabs.test", "s", dedupe_key="fresh")

    assert retry_stalled_notifications() == {"requeued": 0}


def test_an_already_sent_notification_is_not_re_enqueued():
    customer = CustomerUserFactory()
    record = notify(
        Kind.CUSTOMER_DUPLICATE_REGISTRATION, customer.email, "s", dedupe_key="done", entity=customer,
    )
    send_notification(record.pk)
    NotificationRecord.objects.filter(pk=record.pk).update(
        created_at=timezone.now() - timezone.timedelta(hours=2)
    )

    assert retry_stalled_notifications() == {"requeued": 0}


def test_the_retry_stops_rather_than_hammering_a_broker_that_is_still_down(monkeypatch):
    for i in range(3):
        notify(Kind.CALIBRATION_DUE, f"c{i}@nasatlabs.test", "s", dedupe_key=f"down-{i}")
    NotificationRecord.objects.all().update(created_at=timezone.now() - timezone.timedelta(hours=2))

    attempts = []

    def _still_down(pk):
        attempts.append(pk)
        raise OSError("connection refused")

    monkeypatch.setattr("apps.notifications.tasks.send_notification.delay", _still_down)

    assert retry_stalled_notifications() == {"requeued": 0}
    assert len(attempts) == 1


# --- Sample progress -------------------------------------------------------

_NO_ORDER = object()


def _sample_at(status, order=_NO_ORDER, **kwargs):
    """
    A Sample forced to `status`, bypassing the FSM's protected field.

    The sentinel matters: `order=None` is a walk-in sample with deliberately
    no Order, which is different from "caller did not say" -- an `or` here
    would quietly give the walk-in test an order and assert nothing.
    """
    sample = SampleFactory(order=OrderFactory() if order is _NO_ORDER else order, **kwargs)
    Sample.objects.filter(pk=sample.pk).update(status=status)
    return Sample.objects.get(pk=sample.pk)


def test_a_customer_hears_when_their_sample_arrives():
    sample = _sample_at(Sample.Status.RECEIVED)

    notify_sample_progress(sample)

    record = NotificationRecord.objects.get(kind=Kind.SAMPLE_PROGRESS)
    assert record.recipient == sample.order.customer.email
    assert record.context == {"status": "received"}
    assert "arrived" in record.subject


def test_an_internal_step_is_not_a_customer_milestone():
    """Eleven lab states are not eleven customer emails."""
    for status in (Sample.Status.PRE_REGISTERED, Sample.Status.REGISTERED,
                   Sample.Status.IN_PREP, Sample.Status.UNDER_REVIEW):
        notify_sample_progress(_sample_at(status))

    assert not NotificationRecord.objects.filter(kind=Kind.SAMPLE_PROGRESS).exists()


@pytest.mark.parametrize("status", ["under_investigation", "rejected", "retest_pending"])
def test_nonconforming_work_is_never_auto_notified(status, settings):
    """
    7.10 asks the laboratory to evaluate nonconforming work and decide
    whether the customer needs telling. An automatic "your sample failed"
    pre-empts that judgement -- so widening the configured list must not be
    able to switch it on.
    """
    settings.CUSTOMER_NOTIFIED_SAMPLE_STATUSES = [status]

    notify_sample_progress(_sample_at(status))

    assert not NotificationRecord.objects.filter(kind=Kind.SAMPLE_PROGRESS).exists()


def test_the_milestone_is_pinned_at_queue_time_not_read_at_send_time():
    """
    A sample can move twice before a worker picks the row up. Without the
    stored milestone the body would describe wherever it ended up, under a
    subject line about where it was.
    """
    sample = _sample_at(Sample.Status.RECEIVED)
    notify_sample_progress(sample)
    record = NotificationRecord.objects.get(kind=Kind.SAMPLE_PROGRESS)

    Sample.objects.filter(pk=sample.pk).update(status=Sample.Status.IN_PREP)
    send_notification(record.pk)

    assert "arrived at the laboratory" in mail.outbox[-1].body
    assert "in prep" not in mail.outbox[-1].body.lower()


def test_a_retest_does_not_re_announce_that_testing_started():
    sample = _sample_at(Sample.Status.IN_TESTING)

    notify_sample_progress(sample)
    notify_sample_progress(sample)

    assert NotificationRecord.objects.filter(kind=Kind.SAMPLE_PROGRESS).count() == 1


def test_a_walk_in_sample_has_no_customer_to_tell():
    """The Order FK is nullable for over-the-counter work; that is not a failure."""
    sample = _sample_at(Sample.Status.RECEIVED, order=None)

    assert notify_sample_progress(sample) == []
    assert not NotificationRecord.objects.exists()


def test_no_result_travels_with_a_progress_update():
    sample = _sample_at(Sample.Status.APPROVED)
    notify_sample_progress(sample)

    send_notification(NotificationRecord.objects.get(kind=Kind.SAMPLE_PROGRESS).pk)

    body = mail.outbox[-1].body
    assert "never sent by email" in body
    assert sample.unique_sample_code in body


# --- Sample progress: the digest for big orders ----------------------------

def test_a_big_order_is_not_mailed_per_sample(settings):
    """A 30-sample order at three milestones is 90 emails otherwise."""
    settings.SAMPLE_PROGRESS_DIGEST_THRESHOLD = 2
    order = OrderFactory()
    samples = [_sample_at(Sample.Status.RECEIVED, order=order) for _ in range(4)]

    for sample in samples:
        notify_sample_progress(sample)

    assert not NotificationRecord.objects.filter(kind=Kind.SAMPLE_PROGRESS).exists()


def test_a_small_order_is_still_mailed_as_it_happens(settings):
    settings.SAMPLE_PROGRESS_DIGEST_THRESHOLD = 5
    order = OrderFactory()
    sample = _sample_at(Sample.Status.RECEIVED, order=order)

    notify_sample_progress(sample)

    assert NotificationRecord.objects.filter(kind=Kind.SAMPLE_PROGRESS).count() == 1


def test_the_digest_reports_what_moved_today(settings):
    settings.SAMPLE_PROGRESS_DIGEST_THRESHOLD = 2
    order = OrderFactory()
    samples = [_sample_at(Sample.Status.RECEIVED, order=order) for _ in range(4)]
    for sample in samples[:3]:
        _record_status_change(sample, "received")

    send_sample_progress_digests()
    deliver_queued_notifications()

    digest = next(m for m in mail.outbox if "order #" in m.subject)
    assert digest.to == [order.customer.email]
    assert "3 of the 4 samples" in digest.body


def test_the_digest_goes_out_once_per_order_per_milestone_per_day(settings):
    settings.SAMPLE_PROGRESS_DIGEST_THRESHOLD = 2
    order = OrderFactory()
    for _ in range(4):
        _record_status_change(_sample_at(Sample.Status.RECEIVED, order=order), "received")

    send_sample_progress_digests()
    send_sample_progress_digests()

    assert NotificationRecord.objects.filter(kind=Kind.SAMPLE_PROGRESS_DIGEST).count() == 1


def test_the_digest_ignores_a_small_order_that_was_already_mailed(settings):
    settings.SAMPLE_PROGRESS_DIGEST_THRESHOLD = 10
    order = OrderFactory()
    _record_status_change(_sample_at(Sample.Status.RECEIVED, order=order), "received")

    send_sample_progress_digests()

    assert not NotificationRecord.objects.filter(kind=Kind.SAMPLE_PROGRESS_DIGEST).exists()


def test_the_digest_does_not_report_nonconforming_work(settings):
    settings.SAMPLE_PROGRESS_DIGEST_THRESHOLD = 2
    settings.CUSTOMER_NOTIFIED_SAMPLE_STATUSES = ["received", "under_investigation"]
    order = OrderFactory()
    for _ in range(4):
        _record_status_change(_sample_at(Sample.Status.UNDER_INVESTIGATION, order=order), "under_investigation")

    send_sample_progress_digests()

    assert not NotificationRecord.objects.filter(kind=Kind.SAMPLE_PROGRESS_DIGEST).exists()


def test_yesterdays_movement_is_not_in_todays_digest(settings):
    settings.SAMPLE_PROGRESS_DIGEST_THRESHOLD = 2
    order = OrderFactory()
    three_days_ago = timezone.now() - timezone.timedelta(days=3)
    for _ in range(4):
        _record_status_change(_sample_at(Sample.Status.RECEIVED, order=order), "received", when=three_days_ago)

    send_sample_progress_digests()

    assert not NotificationRecord.objects.filter(kind=Kind.SAMPLE_PROGRESS_DIGEST).exists()


# --- Retrying a failed send ------------------------------------------------

def _failing_send(monkeypatch, exc):
    monkeypatch.setattr(
        "apps.notifications.tasks.send_mail", lambda **kwargs: (_ for _ in ()).throw(exc)
    )


def _queued(dedupe_key="retry"):
    customer = CustomerUserFactory()
    return notify(
        Kind.CUSTOMER_DUPLICATE_REGISTRATION, customer.email, "s", dedupe_key=dedupe_key, entity=customer,
    )


@pytest.mark.parametrize(
    "exc",
    [
        smtplib.SMTPServerDisconnected("connection lost"),
        smtplib.SMTPConnectError(421, "service unavailable"),
        OSError("Connection refused"),
        TimeoutError("timed out"),
        smtplib.SMTPResponseException(451, "mailbox busy, try again"),
        smtplib.SMTPRecipientsRefused({"a@b.test": (450, b"greylisted")}),
    ],
)
def test_these_failures_are_worth_another_attempt(exc):
    """4xx is 'try later', and a connection that never formed says nothing at all."""
    assert is_transient(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        smtplib.SMTPAuthenticationError(535, "bad credentials"),
        smtplib.SMTPResponseException(550, "sender domain not verified"),
        smtplib.SMTPSenderRefused(553, "not authorised", "no-reply@x.test"),
        smtplib.SMTPRecipientsRefused({"typo@nowhere.test": (550, b"no such user")}),
        ValueError("a bug in the message builder"),
    ],
)
def test_these_failures_would_fail_identically_forever(exc):
    """
    Retrying an authentication failure against a provider that rate-limits
    bad logins makes things actively worse, and a mistyped recipient is not
    going to start existing.
    """
    assert is_transient(exc) is False


def test_a_permanent_failure_is_abandoned_on_the_first_attempt(monkeypatch):
    record = _queued("permanent")
    _failing_send(monkeypatch, smtplib.SMTPAuthenticationError(535, "bad credentials"))

    with pytest.raises(smtplib.SMTPAuthenticationError):
        send_notification(record.pk)

    record.refresh_from_db()
    assert record.status == Status.ABANDONED
    assert record.attempts == 1


def test_giving_up_is_what_raises_and_so_what_alarms(monkeypatch, settings):
    """
    The failure register should hear about a message the lab has stopped
    trying to deliver, and not about every hiccup on the way there.
    """
    settings.NOTIFICATION_MAX_ATTEMPTS = 2
    record = _queued("exhausted")
    _failing_send(monkeypatch, OSError("Connection refused"))

    assert send_notification(record.pk) == "retry-scheduled"
    with pytest.raises(OSError):
        send_notification(record.pk)

    record.refresh_from_db()
    assert record.status == Status.ABANDONED
    assert record.attempts == 2


def test_a_retry_that_succeeds_leaves_no_trace_of_the_failure(monkeypatch):
    record = _queued("recovers")
    _failing_send(monkeypatch, OSError("Connection refused"))
    send_notification(record.pk)
    monkeypatch.undo()

    assert send_notification(record.pk) == "sent"

    record.refresh_from_db()
    assert record.status == Status.SENT
    assert record.failure_reason == ""
    assert record.attempts == 2
    assert len(mail.outbox) == 1


def test_the_backoff_lengthens_and_then_stops_lengthening():
    from apps.notifications.tasks import _backoff_seconds

    assert _backoff_seconds(1) == 60
    assert _backoff_seconds(2) == 120
    assert _backoff_seconds(3) == 240
    # Capped, so the last attempts are not days apart -- by which point the
    # message has stopped being worth sending.
    assert _backoff_seconds(20) == 3600


# --- The sweep -------------------------------------------------------------

def _aged(record, seconds):
    NotificationRecord.objects.filter(pk=record.pk).update(
        last_attempt_at=timezone.now() - timezone.timedelta(seconds=seconds)
    )


def test_the_sweep_re_enqueues_a_failed_row_once_its_backoff_has_passed(monkeypatch):
    record = _queued("sweep-due")
    _failing_send(monkeypatch, OSError("Connection refused"))
    send_notification(record.pk)
    _aged(record, 300)

    enqueued = []
    monkeypatch.setattr("apps.notifications.tasks.send_notification.delay", lambda pk: enqueued.append(pk))

    assert retry_failed_notifications() == {"requeued": 1, "waiting": 0}
    assert enqueued == [record.pk]


def test_a_row_still_inside_its_backoff_is_left_alone(monkeypatch):
    record = _queued("sweep-waiting")
    _failing_send(monkeypatch, OSError("Connection refused"))
    send_notification(record.pk)

    monkeypatch.setattr("apps.notifications.tasks.send_notification.delay", lambda pk: None)

    assert retry_failed_notifications() == {"requeued": 0, "waiting": 1}


def test_the_sweep_does_not_touch_an_abandoned_row(monkeypatch):
    record = _queued("sweep-abandoned")
    _failing_send(monkeypatch, smtplib.SMTPAuthenticationError(535, "bad credentials"))
    with pytest.raises(smtplib.SMTPAuthenticationError):
        send_notification(record.pk)
    _aged(record, 100000)

    enqueued = []
    monkeypatch.setattr("apps.notifications.tasks.send_notification.delay", lambda pk: enqueued.append(pk))

    assert retry_failed_notifications() == {"requeued": 0, "waiting": 0}
    assert enqueued == []


def test_the_sweep_does_not_touch_a_sent_row(monkeypatch):
    record = _queued("sweep-sent")
    send_notification(record.pk)
    _aged(record, 100000)

    monkeypatch.setattr("apps.notifications.tasks.send_notification.delay", lambda pk: None)

    assert retry_failed_notifications()["requeued"] == 0


def test_the_sweep_stops_rather_than_hammering_a_broker_that_is_down(monkeypatch):
    for i in range(3):
        record = _queued(f"sweep-down-{i}")
        _failing_send(monkeypatch, OSError("Connection refused"))
        send_notification(record.pk)
        _aged(record, 100000)
    monkeypatch.undo()

    attempts = []

    def _still_down(pk):
        attempts.append(pk)
        raise OSError("connection refused")

    monkeypatch.setattr("apps.notifications.tasks.send_notification.delay", _still_down)

    assert retry_failed_notifications()["requeued"] == 0
    assert len(attempts) == 1
