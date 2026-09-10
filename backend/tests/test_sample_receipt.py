"""
Sample identity and the arrival record (FR-C1-01, FR-C1-09, FR-C1-13).

Two clauses of ISO/IEC 17025:2017 are on trial here.

7.4.2 wants identification that is unambiguous and *retained for the life
of the item in the laboratory*. That is tested from both ends: a client
cannot choose a code, and nothing -- not a PATCH, not raw SQL -- can change
one after it has been allocated and, in the real world, printed on a bottle.

7.4.3 wants deviations on receipt recorded, the customer consulted before
proceeding where there is doubt, the outcome of that consultation written
down, and a disclaimer on the report when the customer says test it anyway.
Each of those is a separate test below, and the one that matters most is
the gate: a nonconforming item that nobody has consulted the customer about
must not reach an analyst.

Driven through the real API rather than by calling services directly, for
the reason tests/test_sample_fsm.py gives: the role gates and the
transition-to-400 translation live at the view layer, and a test that skips
them proves the wrong thing.
"""

import datetime

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.samples.identity import UnknownServiceLine, allocate_sample_code
from apps.samples.models import ChainOfCustodyEvent, Sample, SampleReceipt, ServiceLine
from tests.factories import OrderFactory, SampleFactory, StaffUserFactory
from tests.helpers import reload

pytestmark = pytest.mark.django_db


def _receive(client, sample, **body):
    return client.post(f"/api/v1/samples/{sample.id}/receive/", body, format="json")


def _leaking(**overrides):
    """The ordinary nonconforming arrival: a bottle that leaked in transit."""
    return {"condition_on_receipt": "leaking", "seal_intact": False, **overrides}


# --- FR-C1-01 sample identity (ISO/IEC 17025:2017 7.4.2) ---------------------


def test_the_code_is_allocated_server_side_and_a_client_supplied_one_is_ignored(login_as_staff):
    receiver = StaffUserFactory(roles=["sample_receiver"])
    order = OrderFactory(service_line=ServiceLine.WATER_ENVIRONMENTAL)
    client = login_as_staff(receiver)

    response = client.post(
        "/api/v1/samples/",
        {
            "order": order.id,
            "service_line": ServiceLine.WATER_ENVIRONMENTAL,
            "unique_sample_code": "ATTACKER-CHOSEN-0001",
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["unique_sample_code"] != "ATTACKER-CHOSEN-0001"
    assert response.data["unique_sample_code"].startswith("WE-")


def test_codes_increment_within_a_service_line_and_month():
    first = allocate_sample_code(ServiceLine.WATER_ENVIRONMENTAL, on_date=datetime.date(2026, 9, 10))
    second = allocate_sample_code(ServiceLine.WATER_ENVIRONMENTAL, on_date=datetime.date(2026, 9, 11))

    assert first == "WE-202609-0001"
    assert second == "WE-202609-0002"


def test_each_service_line_and_month_counts_separately():
    water = allocate_sample_code(ServiceLine.WATER_ENVIRONMENTAL, on_date=datetime.date(2026, 9, 10))
    failure = allocate_sample_code(ServiceLine.FAILURE_ANALYSIS, on_date=datetime.date(2026, 9, 10))
    next_month = allocate_sample_code(ServiceLine.WATER_ENVIRONMENTAL, on_date=datetime.date(2026, 10, 1))

    assert water == "WE-202609-0001"
    assert failure == "FA-202609-0001"
    assert next_month == "WE-202610-0001"


def test_a_service_line_with_no_prefix_refuses_rather_than_inventing_one():
    with pytest.raises(UnknownServiceLine):
        allocate_sample_code("geotechnical_testing")


def test_a_patch_cannot_change_an_allocated_code(login_as_staff):
    sample = SampleFactory(unique_sample_code="WE-202609-0007")
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = client.patch(
        f"/api/v1/samples/{sample.id}/", {"unique_sample_code": "WE-202609-9999"}, format="json"
    )

    assert response.status_code == 200
    assert reload(sample).unique_sample_code == "WE-202609-0007"


def test_the_database_refuses_a_code_change_even_from_raw_sql():
    """
    The serializer being read-only is the outer ring; migration 0009's
    trigger is the one that holds when the ORM is not involved at all.
    """
    sample = SampleFactory(unique_sample_code="WE-202609-0008")

    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE sample SET unique_sample_code = %s WHERE id = %s", ["WE-202609-9999", sample.id]
            )

    assert reload(sample).unique_sample_code == "WE-202609-0008"


def test_an_unrelated_update_still_works_with_the_trigger_in_place():
    """The trigger fires on every UPDATE, so prove it only objects to the one column."""
    sample = SampleFactory(client_reference="JOB-1")

    sample.client_reference = "JOB-2"
    sample.save(update_fields=["client_reference"])

    assert reload(sample).client_reference == "JOB-2"


# --- FR-C1-09 receipt time (ISO/IEC 17025:2017 7.8.2.1 l) -------------------


def test_receipt_can_be_backdated_to_when_the_courier_actually_arrived(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))
    arrived = timezone.now() - datetime.timedelta(hours=14)

    response = _receive(client, sample, received_at=arrived.isoformat())

    assert response.status_code == 200, response.data
    assert reload(sample).received_at == arrived
    assert sample.receipt.received_at == arrived


