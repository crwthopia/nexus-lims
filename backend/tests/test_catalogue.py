"""
The service catalogue and its prices.

Two things here are worth a test rather than a comment.

**The VAT arithmetic**, because NASAT quotes both ways. A rate published
VAT-exclusive and the same money published VAT-inclusive must produce the
same three figures, and adding a net rate to a gross one -- which is what a
dashboard does if the treatment is not carried with the number -- is wrong
by 12% with nothing on screen to say so.

**The price history**, because an invoice raised in March must keep quoting
March's rate. A price is superseded, never edited, so the windows have to
stay contiguous and non-overlapping however the prices arrive: in order,
back-dated, or corrected the same day.
"""

import datetime
from decimal import Decimal

import pytest

from apps.catalogue import services
from apps.catalogue.models import OfferingPrice, ServiceOffering
from tests.factories import OfferingPriceFactory, ServiceOfferingFactory, StaffUserFactory, TestMethodFactory

pytestmark = pytest.mark.django_db

EXCLUSIVE = OfferingPrice.VatTreatment.EXCLUSIVE
INCLUSIVE = OfferingPrice.VatTreatment.INCLUSIVE


def _set_price(client, offering, **payload):
    return client.post(f"/api/v1/service-offerings/{offering.id}/set-price/", payload, format="json")


# --- VAT, both ways --------------------------------------------------------


def test_a_vat_exclusive_price_adds_vat_on_top():
    price = OfferingPriceFactory(amount=Decimal("1000.00"), vat_treatment=EXCLUSIVE)

    assert price.net_amount == Decimal("1000.00")
    assert price.vat_amount == Decimal("120.00")
    assert price.gross_amount == Decimal("1120.00")


def test_a_vat_inclusive_price_backs_vat_out():
    price = OfferingPriceFactory(amount=Decimal("1120.00"), vat_treatment=INCLUSIVE)

    assert price.net_amount == Decimal("1000.00")
    assert price.vat_amount == Decimal("120.00")
    assert price.gross_amount == Decimal("1120.00")


def test_the_two_treatments_describe_the_same_money():
    """The whole reason the treatment is stored: 1000 net and 1120 gross are one price."""
    net_quoted = OfferingPriceFactory(amount=Decimal("1000.00"), vat_treatment=EXCLUSIVE)
    gross_quoted = OfferingPriceFactory(amount=Decimal("1120.00"), vat_treatment=INCLUSIVE)

    assert net_quoted.net_amount == gross_quoted.net_amount
    assert net_quoted.gross_amount == gross_quoted.gross_amount


def test_net_plus_vat_always_equals_gross_at_awkward_amounts():
    """
    Rounded independently, the three figures disagree by a centavo often
    enough to matter -- 1234.56 inclusive is the canonical example.
    """
    for amount in ["1234.56", "999.99", "0.05", "77777.77"]:
        for treatment in (EXCLUSIVE, INCLUSIVE):
            price = OfferingPriceFactory(amount=Decimal(amount), vat_treatment=treatment)
            assert price.net_amount + price.vat_amount == price.gross_amount, f"{amount} {treatment}"


