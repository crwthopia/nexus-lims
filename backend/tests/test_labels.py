"""
Label and job-order printing (FR-C1-02, ISO/IEC 17025:2017 7.4.2).

7.4.2 asks for identification that is unambiguous, survives for as long as
the item is in the laboratory, accommodates subdivision, and never lets two
items be confused. Printing is where that meets a roll of adhesive stock,
and the tests split along the two ways it fails.

**The barcode does not scan.** Everything else on a label is cosmetic; if
the bars do not decode back to the sample code the feature is worthless,
and no assertion about the HTML would notice. So the first group renders
the real PDF, rasterises it at a label printer's DPI and decodes it the way
a handheld scanner would. That is a heavier test than this suite usually
writes, and it is the only one here that could not be replaced by reading
the template.

**Two containers end up carrying the same identity.** The reprint register
is the control for that, so the second group is about what gets recorded
and what is refused.

Deliberately not tested: how the layout looks. That is QA's to author (the
templates carry placeholder banners saying so), and a test asserting on
millimetres would fail the moment somebody improved the artwork.
"""

import datetime

import pytest
from django.utils import timezone

from apps.samples.models import LabelPrintEvent, Sample
from apps.testing.models import TestRequest
from tests.factories import (
    OrderFactory,
    SampleFactory,
    StaffUserFactory,
    TestMethodFactory,
    TestRequestFactory,
)

pytestmark = pytest.mark.django_db

HOURS_24 = datetime.timedelta(hours=24)


def _received_sample(**kwargs):
    kwargs.setdefault("collection_datetime", timezone.now() - datetime.timedelta(hours=2))
    return SampleFactory(
        status=Sample.Status.RECEIVED,
        received_at=timezone.now() - datetime.timedelta(hours=1),
        **kwargs,
    )


def _printer(*roles):
    return StaffUserFactory(roles=list(roles) or ["sample_receiver"])


def _post(client, url, **body):
    return client.post(url, body, format="json")


def page_count(pdf_bytes):
    import pypdfium2 as pdfium

    return len(pdfium.PdfDocument(pdf_bytes))


def decode_barcodes(pdf_bytes, *, dpi=300):
    """
    Read the PDF the way a scanner reads the printed label.

    300dpi is an ordinary thermal-transfer label printer. Rendering at the
    resolution the hardware actually prints at is the point -- a barcode
    that decodes from the vector source but not from a 300dpi raster is a
    barcode that works in a test and fails on the bench.
    """
    import pypdfium2 as pdfium
    import zxingcpp

    document = pdfium.PdfDocument(pdf_bytes)
    found = []
    for page in document:
        image = page.render(scale=dpi / 72).to_pil()
        found.extend(result.text for result in zxingcpp.read_barcodes(image))
    return found


# --- the barcode actually scans ---------------------------------------------


def test_the_printed_barcode_decodes_back_to_the_sample_code(login_as_staff):
    sample = _received_sample(unique_sample_code="WE-202609-0042")
    client = login_as_staff(_printer())

    response = _post(client, f"/api/v1/samples/{sample.id}/labels/")

    assert response.status_code == 200, response.content[:400]
    assert response["Content-Type"] == "application/pdf"
    assert decode_barcodes(response.content) == ["WE-202609-0042"]


def test_every_container_gets_exactly_one_page(login_as_staff):
    """
    Three bottles, three labels, all carrying the same identity -- and
    three *pages*, which is the half a barcode assertion cannot see.

    Content that overflows a 25mm label is not truncated: the remainder is
    pushed onto another page, which a label printer obediently feeds as a
    blank label and which every decode-only test passes straight over. This
    caught exactly that during development.
    """
    sample = _received_sample(unique_sample_code="WE-202609-0043", container_count=3)
    client = login_as_staff(_printer())

    response = _post(client, f"/api/v1/samples/{sample.id}/labels/")

    assert decode_barcodes(response.content) == ["WE-202609-0043"] * 3
    assert page_count(response.content) == 3


