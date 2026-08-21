"""
Instrument raw-data ingestion (Blueprint Section 11):
POST /test-requests/{id}/ingest.

The assertions that matter are the ones tying ingested results to the same
rules manual entry obeys. An ingestion path that skips the competency gate,
or trusts the instrument's own idea of whether a value passed, is worse
than no ingestion at all -- it produces regulated records that look
identical to hand-entered ones and were never checked.
"""

import hashlib
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.testing.ingestion import IngestionError, parse_generic_csv, parser_for
from apps.testing.models import TestResult
from tests.factories import (
    InstrumentFactory,
    StaffUserFactory,
    TestMethodFactory,
    TestRequestFactory,
)

pytestmark = pytest.mark.django_db


def csv_upload(text, name="export.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


@pytest.fixture
def oss_bucket():
    """
    The endpoint stores the raw file before parsing, so every test that goes
    through it needs a bucket. Declared as a fixture rather than hidden in
    upload_object() because provisioning the bucket is IaC's job in
    production, not something a request should do on every upload.
    """
    from apps.audit.oss import ensure_bucket

    ensure_bucket()


def certified_analyst(test_method, role="analyst"):
    from tests.factories import RoleFactory

    user = StaffUserFactory()
    user.roles.add(RoleFactory(name=role))
    user.instrument_certifications.add(test_method)
    return user


# --- Parsing ---------------------------------------------------------------

def test_a_well_formed_export_becomes_results():
    method = TestMethodFactory(specification_limits={"max": 1.0})

    rows = parse_generic_csv(b"value,unit\n0.4,mg/L\n0.6,mg/L\n", method)

    assert [r["value"] for r in rows] == ["0.4", "0.6"]
    assert all(r["unit"] == "mg/L" for r in rows)
    assert all(r["data_type"] == TestResult.DataType.FLOAT for r in rows)


def test_a_multi_analyte_export_keeps_each_row_labelled():
    """
    The case the analyte field exists for: one TestRequest, one TestMethod,
    twelve elements. Without the label these are twelve unattributable
    numbers on a certificate.
    """
    method = TestMethodFactory(specification_limits={"max": 1.0})

    rows = parse_generic_csv(
        b"analyte,value,unit\nLead,0.4,mg/L\nCadmium,9.9,mg/L\nMercury,0.1,mg/L\n", method
    )

    assert [r["analyte"] for r in rows] == ["Lead", "Cadmium", "Mercury"]
    # The OOS rule still applies per row, independent of the label.
    assert [r["is_out_of_spec"] for r in rows] == [False, True, False]


def test_analyte_is_optional_for_a_single_parameter_method():
    # A pH method reports one number; the method name already says what was
    # measured, so requiring a label would be noise.
    method = TestMethodFactory()

    rows = parse_generic_csv(b"value,unit\n7.2,pH\n", method)

    assert rows[0]["analyte"] == ""


def test_out_of_spec_is_computed_from_the_method_not_the_file():
    # The instrument does not get a vote: the limit comes from TestMethod.
    method = TestMethodFactory(specification_limits={"max": 1.0})

    rows = parse_generic_csv(b"value,unit\n0.4,mg/L\n9.9,mg/L\n", method)

    assert [r["is_out_of_spec"] for r in rows] == [False, True]


def test_a_utf8_bom_is_tolerated():
    # Instrument software on Windows writes CSV with a BOM often enough
    # that failing on it would make the feature look broken.
    method = TestMethodFactory()

    rows = parse_generic_csv("﻿value,unit\n1.0,g\n".encode("utf-8"), method)

    assert rows[0]["value"] == "1.0"


def test_columns_are_matched_case_and_space_insensitively():
    method = TestMethodFactory()

    rows = parse_generic_csv(b" Value , Unit \n 2.5 , mg \n", method)

    assert rows[0]["value"] == "2.5"
    assert rows[0]["unit"] == "mg"


def test_a_binary_export_is_rejected_with_an_actionable_message():
    method = TestMethodFactory()

    with pytest.raises(IngestionError, match="not valid UTF-8"):
        parse_generic_csv(b"\x00\x01\x02\xff\xfe", method)


def test_a_missing_value_column_is_rejected():
    method = TestMethodFactory()

    with pytest.raises(IngestionError, match="value"):
        parse_generic_csv(b"reading,unit\n0.4,mg/L\n", method)


def test_a_non_numeric_value_in_a_numeric_column_is_rejected():
    # Storing it would skip the OOS check entirely and enter the record as
    # in-spec, which is the quiet failure this guards.
    method = TestMethodFactory(specification_limits={"max": 1.0})

    with pytest.raises(IngestionError, match="not numeric"):
        parse_generic_csv(b"value,unit\nn/a,mg/L\n", method)


def test_a_header_only_file_is_rejected():
    method = TestMethodFactory()

    with pytest.raises(IngestionError, match="no data rows"):
        parse_generic_csv(b"value,unit\n", method)


def test_an_unknown_data_type_is_rejected():
    method = TestMethodFactory()

    with pytest.raises(IngestionError, match="unknown data_type"):
        parse_generic_csv(b"value,data_type\n1,quantum\n", method)


def test_a_trailing_delimiter_is_tolerated():
    # "Lead,0.42," -- one empty surplus field. csv.DictReader files anything
    # past the header under the None key as a *list*, which used to reach
    # a .strip() call and raise AttributeError: an unhandled 500 on the most
    # ordinary formatting artifact a CSV export has.
    method = TestMethodFactory(specification_limits={"max": 1.0})

    rows = parse_generic_csv(b"analyte,value\nLead,0.42,\n", method)

    assert len(rows) == 1
    assert rows[0]["analyte"] == "Lead"
    assert rows[0]["value"] == "0.42"


def test_a_row_with_more_values_than_columns_is_rejected():
    # Surplus with content in it means we cannot know which value belongs to
    # which column. Refusing the file beats storing a guess in a regulated
    # record -- and it must be the parser's own 400, not a 500.
    method = TestMethodFactory()

    with pytest.raises(IngestionError, match=r"Row 2: 3 values for 2 columns"):
        parse_generic_csv(b"analyte,value\nLead,0.42,extra\n", method)


def test_an_over_length_field_is_rejected_by_the_parser_not_the_database():
    # TestResult.unit is a CharField(max_length=32). Without this check the
    # row reaches Postgres during bulk_create and fails as "value too long
    # for type character varying(32)" -- a 500 quoting a column name at
    # someone who uploaded a file.
    method = TestMethodFactory()

    with pytest.raises(IngestionError, match=r"Row 2: 'unit' is longer than 32 characters"):
        parse_generic_csv(f"value,unit\n1,{'x' * 33}\n".encode(), method)

    with pytest.raises(IngestionError, match=r"Row 2: 'analyte' is longer than 255 characters"):
        parse_generic_csv(f"analyte,value\n{'x' * 256},1\n".encode(), method)


def test_an_instrument_without_a_vendor_parser_falls_back_to_csv():
    # Every instrument in NASAT's list can export CSV, so an unregistered
    # model means "no vendor parser yet", not "unusable".
    instrument = InstrumentFactory()

    assert parser_for(instrument) is parse_generic_csv
    assert parser_for(None) is parse_generic_csv


# --- Endpoint --------------------------------------------------------------

def test_ingesting_creates_results_linked_to_the_stored_file(login_as_staff, oss_bucket):
    method = TestMethodFactory(specification_limits={"max": 1.0})
    test_request = TestRequestFactory(test_method=method)
    client = login_as_staff(certified_analyst(method))

    response = client.post(
        f"/api/v1/test-requests/{test_request.pk}/ingest/",
        {"file": csv_upload("value,unit\n0.4,mg/L\n9.9,mg/L\n")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["created"] == 2
    results = test_request.results.order_by("value")
    # ALCOA traceability: every result points back at the file it came from.
    assert {r.raw_file_id for r in results} == {body["raw_file_id"]}
    assert {r.raw_file_checksum_sha256 for r in results} == {body["checksum_sha256"]}
    assert body["checksum_sha256"] == hashlib.sha256(b"value,unit\n0.4,mg/L\n9.9,mg/L\n").hexdigest()
    assert sorted(r.is_out_of_spec for r in results) == [False, True]


def test_ingesting_a_multi_analyte_file_persists_the_labels(login_as_staff, oss_bucket):
    method = TestMethodFactory(specification_limits={"max": 1.0})
    test_request = TestRequestFactory(test_method=method)
    client = login_as_staff(certified_analyst(method))

    response = client.post(
        f"/api/v1/test-requests/{test_request.pk}/ingest/",
        {"file": csv_upload("analyte,value,unit\nLead,0.4,mg/L\nCadmium,9.9,mg/L\n")},
    )

    assert response.status_code == 201
    stored = {r.analyte: r for r in test_request.results.all()}
    assert set(stored) == {"Lead", "Cadmium"}
    assert stored["Cadmium"].is_out_of_spec is True
    assert stored["Lead"].is_out_of_spec is False


def test_an_uncertified_analyst_cannot_ingest(login_as_staff):
    # The competency gate applies identically to uploading and typing --
    # otherwise it is decorative.
    from tests.factories import RoleFactory

    method = TestMethodFactory()
    test_request = TestRequestFactory(test_method=method)
    user = StaffUserFactory()
    user.roles.add(RoleFactory(name="analyst"))  # role yes, certification no
    client = login_as_staff(user)

    response = client.post(
        f"/api/v1/test-requests/{test_request.pk}/ingest/",
        {"file": csv_upload("value,unit\n0.4,mg/L\n")},
    )

    assert response.status_code == 400
    assert "not certified" in str(response.json())
    assert test_request.results.count() == 0


def test_ingesting_requires_the_analyst_role(login_as_staff):
    method = TestMethodFactory()
    test_request = TestRequestFactory(test_method=method)
    client = login_as_staff(StaffUserFactory())  # no roles at all

    response = client.post(
        f"/api/v1/test-requests/{test_request.pk}/ingest/",
        {"file": csv_upload("value,unit\n0.4,mg/L\n")},
    )

    assert response.status_code == 403


def test_re_uploading_the_same_file_is_refused(login_as_staff, oss_bucket):
    # Double-ingesting would double every result on the request, which in a
    # regulated record is a data-integrity incident rather than a nuisance.
    method = TestMethodFactory()
    test_request = TestRequestFactory(test_method=method)
    client = login_as_staff(certified_analyst(method))
    payload = "value,unit\n0.4,mg/L\n"

    first = client.post(f"/api/v1/test-requests/{test_request.pk}/ingest/", {"file": csv_upload(payload)})
    second = client.post(f"/api/v1/test-requests/{test_request.pk}/ingest/", {"file": csv_upload(payload)})

    assert first.status_code == 201
    assert second.status_code == 409
    assert test_request.results.count() == 1


def test_a_different_file_is_still_accepted_afterwards(login_as_staff, oss_bucket):
    method = TestMethodFactory()
    test_request = TestRequestFactory(test_method=method)
    client = login_as_staff(certified_analyst(method))

    client.post(f"/api/v1/test-requests/{test_request.pk}/ingest/", {"file": csv_upload("value\n0.4\n")})
    second = client.post(f"/api/v1/test-requests/{test_request.pk}/ingest/", {"file": csv_upload("value\n0.5\n")})

    assert second.status_code == 201
    assert test_request.results.count() == 2


def test_a_malformed_file_is_reported_with_the_parser_message(login_as_staff, oss_bucket):
    method = TestMethodFactory()
    test_request = TestRequestFactory(test_method=method)
    client = login_as_staff(certified_analyst(method))

    response = client.post(
        f"/api/v1/test-requests/{test_request.pk}/ingest/",
        {"file": csv_upload("value,unit\nn/a,mg/L\n")},
    )

    assert response.status_code == 400
    # "row 2: value 'n/a' is not numeric" is actionable; "could not parse
    # file" would not be.
    assert "Row 2" in str(response.json())
    assert test_request.results.count() == 0


def test_a_missing_file_is_a_400_not_a_500(login_as_staff):
    method = TestMethodFactory()
    test_request = TestRequestFactory(test_method=method)
    client = login_as_staff(certified_analyst(method))

    response = client.post(f"/api/v1/test-requests/{test_request.pk}/ingest/", {})

    assert response.status_code == 400
    assert "file" in str(response.json()).lower()


def test_the_raw_file_is_stored_even_when_parsing_fails(login_as_staff, oss_bucket):
    """
    ALCOA traceability wants the artifact the lab actually received,
    including one that turned out to be malformed -- so the upload happens
    before the parse, and survives it failing.
    """
    from django.conf import settings

    from apps.audit.oss import get_client

    method = TestMethodFactory()
    test_request = TestRequestFactory(test_method=method)
    client = login_as_staff(certified_analyst(method))
    payload = "value,unit\nn/a,mg/L\n"

    response = client.post(
        f"/api/v1/test-requests/{test_request.pk}/ingest/", {"file": csv_upload(payload)}
    )

    assert response.status_code == 400
    digest = hashlib.sha256(payload.encode()).hexdigest()
    stored = get_client().get_object(
        Bucket=settings.OSS_BUCKET_NAME, Key=f"raw-instrument-exports/{test_request.pk}/{digest}"
    )
    assert stored["Body"].read().decode() == payload