def test_a_zero_rated_service_is_a_rate_not_a_special_case():
    price = OfferingPriceFactory(amount=Decimal("500.00"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("0.00"))

    assert price.vat_amount == Decimal("0.00")
    assert price.gross_amount == Decimal("500.00")


def test_rounding_is_half_up_as_an_invoice_does():
    # 0.125 -> 0.13, not Decimal's default banker's-rounding 0.12.
    price = OfferingPriceFactory(amount=Decimal("1.25"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("10.00"))

    assert price.gross_amount == Decimal("1.38")


# --- price history ---------------------------------------------------------


def test_a_new_price_closes_the_previous_one_the_day_before():
    offering = ServiceOfferingFactory()
    first = services.set_price(
        offering, amount=Decimal("1000"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("12"),
        effective_from=datetime.date(2026, 1, 1),
    )

    second = services.set_price(
        offering, amount=Decimal("1200"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("12"),
        effective_from=datetime.date(2026, 7, 1),
    )

    first.refresh_from_db()
    assert first.effective_to == datetime.date(2026, 6, 30)
    assert second.effective_to is None
    assert offering.price_on(datetime.date(2026, 6, 30)) == first
    assert offering.price_on(datetime.date(2026, 7, 1)) == second


def test_an_invoice_raised_before_a_rise_still_quotes_the_old_rate():
    """The reason prices are versioned rather than edited."""
    offering = ServiceOfferingFactory()
    services.set_price(
        offering, amount=Decimal("1000"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("12"),
        effective_from=datetime.date(2026, 1, 1),
    )
    services.set_price(
        offering, amount=Decimal("1500"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("12"),
        effective_from=datetime.date(2026, 7, 1),
    )

    assert offering.price_on(datetime.date(2026, 3, 15)).amount == Decimal("1000.00")


def test_correcting_todays_price_replaces_it_rather_than_stacking():
    offering = ServiceOfferingFactory()
    today = services.today()
    services.set_price(
        offering, amount=Decimal("1000"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("12"), effective_from=today,
    )

    services.set_price(
        offering, amount=Decimal("1100"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("12"), effective_from=today,
    )

    assert offering.prices.count() == 1
    assert offering.price_on(today).amount == Decimal("1100.00")


def test_a_back_dated_price_does_not_swallow_the_period_after_it():
    offering = ServiceOfferingFactory()
    current = services.set_price(
        offering, amount=Decimal("1500"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("12"),
        effective_from=datetime.date(2026, 7, 1),
    )

    back_dated = services.set_price(
        offering, amount=Decimal("1000"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("12"),
        effective_from=datetime.date(2026, 1, 1),
    )

    assert back_dated.effective_to == datetime.date(2026, 6, 30)
    current.refresh_from_db()
    assert current.effective_to is None
    assert offering.price_on(datetime.date(2026, 7, 2)) == current


def test_an_offering_priced_from_next_month_has_no_price_today():
    offering = ServiceOfferingFactory()
    services.set_price(
        offering, amount=Decimal("1000"), vat_treatment=EXCLUSIVE, vat_rate_pct=Decimal("12"),
        effective_from=services.today() + datetime.timedelta(days=30),
    )

    assert offering.price_on(services.today()) is None


# --- API -------------------------------------------------------------------


def test_setting_a_price_requires_a_catalogue_role(login_as_staff):
    offering = ServiceOfferingFactory()
    client = login_as_staff(StaffUserFactory(roles=["analyst"]))

    response = _set_price(client, offering, amount="1000.00", vat_treatment="exclusive")

    assert response.status_code == 403
    assert offering.prices.count() == 0


def test_a_lab_supervisor_can_price_an_offering(login_as_staff):
    offering = ServiceOfferingFactory()
    supervisor = StaffUserFactory(roles=["lab_supervisor"])
    client = login_as_staff(supervisor)

    response = _set_price(client, offering, amount="1120.00", vat_treatment="inclusive", note="2026 rate card")

    assert response.status_code == 200
    assert response.data["current_price"]["net_amount"] == "1000.00"
    assert response.data["current_price"]["gross_amount"] == "1120.00"
    assert offering.prices.get().created_by_id == supervisor.id


def test_the_response_carries_all_three_figures_so_no_caller_recomputes_them(login_as_staff):
    offering = ServiceOfferingFactory()
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))
    _set_price(client, offering, amount="1000.00", vat_treatment="exclusive")

    response = client.get(f"/api/v1/service-offerings/{offering.id}/")

    price = response.data["current_price"]
    assert (price["net_amount"], price["vat_amount"], price["gross_amount"]) == ("1000.00", "120.00", "1120.00")


def test_creating_an_offering_requires_a_catalogue_role(login_as_staff):
    client = login_as_staff(StaffUserFactory(roles=["qa_officer"]))

    response = client.post(
        "/api/v1/service-offerings/",
        {"code": "WQ-BOD5", "name": "BOD (5-day)", "service_line": "water_environmental"},
        format="json",
    )

    assert response.status_code == 403


def test_any_staff_member_can_read_the_catalogue(login_as_staff):
    ServiceOfferingFactory(code="WQ-BOD5")
    client = login_as_staff(StaffUserFactory(roles=["analyst"]))

    response = client.get("/api/v1/service-offerings/")

    assert response.status_code == 200
    assert [row["code"] for row in response.data["results"]] == ["WQ-BOD5"]


def test_a_code_is_normalised_so_two_spellings_are_one_offering(login_as_staff):
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))

    created = client.post(
        "/api/v1/service-offerings/",
        {"code": " wq-bod5 ", "name": "BOD (5-day)", "service_line": "water_environmental"},
        format="json",
    )
    duplicate = client.post(
        "/api/v1/service-offerings/",
        {"code": "WQ-BOD5", "name": "BOD again", "service_line": "water_environmental"},
        format="json",
    )

    assert created.status_code == 201
    assert created.data["code"] == "WQ-BOD5"
    assert duplicate.status_code == 400


def test_training_is_refused_because_its_catalogue_is_elsewhere(login_as_staff):
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))

    response = client.post(
        "/api/v1/service-offerings/",
        {"code": "TR-001", "name": "ISO 17025 workshop", "service_line": "training"},
        format="json",
    )

    assert response.status_code == 400
    assert "TrainingCourse" in str(response.data["service_line"])


def test_the_database_refuses_a_training_offering_even_without_the_serializer():
    """The serializer states the rule; the check constraint is what enforces it."""
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        ServiceOffering.objects.create(code="TR-002", name="Workshop", service_line="training")


def test_filters_narrow_by_service_line_active_and_text(login_as_staff):
    ServiceOfferingFactory(code="WQ-BOD5", name="BOD (5-day)", service_line="water_environmental")
    ServiceOfferingFactory(code="FA-SEM", name="SEM/EDS", service_line="failure_analysis")
    ServiceOfferingFactory(code="WQ-OLD", name="Withdrawn", service_line="water_environmental", is_active=False)
    client = login_as_staff(StaffUserFactory())

    by_line = client.get("/api/v1/service-offerings/?service_line=water_environmental")
    active_only = client.get("/api/v1/service-offerings/?active=true")
    by_text = client.get("/api/v1/service-offerings/?q=sem")

    assert {row["code"] for row in by_line.data["results"]} == {"WQ-BOD5", "WQ-OLD"}
    assert {row["code"] for row in active_only.data["results"]} == {"WQ-BOD5", "FA-SEM"}
    assert [row["code"] for row in by_text.data["results"]] == ["FA-SEM"]


def test_price_history_is_read_only_over_the_api(login_as_staff):
    price = OfferingPriceFactory()
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))

    response = client.patch(f"/api/v1/offering-prices/{price.id}/", {"amount": "1.00"}, format="json")

    assert response.status_code == 405
    price.refresh_from_db()
    assert price.amount == Decimal("1000.00")


def test_a_panel_carries_its_methods(login_as_staff):
    bod = TestMethodFactory(name="BOD", method_reference="SM 5210 B")
    coliform = TestMethodFactory(name="Total coliform", method_reference="SM 9221 B")
    client = login_as_staff(StaffUserFactory(roles=["lab_supervisor"]))

    response = client.post(
        "/api/v1/service-offerings/",
        {
            "code": "WQ-POT",
            "name": "Potability panel",
            "service_line": "water_environmental",
            "test_methods": [bod.id, coliform.id],
        },
        format="json",
    )

    assert response.status_code == 201
    assert sorted(response.data["test_method_names"]) == ["BOD", "Total coliform"]