def test_a_label_with_every_field_populated_still_fits_one_page(login_as_staff):
    """
    The worst case the layout has to survive: hazards, a long client
    reference, a long preservation note, a storage location, and a deadline
    counted from receipt -- which is the one that carries an extra
    annotation. If this spills, every label printed that day is
    interleaved with blanks.
    """
    from apps.testing import holding_times

    sample = _received_sample(
        unique_sample_code="WE-202609-0047",
        collection_datetime=None,          # forces the receipt-basis annotation
        client_reference="CUSTOMER-JOB-2026-00118",
        preservation_method="HNO3 to pH<2, chilled 0-6 C",
        safety_flags=["Corrosive", "Biohazard"],
    )
    test_request = TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=HOURS_24))
    holding_times.apply_to(test_request)
    client = login_as_staff(_printer())

    response = _post(client, f"/api/v1/samples/{sample.id}/labels/")

    assert response.status_code == 200, response.content[:400]
    assert page_count(response.content) == 1
    assert decode_barcodes(response.content) == ["WE-202609-0047"]


def test_a_batch_prints_every_sample_asked_for(login_as_staff):
    first = _received_sample(unique_sample_code="WE-202609-0044")
    second = _received_sample(unique_sample_code="WE-202609-0045", container_count=2)
    client = login_as_staff(_printer())

    response = _post(client, "/api/v1/samples/print-labels/", samples=[first.id, second.id])

    assert response.status_code == 200, response.content[:400]
    assert decode_barcodes(response.content) == [
        "WE-202609-0044", "WE-202609-0045", "WE-202609-0045",
    ]
    assert page_count(response.content) == 3


def test_a_batch_prints_in_the_order_it_was_asked_for(login_as_staff):
    """
    The list a receiving clerk sends is the order the containers are lined
    up in on the bench. Labels coming off the printer in the model's
    newest-first default is how the third bottle gets the second one's
    identity.
    """
    first = _received_sample(unique_sample_code="WE-202609-0060")
    second = _received_sample(unique_sample_code="WE-202609-0061")
    third = _received_sample(unique_sample_code="WE-202609-0062")
    client = login_as_staff(_printer())

    response = _post(client, "/api/v1/samples/print-labels/", samples=[third.id, first.id, second.id])

    assert decode_barcodes(response.content) == [
        "WE-202609-0062", "WE-202609-0060", "WE-202609-0061",
    ]


def test_a_repeated_id_in_a_batch_prints_once(login_as_staff):
    """Asking twice is a slip in the list, not a request for two identities."""
    sample = _received_sample(unique_sample_code="WE-202609-0063")
    client = login_as_staff(_printer())

    response = _post(client, "/api/v1/samples/print-labels/", samples=[sample.id, sample.id])

    assert decode_barcodes(response.content) == ["WE-202609-0063"]
    assert LabelPrintEvent.objects.count() == 1


def test_a_worksheet_label_carries_the_parent_sample_code(login_as_staff):
    """
    7.4.2 on subdivision: an aliquot scans onto the record the container
    scans onto, because results, review and the report all hang off the
    sample. The suffix distinguishing the tubes is for the human.
    """
    sample = _received_sample(unique_sample_code="WE-202609-0046")
    test_request = TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=HOURS_24))
    client = login_as_staff(_printer("analyst"))

    response = _post(client, f"/api/v1/test-requests/{test_request.id}/label/", copies=2)

    assert response.status_code == 200, response.content[:400]
    assert decode_barcodes(response.content) == ["WE-202609-0046"] * 2
    assert page_count(response.content) == 2


def test_a_code_too_long_for_the_stock_is_refused_not_truncated(login_as_staff):
    """
    A barcode running off the edge of a label is not a slightly worse
    barcode: it can scan as a different, shorter code, which is a container
    carrying somebody else's identity. "Use wider stock" is a fixable
    answer; a truncated barcode is a silent one.
    """
    sample = _received_sample(unique_sample_code="LEGACY-SAMPLE-CODE-FROM-A-PRIOR-SYSTEM-0001")
    client = login_as_staff(_printer())

    response = _post(client, f"/api/v1/samples/{sample.id}/labels/")

    assert response.status_code == 400
    assert "wider stock" in str(response.data)
    assert not LabelPrintEvent.objects.exists()