def test_the_write_time_is_kept_separately_from_the_event_time(login_as_staff):
    """ALCOA wants both: when custody moved, and when somebody wrote that down."""
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))
    arrived = timezone.now() - datetime.timedelta(hours=14)

    _receive(client, sample, received_at=arrived.isoformat())

    event = ChainOfCustodyEvent.objects.get(sample=sample)
    assert event.occurred_at == arrived
    assert event.timestamp > arrived


def test_a_receipt_in_the_future_is_refused(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))
    tomorrow = timezone.now() + datetime.timedelta(days=1)

    response = _receive(client, sample, received_at=tomorrow.isoformat())

    assert response.status_code == 400
    assert "future" in str(response.data).lower()
    assert reload(sample).status == Sample.Status.REGISTERED


def test_a_malformed_body_leaves_the_sample_where_it_was(login_as_staff):
    """The body is parsed before the transition runs, not after."""
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = _receive(client, sample, receipt_temperature_c="not-a-number")

    assert response.status_code == 400
    assert reload(sample).status == Sample.Status.REGISTERED
    assert not SampleReceipt.objects.filter(sample=sample).exists()


# --- FR-C1-09 the arrival record (ISO/IEC 17025:2017 7.4.3) -----------------


def test_a_bare_receive_records_a_conforming_receipt(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    receiver = StaffUserFactory(roles=["sample_receiver"])
    client = login_as_staff(receiver)

    response = _receive(client, sample)

    assert response.status_code == 200, response.data
    receipt = reload(sample).receipt
    assert receipt.is_conforming
    assert receipt.received_by_id == receiver.id
    assert receipt.deviation_reasons == []


def test_the_receive_response_carries_the_saved_receipt(login_as_staff):
    """
    The view builds an unsaved SampleReceipt first, purely to ask it which
    checks failed before running the transition. Assigning `sample=` to a
    OneToOne populates the reverse cache on the sample, so the response
    could plausibly serialize that throwaway -- id and all -- instead of
    the row that was actually written. It does not, because
    record_receipt's create() overwrites the cache with the saved
    instance; this pins that, since the failure mode is a 200 carrying a
    receipt with a null id.
    """
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = client.post(f"/api/v1/samples/{sample.id}/receive/", {}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["receipt"]["id"] == sample.receipt.id


def test_a_deviation_with_no_explanation_is_refused(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = _receive(client, sample, **_leaking())

    assert response.status_code == 400
    assert "deviations" in response.data
    assert reload(sample).status == Sample.Status.REGISTERED


def test_a_recorded_deviation_is_accepted_and_summarised(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = _receive(client, sample, **_leaking(deviations="Bottle leaked in transit; ~40 mL lost."))

    assert response.status_code == 200, response.data
    receipt = reload(sample).receipt
    assert not receipt.is_conforming
    assert "the seal was not intact" in receipt.deviation_reasons


def test_an_unmeasured_temperature_is_not_recorded_as_conforming(login_as_staff):
    """Null means no temperature requirement applied -- it is not an assertion that one was met."""
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    _receive(client, sample)

    receipt = reload(sample).receipt
    assert receipt.temperature_conforms is None
    assert receipt.is_conforming


def test_a_temperature_excursion_counts_as_a_deviation(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = _receive(
        client, sample,
        receipt_temperature_c="14.50",
        temperature_conforms=False,
        deviations="Cooler at 14.5 C on arrival; specified 0-6 C.",
    )

    assert response.status_code == 200, response.data
    receipt = reload(sample).receipt
    assert not receipt.is_conforming
    assert any("temperature range" in reason for reason in receipt.deviation_reasons)


# --- FR-C1-13 the "consult before proceeding" gate (7.4.3) ------------------


def test_a_nonconforming_item_cannot_start_prep_until_the_customer_is_consulted(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    receiver = StaffUserFactory(roles=["sample_receiver"])
    analyst = StaffUserFactory(roles=["analyst"])

    _receive(login_as_staff(receiver), sample, **_leaking(deviations="Bottle leaked in transit."))

    response = login_as_staff(analyst).post(f"/api/v1/samples/{sample.id}/start-prep/")

    assert response.status_code == 400
    assert "7.4.3" in str(response.data)
    assert reload(sample).status == Sample.Status.RECEIVED


def test_recording_the_consultation_opens_the_gate(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    receiver = StaffUserFactory(roles=["sample_receiver"])
    analyst = StaffUserFactory(roles=["analyst"])

    _receive(login_as_staff(receiver), sample, **_leaking(deviations="Bottle leaked in transit."))
    consultation = login_as_staff(receiver).post(
        f"/api/v1/samples/{sample.id}/receipt-consultation/",
        {
            "outcome": "Customer advised of the loss; instructed to proceed with pH and conductivity only.",
            "authorised_despite_deviation": True,
            "disclaimer_text": "Volume loss in transit may affect the reported total coliform count.",
        },
        format="json",
    )
    assert consultation.status_code == 200, consultation.data

    response = login_as_staff(analyst).post(f"/api/v1/samples/{sample.id}/start-prep/")

    assert response.status_code == 200, response.data
    assert reload(sample).status == Sample.Status.IN_PREP


def test_a_conforming_item_is_never_gated(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    _receive(login_as_staff(StaffUserFactory(roles=["sample_receiver"])), sample)

    response = login_as_staff(StaffUserFactory(roles=["analyst"])).post(
        f"/api/v1/samples/{sample.id}/start-prep/"
    )

    assert response.status_code == 200, response.data


def test_a_sample_received_before_the_receipt_record_existed_is_not_stranded(login_as_staff):
    """
    Samples already in flight when this shipped have no receipt row. The
    gate lets them through rather than halting live work to satisfy a
    record that could not have been made.
    """
    sample = SampleFactory(status=Sample.Status.RECEIVED)
    assert not SampleReceipt.objects.filter(sample=sample).exists()

    response = login_as_staff(StaffUserFactory(roles=["analyst"])).post(
        f"/api/v1/samples/{sample.id}/start-prep/"
    )

    assert response.status_code == 200, response.data


def test_authorising_testing_despite_a_deviation_requires_a_disclaimer(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    receiver = StaffUserFactory(roles=["sample_receiver"])
    client = login_as_staff(receiver)
    _receive(client, sample, **_leaking(deviations="Bottle leaked in transit."))

    response = client.post(
        f"/api/v1/samples/{sample.id}/receipt-consultation/",
        {"outcome": "Customer said proceed.", "authorised_despite_deviation": True},
        format="json",
    )

    assert response.status_code == 400
    assert "disclaimer_text" in response.data


def test_the_disclaimer_flag_follows_the_customers_instruction(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))
    _receive(client, sample, **_leaking(deviations="Bottle leaked in transit."))

    declined = client.post(
        f"/api/v1/samples/{sample.id}/receipt-consultation/",
        {"outcome": "Customer will resample rather than proceed.", "authorised_despite_deviation": False},
        format="json",
    )

    assert declined.status_code == 200, declined.data
    assert declined.data["report_disclaimer_required"] is False
    assert declined.data["consultation_recorded"] is True


def test_a_consultation_is_refused_on_an_item_that_arrived_intact(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))
    _receive(client, sample)

    response = client.post(
        f"/api/v1/samples/{sample.id}/receipt-consultation/",
        {"outcome": "Called them anyway."},
        format="json",
    )

    assert response.status_code == 400
    assert "conformed" in str(response.data)


def test_a_consultation_needs_an_outcome_not_just_a_phone_call(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))
    _receive(client, sample, **_leaking(deviations="Bottle leaked in transit."))

    response = client.post(
        f"/api/v1/samples/{sample.id}/receipt-consultation/", {"outcome": "   "}, format="json"
    )

    assert response.status_code == 400
    assert "outcome" in response.data


# --- FR-C1-09 refusing an item at the door (7.4.3) --------------------------


def test_an_item_can_be_refused_before_it_is_received(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = client.post(
        f"/api/v1/samples/{sample.id}/reject-at-receipt/",
        {"reason": "Container shattered in transit; nothing recoverable."},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert reload(sample).status == Sample.Status.RECEIPT_REJECTED
    # Refusing is itself a receipt observation: the lab did take delivery.
    assert "shattered" in sample.receipt.deviations


def test_an_item_can_be_refused_after_it_has_been_booked_in(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))
    _receive(client, sample, **_leaking(deviations="Bottle leaked in transit."))

    response = client.post(
        f"/api/v1/samples/{sample.id}/reject-at-receipt/",
        {"reason": "Customer confirmed they will resample."},
        format="json",
    )

    assert response.status_code == 200, response.data
    refused = reload(sample)
    receipt = refused.receipt
    assert refused.status == Sample.Status.RECEIPT_REJECTED
    # The counter observation survives alongside the decision to refuse.
    assert "leaked in transit" in receipt.deviations
    assert "resample" in receipt.deviations


def test_refusing_an_item_requires_a_reason(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    response = client.post(f"/api/v1/samples/{sample.id}/reject-at-receipt/", {}, format="json")

    assert response.status_code == 400
    assert "reason" in response.data
    assert reload(sample).status == Sample.Status.REGISTERED


def test_refusing_an_item_is_role_gated(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["analyst"]))

    response = client.post(
        f"/api/v1/samples/{sample.id}/reject-at-receipt/", {"reason": "Leaking."}, format="json"
    )

    assert response.status_code == 403
    assert reload(sample).status == Sample.Status.REGISTERED


def test_a_refused_item_does_not_land_in_the_nonconforming_work_queue(login_as_staff):
    """
    7.4.3, not 7.10: nothing was tested, so there are no results whose
    significance an investigation would evaluate.
    """
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    client = login_as_staff(StaffUserFactory(roles=["sample_receiver"]))

    client.post(
        f"/api/v1/samples/{sample.id}/reject-at-receipt/", {"reason": "Wrong container type."}, format="json"
    )

    assert reload(sample).status != Sample.Status.UNDER_INVESTIGATION


def test_a_refused_item_can_be_disposed_of(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    login_as_staff(StaffUserFactory(roles=["sample_receiver"])).post(
        f"/api/v1/samples/{sample.id}/reject-at-receipt/", {"reason": "Wrong container type."}, format="json"
    )

    response = login_as_staff(StaffUserFactory(roles=["qa_officer"])).post(
        f"/api/v1/samples/{sample.id}/dispose/"
    )

    assert response.status_code == 200, response.data
    assert reload(sample).status == Sample.Status.DISPOSED


def test_a_refused_item_cannot_be_prepped(login_as_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)
    login_as_staff(StaffUserFactory(roles=["sample_receiver"])).post(
        f"/api/v1/samples/{sample.id}/reject-at-receipt/", {"reason": "Wrong container type."}, format="json"
    )

    response = login_as_staff(StaffUserFactory(roles=["analyst"])).post(
        f"/api/v1/samples/{sample.id}/start-prep/"
    )

    assert response.status_code == 400
    assert reload(sample).status == Sample.Status.RECEIPT_REJECTED
