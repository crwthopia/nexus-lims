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

import pytest
from django.core import mail
from django.db import transaction
from django.utils import timezone

from apps.audit.failures import record_failure
from apps.audit.models import SystemFailure
from apps.notifications.messages import BODY_BUILDERS, NotificationEntityGone, build_body
from apps.notifications.models import NotificationRecord
from apps.notifications.notify import notify, notify_each, staff_emails_for_roles
from apps.notifications.tasks import (
    retry_stalled_notifications,
    send_notification,
    send_open_failure_digest,
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


def test_a_failed_send_is_recorded_on_the_row_and_re_raised(monkeypatch):
    """Recorded so the row says why; re-raised so it becomes a SystemFailure."""
    customer = CustomerUserFactory()
    record = notify(
        Kind.CUSTOMER_DUPLICATE_REGISTRATION, customer.email, "subject", dedupe_key="k4", entity=customer,
    )
    monkeypatch.setattr(
        "apps.notifications.tasks.send_mail",
        lambda **kwargs: (_ for _ in ()).throw(OSError("connection refused")),
    )

    with pytest.raises(OSError):
        send_notification(record.pk)

    record.refresh_from_db()
    assert record.status == Status.FAILED
    assert "connection refused" in record.failure_reason


def test_a_notification_about_a_deleted_record_is_dropped_not_retried_forever():
    customer = CustomerUserFactory()
    record = notify(
        Kind.CUSTOMER_EMAIL_VERIFICATION, customer.email, "subject", dedupe_key="k5", entity=customer,
    )
    customer.delete()

    assert send_notification(record.pk) == "entity-gone"

    record.refresh_from_db()
    assert record.status == Status.FAILED
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