def test_a_client_may_ask_for_a_pdf_by_name(login_as_staff):
    """
    DRF negotiates before it dispatches, so an endpoint that produces PDF
    has to declare it or answer 406 to a client asking for exactly what it
    returns. A real browser did.
    """
    sample = _received_sample(unique_sample_code="WE-202609-0048")
    client = login_as_staff(_printer())

    response = client.post(
        f"/api/v1/samples/{sample.id}/labels/", {}, format="json", HTTP_ACCEPT="application/pdf",
    )

    assert response.status_code == 200, response.content[:400]
    assert response["Content-Type"] == "application/pdf"
    assert decode_barcodes(response.content) == ["WE-202609-0048"]


def test_an_error_still_comes_back_readable_when_a_pdf_was_asked_for(login_as_staff):
    """
    The refusal is raised after negotiation, so it renders through the PDF
    renderer. A client that asked for a PDF and did not get one still has
    to be able to read why -- otherwise the console shows "something went
    wrong" instead of the reason, and the reprint prompt never fires.
    """
    sample = _received_sample(unique_sample_code="WE-202609-0049")
    client = login_as_staff(_printer())
    assert client.post(f"/api/v1/samples/{sample.id}/labels/", {}, format="json").status_code == 200

    response = client.post(
        f"/api/v1/samples/{sample.id}/labels/", {}, format="json", HTTP_ACCEPT="application/pdf",
    )

    assert response.status_code == 400
    assert response["Content-Type"] == "application/json"
    assert "7.4.2" in response.content.decode()


# --- what the label says -----------------------------------------------------


def test_the_label_carries_the_soonest_holding_time_deadline(login_as_staff):
    """
    A container is one physical thing with several analyses queued against
    it. Print the latest deadline and the short-hold analysis is quietly
    lost, so the one that belongs on the side is the first that bites.
    """
    from apps.samples import labels as label_services

    collected = timezone.now()
    sample = _received_sample(collection_datetime=collected)
    TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=datetime.timedelta(hours=48)))
    TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=HOURS_24))
    for test_request in sample.test_requests.all():
        from apps.testing import holding_times
        holding_times.apply_to(test_request)

    due_at, basis, expired = label_services.earliest_deadline(Sample.objects.get(pk=sample.pk))

    assert due_at == collected + HOURS_24
    assert basis == TestRequest.DueBasis.COLLECTION
    assert expired is False


def test_completed_work_does_not_keep_a_container_flagged(login_as_staff):
    from apps.samples import labels as label_services
    from apps.testing import holding_times

    sample = _received_sample(collection_datetime=timezone.now() - datetime.timedelta(hours=48))
    test_request = TestRequestFactory(
        sample=sample,
        test_method=TestMethodFactory(holding_time=HOURS_24),
        status=TestRequest.Status.COMPLETED,
    )
    holding_times.apply_to(test_request)

    due_at, _basis, _expired = label_services.earliest_deadline(Sample.objects.get(pk=sample.pk))

    assert due_at is None


def test_a_sample_with_no_holding_time_still_prints(login_as_staff):
    """Most of the Failure Analysis line. The label just has no date on it."""
    sample = _received_sample(unique_sample_code="FA-202609-0001")
    TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=None))
    client = login_as_staff(_printer())

    response = _post(client, f"/api/v1/samples/{sample.id}/labels/")

    assert response.status_code == 200
    assert decode_barcodes(response.content) == ["FA-202609-0001"]


# --- the reprint register (7.4.2: items must not be confused) ----------------


def test_printing_records_who_printed_what(login_as_staff):
    sample = _received_sample(container_count=2)
    receiver = _printer()
    client = login_as_staff(receiver)

    _post(client, f"/api/v1/samples/{sample.id}/labels/")

    event = LabelPrintEvent.objects.get()
    assert event.kind == LabelPrintEvent.Kind.CONTAINER
    assert event.printed_by_id == receiver.id
    assert event.copies == 2
    assert event.is_reprint is False


def test_a_second_print_without_a_reason_is_refused(login_as_staff):
    sample = _received_sample()
    client = login_as_staff(_printer())
    assert _post(client, f"/api/v1/samples/{sample.id}/labels/").status_code == 200

    response = _post(client, f"/api/v1/samples/{sample.id}/labels/")

    assert response.status_code == 400
    assert "7.4.2" in str(response.data)
    assert LabelPrintEvent.objects.count() == 1


