"""
`manage.py import_price_list`, which is how a rate card actually arrives.

The behaviour worth pinning is what happens to a file that is *nearly*
right, because that is the file people have: a peso sign in the price
column, a thousands separator, a blank spacer row, a method reference that
doesn't match anything. Two of those are fine and two must stop the import,
and the difference matters -- a rate card half-loaded looks loaded.
"""

import datetime
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalogue.models import ServiceOffering
from tests.factories import TestMethodFactory

pytestmark = pytest.mark.django_db

HEADER = "code,name,service_line,price,vat_treatment,turnaround_days,accredited,test_methods,note\n"


def write_csv(tmp_path, body, header=HEADER):
    path = tmp_path / "rates.csv"
    path.write_text(header + body, encoding="utf-8")
    return str(path)


def test_it_imports_offerings_and_prices(tmp_path):
    path = write_csv(
        tmp_path,
        "WQ-BOD5,BOD (5-day),water_environmental,1200.00,exclusive,5,yes,,2026 rate card\n"
        "FA-SEM,SEM/EDS,failure_analysis,8960.00,inclusive,10,no,,\n",
    )

    call_command("import_price_list", path, "--effective-from", "2026-01-01")

    bod = ServiceOffering.objects.get(code="WQ-BOD5")
    assert bod.name == "BOD (5-day)"
    assert bod.turnaround_days == 5
    assert bod.is_accredited is True
    price = bod.price_on(datetime.date(2026, 6, 1))
    assert (price.net_amount, price.gross_amount) == (Decimal("1200.00"), Decimal("1344.00"))

    sem = ServiceOffering.objects.get(code="FA-SEM")
    assert sem.price_on(datetime.date(2026, 6, 1)).net_amount == Decimal("8000.00")


def test_it_tolerates_the_things_spreadsheets_actually_export(tmp_path):
    path = write_csv(
        tmp_path,
        "wq-tss ,Total Suspended Solids,water_environmental,\"₱1,250.00\",exclusive,,,,\n"
        "\n"
        ",,,,,,,,\n",
    )

    call_command("import_price_list", path)

    offering = ServiceOffering.objects.get()
    assert offering.code == "WQ-TSS"
    assert offering.price_on(offering.prices.get().effective_from).amount == Decimal("1250.00")


def test_re_importing_updates_the_offering_and_supersedes_its_price(tmp_path):
    path = write_csv(tmp_path, "WQ-BOD5,BOD,water_environmental,1000.00,exclusive,,,,\n")
    call_command("import_price_list", path, "--effective-from", "2026-01-01")

    path = write_csv(tmp_path, "WQ-BOD5,BOD (5-day),water_environmental,1200.00,exclusive,,,,\n")
    call_command("import_price_list", path, "--effective-from", "2026-07-01")

    offering = ServiceOffering.objects.get()
    assert offering.name == "BOD (5-day)"
    assert offering.prices.count() == 2
    assert offering.price_on(datetime.date(2026, 3, 1)).amount == Decimal("1000.00")
    assert offering.price_on(datetime.date(2026, 8, 1)).amount == Decimal("1200.00")


def test_a_dry_run_writes_nothing(tmp_path):
    path = write_csv(tmp_path, "WQ-BOD5,BOD,water_environmental,1000.00,exclusive,,,,\n")

    call_command("import_price_list", path, "--dry-run")

    assert ServiceOffering.objects.count() == 0


def test_a_missing_column_stops_the_import_before_anything_is_written(tmp_path):
    path = write_csv(tmp_path, "WQ-BOD5,BOD,1000.00\n", header="code,name,price\n")

    with pytest.raises(CommandError, match="missing required column"):
        call_command("import_price_list", path)

    assert ServiceOffering.objects.count() == 0


def test_a_bad_row_rolls_back_the_whole_file(tmp_path):
    """A rate card is one document: half of one loaded is worse than none."""
    path = write_csv(
        tmp_path,
        "WQ-BOD5,BOD,water_environmental,1000.00,exclusive,,,,\n"
        "WQ-COD,COD,water_environmental,not-a-number,exclusive,,,,\n",
    )

    with pytest.raises(CommandError, match="line 3: price"):
        call_command("import_price_list", path)

    assert ServiceOffering.objects.count() == 0


def test_an_unknown_service_line_names_the_line_it_is_on(tmp_path):
    path = write_csv(tmp_path, "WQ-BOD5,BOD,potable_water,1000.00,exclusive,,,,\n")

    with pytest.raises(CommandError, match="line 2: service_line"):
        call_command("import_price_list", path)


def test_an_unmatched_test_method_is_an_error_not_a_silent_omission(tmp_path):
    TestMethodFactory(name="BOD", method_reference="SM 5210 B")
    path = write_csv(tmp_path, "WQ-POT,Potability,water_environmental,5000.00,exclusive,,,SM 5210 B;SM 9221 B,\n")

    with pytest.raises(CommandError, match="no TestMethod matches 'SM 9221 B'"):
        call_command("import_price_list", path)


def test_methods_are_matched_by_reference_or_name(tmp_path):
    bod = TestMethodFactory(name="BOD", method_reference="SM 5210 B")
    coliform = TestMethodFactory(name="Total coliform", method_reference="SM 9221 B")
    path = write_csv(tmp_path, "WQ-POT,Potability,water_environmental,5000.00,exclusive,,,sm 5210 b;Total coliform,\n")

    call_command("import_price_list", path)

    assert set(ServiceOffering.objects.get().test_methods.all()) == {bod, coliform}
