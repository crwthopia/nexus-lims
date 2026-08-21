"""
Instrument raw-data ingestion (Blueprint Section 11).

An instrument export is uploaded against a TestRequest, stored in object
storage for ALCOA traceability (Section 7.3), and parsed into TestResult
rows that carry `raw_file_id` and `raw_file_checksum_sha256` pointing back
at the file they came from.

Parsers are looked up by `Instrument.model`, so adding vendor support is
registering a function rather than editing this module's control flow. Only
the generic CSV parser is implemented: real FESEM/EDX/TGA/XRF exports are
vendor-specific binary or semi-structured text, and writing a parser for a
format nobody has produced a sample of yields code that looks finished and
fails on first contact with the instrument. NASAT can export CSV from the
instrument software in the meantime; a vendor parser is a drop-in once real
export files exist to write it against.

The competency and out-of-spec rules live here rather than in the
serializer that used to own them, because ingestion has to apply exactly
the same ones. Two copies of "is this result out of spec" is how a lab ends
up with a manually-entered result flagged and an ingested one not.
"""

import csv
import hashlib
import io

from apps.testing.models import TestResult


class IngestionError(Exception):
    """A file that cannot be turned into results. Message is operator-facing."""


# --- Shared result rules ---------------------------------------------------

def assert_certified(user, test_method):
    """
    FR-C3-02 competency gate, applied identically to manual entry and to
    ingestion -- an analyst who may not type a result in may not upload one
    either, or the gate is decorative.
    """
    if user.is_superuser:
        return
    if not user.instrument_certifications.filter(pk=test_method.pk).exists():
        raise IngestionError(
            f"'{user.display_name}' is not certified for test method "
            f"'{test_method.name}' (FR-C3-02 competency check)."
        )


def compute_out_of_spec(test_method, data_type, value):
    """
    FR-C3-08: computed from TestMethod.specification_limits, never accepted
    from input -- neither a client's JSON nor an instrument's own opinion of
    whether it passed.
    """
    limits = test_method.specification_limits or {}
    if data_type not in (TestResult.DataType.FLOAT, TestResult.DataType.INT):
        return False
    if "min" not in limits and "max" not in limits:
        return False
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return False
    if "min" in limits and numeric_value < limits["min"]:
        return True
    if "max" in limits and numeric_value > limits["max"]:
        return True
    return False


# --- Parsers ---------------------------------------------------------------

_PARSERS = {}


def register_parser(instrument_model):
    """Registers a parser for an Instrument.InstrumentModel value."""

    def decorator(func):
        _PARSERS[instrument_model] = func
        return func

    return decorator


def parser_for(instrument):
    """
    The parser for `instrument`, falling back to the generic CSV reader.

    A fallback rather than an error because every instrument in NASAT's list
    can export CSV from its own software, so an unregistered model is a
    'no vendor parser yet' situation, not an unusable file.
    """
    if instrument is None:
        return parse_generic_csv
    return _PARSERS.get(instrument.model, parse_generic_csv)


REQUIRED_COLUMNS = {"value"}
OPTIONAL_COLUMNS = {"analyte", "unit", "data_type"}


def parse_generic_csv(content, test_method):
    """
    The documented interchange format: a header row, then one row per
    measurement.

        analyte,value,unit,data_type
        Lead,0.42,mg/L,float

    `value` is required; `unit` defaults to empty and `data_type` to float,
    which is what a numeric instrument export almost always is.

    `analyte` names the parameter each row measures, which is what makes a
    multi-analyte export usable: an ICP-MS run reporting twelve elements
    becomes twelve labelled results against one TestRequest. It stays
    optional because a single-parameter method (pH, say) has nothing to
    disambiguate -- the method name already says what was measured.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestionError(
            "File is not valid UTF-8 text. Export the instrument data as CSV "
            "rather than the instrument's native binary format."
        ) from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise IngestionError("File is empty.")

    columns = {(name or "").strip().lower() for name in reader.fieldnames}
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise IngestionError(
            f"Missing required column(s): {', '.join(sorted(missing))}. "
            f"Expected a header row with 'value' and optionally "
            f"{', '.join(sorted(OPTIONAL_COLUMNS))}."
        )

    parsed = []
    for line_number, row in enumerate(reader, start=2):  # 1 is the header
        normalised = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        value = normalised.get("value", "")
        if not value:
            raise IngestionError(f"Row {line_number}: 'value' is empty.")

        data_type = normalised.get("data_type") or TestResult.DataType.FLOAT
        if data_type not in TestResult.DataType.values:
            raise IngestionError(
                f"Row {line_number}: unknown data_type '{data_type}'. "
                f"One of: {', '.join(TestResult.DataType.values)}."
            )
        if data_type in (TestResult.DataType.FLOAT, TestResult.DataType.INT):
            try:
                float(value)
            except ValueError as exc:
                # Caught here rather than silently stored: a non-numeric
                # value in a numeric column would skip the OOS check
                # entirely and enter the record as in-spec.
                raise IngestionError(
                    f"Row {line_number}: value '{value}' is not numeric, but data_type is '{data_type}'."
                ) from exc

        parsed.append(
            {
                "analyte": normalised.get("analyte", ""),
                "data_type": data_type,
                "value": value,
                "unit": normalised.get("unit", ""),
                "is_out_of_spec": compute_out_of_spec(test_method, data_type, value),
            }
        )

    if not parsed:
        raise IngestionError("File contains a header row but no data rows.")
    return parsed


def checksum(content):
    """SHA-256 of the raw bytes, recorded per result for ALCOA traceability."""
    return hashlib.sha256(content).hexdigest()


def object_key_for(test_request, digest):
    """
    Keyed by content hash, so re-uploading an identical file is idempotent
    in storage as well as being rejected at the API layer.
    """
    return f"raw-instrument-exports/{test_request.pk}/{digest}"
