"""
Load a rate card into the catalogue from CSV.

A price list arrives as a spreadsheet, every time, from someone who is not
going to type two hundred rows into a web form. This reads that file, and
is deliberately strict about it: a row it cannot understand stops the
import with the line number and the reason, rather than being skipped into
a catalogue nobody then knows is incomplete.

Columns (header row required, order irrelevant, case- and space-insensitive):

    code*              rate-card code, the natural key -- re-importing the
                       same code updates that offering rather than adding one
    name*
    service_line*      failure_analysis | water_environmental
    price*             the published figure
    vat_treatment*     exclusive | inclusive
    vat_rate_pct       default 12.00
    description
    turnaround_days
    accredited         yes/no/true/false/1/0
    active             yes/no/... (default yes)
    test_methods       method references, ';'-separated, matched against
                       TestMethod.method_reference then .name
    note               free text stored against the price version

Usage:

    python manage.py import_price_list rates.csv --effective-from 2026-01-01
    python manage.py import_price_list rates.csv --dry-run

--dry-run parses, validates and reports, and writes nothing. Run it first:
it is the difference between finding out about a bad column now and finding
out after two hundred rows are in the database.
"""

import csv
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalogue import services
from apps.catalogue.models import CATALOGUE_SERVICE_LINES, OfferingPrice, ServiceOffering
from apps.testing.models import TestMethod

REQUIRED = ["code", "name", "service_line", "price", "vat_treatment"]
TRUTHY = {"yes", "y", "true", "t", "1"}
FALSY = {"no", "n", "false", "f", "0", ""}


def _norm(header):
    return (header or "").strip().lower().replace(" ", "_").replace("-", "_")


def _flag(value, field, line, *, default=False):
    text = (value or "").strip().lower()
    if text == "":
        return default
    if text in TRUTHY:
        return True
    if text in FALSY:
        return False
    raise CommandError(f"line {line}: {field} is '{value}'; expected yes/no.")


