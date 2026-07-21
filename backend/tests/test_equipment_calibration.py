"""FR-E3-02: logging a CalibrationRecord keeps Instrument.status/calibration_due_date in sync."""

import datetime

import pytest
from django.utils import timezone

from apps.equipment.models import Instrument
from tests.factories import InstrumentFactory, StaffUserFactory

pytestmark = pytest.mark.django_db


def _post_calibration(client, instrument, result, next_due_date):
    return client.post(
        "/api/v1/calibration-records/",
        {
            "instrument": instrument.id,
            "performed_at": timezone.now().isoformat(),
            "result": result,
            "next_due_date": next_due_date.isoformat(),
        },
        format="json",
    )


def test_passing_calibration_returns_instrument_to_in_service(login_as_staff):
    instrument = InstrumentFactory(status=Instrument.Status.OUT_OF_CALIBRATION)
    custodian = StaffUserFactory(roles=["instrument_custodian"])
    client = login_as_staff(custodian)
    due_date = timezone.localdate() + datetime.timedelta(days=180)

    response = _post_calibration(client, instrument, "pass", due_date)

    assert response.status_code == 201
    instrument.refresh_from_db()
    assert instrument.status == Instrument.Status.IN_SERVICE
    assert instrument.calibration_due_date == due_date


def test_failing_calibration_marks_instrument_out_of_calibration(login_as_staff):
    instrument = InstrumentFactory(status=Instrument.Status.IN_SERVICE)
    custodian = StaffUserFactory(roles=["instrument_custodian"])
    client = login_as_staff(custodian)
    due_date = timezone.localdate() + datetime.timedelta(days=7)

    response = _post_calibration(client, instrument, "fail", due_date)

    assert response.status_code == 201
    instrument.refresh_from_db()
    assert instrument.status == Instrument.Status.OUT_OF_CALIBRATION
    assert instrument.calibration_due_date == due_date