def test_a_reprint_with_a_reason_is_recorded_as_one(login_as_staff):
    sample = _received_sample()
    client = login_as_staff(_printer())
    _post(client, f"/api/v1/samples/{sample.id}/labels/")

    response = _post(
        client, f"/api/v1/samples/{sample.id}/labels/",
        reason="Original label came off in the cold room.",
    )

    assert response.status_code == 200
    reprint = LabelPrintEvent.objects.latest("printed_at")
    assert reprint.is_reprint is True
    assert "cold room" in reprint.reason


def test_the_client_cannot_declare_its_own_print_a_first_print(login_as_staff):
    """
    is_reprint is looked up server-side. A caller that could set it could
    print unexplained duplicate identities indefinitely.
    """
    sample = _received_sample()
    client = login_as_staff(_printer())
    _post(client, f"/api/v1/samples/{sample.id}/labels/")

    response = client.post(
        f"/api/v1/samples/{sample.id}/labels/",
        {"is_reprint": False, "reason": "Trying to look like a first print."},
        format="json",
    )

    assert response.status_code == 200
    assert LabelPrintEvent.objects.latest("printed_at").is_reprint is True


def test_a_worksheet_label_is_a_different_kind_from_a_container_label(login_as_staff):
    """
    Printing an aliquot label is not a reprint of the bottle's label: they
    identify different things and each gets its own first print.
    """
    sample = _received_sample()
    test_request = TestRequestFactory(sample=sample, test_method=TestMethodFactory())
    client = login_as_staff(_printer("sample_receiver", "analyst"))
    _post(client, f"/api/v1/samples/{sample.id}/labels/")

    response = _post(client, f"/api/v1/test-requests/{test_request.id}/label/")

    assert response.status_code == 200
    assert LabelPrintEvent.objects.filter(is_reprint=True).count() == 0
    assert LabelPrintEvent.objects.count() == 2


def test_a_batch_records_one_event_per_sample(login_as_staff):
    """So the register still answers "was this container labelled" one sample at a time."""
    first = _received_sample()
    second = _received_sample()
    client = login_as_staff(_printer())

    _post(client, "/api/v1/samples/print-labels/", samples=[first.id, second.id])

    assert set(LabelPrintEvent.objects.values_list("sample_id", flat=True)) == {first.id, second.id}


def test_a_batch_naming_an_unknown_sample_prints_nothing(login_as_staff):
    """A batch that quietly prints eleven of twelve is a sample that goes into a fridge unlabelled."""
    sample = _received_sample()
    client = login_as_staff(_printer())

    response = _post(client, "/api/v1/samples/print-labels/", samples=[sample.id, 999999])

    assert response.status_code == 400
    assert "999999" in str(response.data)
    assert not LabelPrintEvent.objects.exists()


def test_printing_is_role_gated(login_as_staff):
    sample = _received_sample()
    client = login_as_staff(StaffUserFactory(roles=["reviewer"]))

    response = _post(client, f"/api/v1/samples/{sample.id}/labels/")

    assert response.status_code == 403
    assert not LabelPrintEvent.objects.exists()


# --- the job order sheet ------------------------------------------------------


def test_the_job_order_prints_and_is_recorded(login_as_staff):
    order = OrderFactory()
    sample = _received_sample(order=order, service_line=order.service_line)
    TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=HOURS_24))
    client = login_as_staff(_printer())

    response = _post(client, f"/api/v1/orders/{order.id}/job-order/")

    assert response.status_code == 200, response.content[:400]
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    event = LabelPrintEvent.objects.get()
    assert event.kind == LabelPrintEvent.Kind.JOB_ORDER
    assert event.order_id == order.id


def test_an_order_with_no_samples_still_prints(login_as_staff):
    """A sheet printed ahead of a delivery is a legitimate thing to want."""
    order = OrderFactory()
    client = login_as_staff(_printer())

    response = _post(client, f"/api/v1/orders/{order.id}/job-order/")

    assert response.status_code == 200, response.content[:400]


def test_the_job_order_is_role_gated(login_as_staff):
    order = OrderFactory()
    client = login_as_staff(StaffUserFactory(roles=["reviewer"]))

    response = _post(client, f"/api/v1/orders/{order.id}/job-order/")

    assert response.status_code == 403