class Command(BaseCommand):
    help = "Import or update service offerings and their prices from a CSV rate card."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument(
            "--effective-from", default=None,
            help="ISO date the imported prices take effect (default: today). Prices already in force are closed the day before.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Parse and report; write nothing.")

    def handle(self, *args, **options):
        effective_from = self._parse_date(options["effective_from"])
        rows = self._read(options["csv_path"])

        created = updated = repriced = 0
        # One transaction for the file: a rate card is one document, and
        # half of one loaded is worse than none of it, since nothing on
        # screen afterwards says which half.
        with transaction.atomic():
            for line, row in rows:
                offering, was_created = self._upsert_offering(row, line)
                created += was_created
                updated += not was_created
                services.set_price(
                    offering,
                    amount=row["price"],
                    vat_treatment=row["vat_treatment"],
                    vat_rate_pct=row["vat_rate_pct"],
                    effective_from=effective_from,
                    note=row["note"],
                )
                repriced += 1
            if options["dry_run"]:
                transaction.set_rollback(True)

        verb = "would import" if options["dry_run"] else "imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {len(rows)} row(s): {created} new offering(s), {updated} updated, "
                f"{repriced} price(s) effective {effective_from}."
            )
        )
        if options["dry_run"]:
            self.stdout.write("Dry run: nothing was written.")

    # --- parsing -----------------------------------------------------------

    def _parse_date(self, value):
        if not value:
            return services.today()
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError(f"--effective-from must be an ISO date (YYYY-MM-DD), got '{value}'.") from exc

    def _read(self, path):
        try:
            handle = open(path, newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(f"cannot read {path}: {exc}") from exc

        with handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise CommandError(f"{path} is empty.")
            headers = {_norm(h) for h in reader.fieldnames}
            missing = [column for column in REQUIRED if column not in headers]
            if missing:
                raise CommandError(
                    f"{path} is missing required column(s): {', '.join(missing)}. "
                    f"Found: {', '.join(sorted(headers))}."
                )
            rows = []
            for line, raw in enumerate(reader, start=2):
                row = {_norm(k): (v or "").strip() for k, v in raw.items() if k is not None}
                if not any(row.get(column) for column in REQUIRED):
                    continue  # a blank spacer row, which spreadsheets are full of
                rows.append((line, self._clean(row, line)))
        if not rows:
            raise CommandError(f"{path} has a header but no data rows.")
        return rows

    def _clean(self, row, line):
        code = row.get("code", "").strip().upper()
        if not code:
            raise CommandError(f"line {line}: code is required.")

        service_line = row.get("service_line", "").strip().lower()
        allowed = [entry.value for entry in CATALOGUE_SERVICE_LINES]
        if service_line not in allowed:
            raise CommandError(f"line {line}: service_line '{row.get('service_line')}' is not one of {allowed}.")

        treatment = row.get("vat_treatment", "").strip().lower()
        if treatment not in OfferingPrice.VatTreatment.values:
            raise CommandError(
                f"line {line}: vat_treatment '{row.get('vat_treatment')}' is not one of "
                f"{list(OfferingPrice.VatTreatment.values)}."
            )

        return {
            "code": code,
            "name": row.get("name", "").strip(),
            "description": row.get("description", ""),
            "service_line": service_line,
            "price": self._decimal(row.get("price"), "price", line),
            "vat_treatment": treatment,
            "vat_rate_pct": self._decimal(row.get("vat_rate_pct") or "12.00", "vat_rate_pct", line),
            "turnaround_days": self._int(row.get("turnaround_days"), "turnaround_days", line),
            "is_accredited": _flag(row.get("accredited"), "accredited", line),
            "is_active": _flag(row.get("active"), "active", line, default=True),
            "test_methods": [ref.strip() for ref in (row.get("test_methods") or "").split(";") if ref.strip()],
            "note": row.get("note", "")[:255],
        }

    def _decimal(self, value, field, line):
        # Spreadsheets export "₱1,250.00" as often as "1250.00".
        text = (value or "").replace(",", "").replace("₱", "").replace("PHP", "").strip()
        if not text:
            raise CommandError(f"line {line}: {field} is required.")
        try:
            parsed = Decimal(text)
        except InvalidOperation as exc:
            raise CommandError(f"line {line}: {field} '{value}' is not a number.") from exc
        if parsed < 0:
            raise CommandError(f"line {line}: {field} cannot be negative.")
        return parsed

    def _int(self, value, field, line):
        text = (value or "").strip()
        if not text:
            return None
        if not text.isdigit():
            raise CommandError(f"line {line}: {field} '{value}' is not a whole number of days.")
        return int(text)

    # --- writing -----------------------------------------------------------

    def _upsert_offering(self, row, line):
        offering, was_created = ServiceOffering.objects.update_or_create(
            code=row["code"],
            defaults={
                "name": row["name"],
                "description": row["description"],
                "service_line": row["service_line"],
                "turnaround_days": row["turnaround_days"],
                "is_accredited": row["is_accredited"],
                "is_active": row["is_active"],
            },
        )
        if row["test_methods"]:
            offering.test_methods.set(self._resolve_methods(row["test_methods"], line))
        return offering, was_created

    def _resolve_methods(self, references, line):
        """
        A named method that does not exist is an error, not a silent
        omission: an offering mapped to five of its six methods looks
        complete and quietly under-reports the sixth everywhere it is
        counted.
        """
        methods = []
        for reference in references:
            method = (
                TestMethod.objects.filter(method_reference__iexact=reference).first()
                or TestMethod.objects.filter(name__iexact=reference).first()
            )
            if method is None:
                raise CommandError(
                    f"line {line}: no TestMethod matches '{reference}' by method_reference or name. "
                    "Create the method first, or leave test_methods blank and map it later."
                )
            methods.append(method)
        return methods
