# NASAT LIMS — Instrument Export CSV Format

**Version 1 · Interchange format for instrument raw-data ingestion**

This document specifies the CSV file format the NASAT LIMS accepts as an
instrument export. It is written to be handed to an instrument vendor, an
integrator, or whoever configures the export template in the instrument's own
software.

Conform to this and the LIMS will ingest your export today, with no code
change on our side.

---

## 1. Who this is for, and the two ways in

There are two ways an instrument's data reaches the LIMS.

**A. Export CSV in this format.** Most instrument software can be configured
to write a delimited report. If yours can produce the shape described below,
nothing else is required — the file is accepted as-is. This is the supported
path and the rest of this document specifies it.

**B. We write a parser for your native format.** The LIMS has a parser
registry keyed by instrument model, so support for a vendor's own binary or
semi-structured export is a self-contained addition. We have not written any
yet, deliberately: a parser for a format we have never seen a real file of is
code that looks finished and fails on first contact with the instrument. If
you want this path, see [section 10](#10-if-you-would-rather-we-parsed-your-native-format).

---

## 2. The format at a glance

A header row, then one row per measurement.

```csv
analyte,value,unit,data_type
Lead,0.42,mg/L,float
Cadmium,0.019,mg/L,float
Mercury,0.004,mg/L,float
```

One file is uploaded against one **test request**, which is one sample tested
by one **test method**. Every row in the file is a result of that one method.
A file therefore does not name the sample, the method, the operator, or the
date — the LIMS already knows all four from the request the file is uploaded
against, and taking them from the file instead would let a mislabelled export
attach results to the wrong sample.

---

## 3. File-level requirements

| Property | Requirement |
|---|---|
| Encoding | UTF-8. A byte-order mark (BOM) is tolerated — Windows instrument software writes one often enough that rejecting it would be unhelpful. |
| Delimiter | Comma (`,`). |
| Quoting | RFC 4180. Wrap a field in `"` if it contains a comma; double an embedded quote (`""`). |
| Line endings | `LF` or `CRLF`. Both work. |
| Header row | Required. Must be the first line. |
| Blank lines | Ignored. |
| Compression / archives | Not accepted. Upload the `.csv` itself, not a `.zip`. |
| Size | No fixed limit, but the file is parsed synchronously while the analyst waits. Exports in the thousands of rows are fine; exports in the millions are not the intended use. |

A file that is not valid UTF-8 text is rejected with:

> File is not valid UTF-8 text. Export the instrument data as CSV rather than the instrument's native binary format.

---

## 4. Columns

| Column | Required | Default | Notes |
|---|---|---|---|
| `value` | **Yes** | — | The measurement. Stored as text and interpreted per `data_type`. Must not be empty. |
| `analyte` | No | `""` (empty) | The parameter this row measures. Max **255** characters. |
| `unit` | No | `""` (empty) | Unit of measure, verbatim (`mg/L`, `%`, `ppm`, `µm`). Max **32** characters. |
| `data_type` | No | `float` | One of the values in [section 5](#5-data_type-values). |

**Header names are matched case-insensitively and ignoring surrounding
whitespace.** `Analyte`, `ANALYTE`, and `  analyte  ` are all the same column.

**Columns you add that are not in this table are ignored.** If your export
template also emits `serial_number`, `operator`, `run_id`, or a timestamp,
leave them in — they will not cause a rejection. They are simply not read.
The file itself is retained in object storage exactly as uploaded, so those
extra columns remain part of the traceable record even though the LIMS does
not parse them into fields.

**Do not repeat a column name.** A duplicated header silently keeps only the
last occurrence.

### On `analyte`

`analyte` is what makes a multi-analyte export usable. An ICP-MS run
reporting twelve elements becomes twelve *labelled* results against one test
request; without the column it becomes twelve unlabelled numbers.

Leave it out entirely for a single-parameter method — pH, moisture content,
a single thickness measurement — where the method name already says what was
measured and there is nothing to disambiguate.

---

## 5. `data_type` values

| Value | Meaning |
|---|---|
| `float` | Decimal number. **The default**, and what a numeric instrument export almost always is. |
| `int` | Whole number. |
| `text` | Free text. |
| `date` | A date. |
| `boolean` | True/false. |
| `list` | A selection from a controlled list. |
| `interval` | A range or duration. |
| `calculated` | A value derived from other results. |
| `file` | A reference to an attached file. |

For `float` and `int`, the value **must parse as a number**. A non-numeric
value in a numeric column is rejected rather than stored, because storing it
would skip the out-of-spec check entirely and enter the record as in-spec.

If your instrument emits `<0.01`, `n/a`, `ND`, `--`, or `LOD` for a
non-detect, you must either send it with `data_type` of `text` (in which case
no out-of-spec check applies) or agree a numeric convention with NASAT QA
first. Do not send it as `float`.

---

## 6. Worked examples

**Single-parameter method** — no `analyte` needed, `data_type` defaults to
`float`:

```csv
value,unit
7.41,pH
```

**Multi-analyte run**, fully explicit:

```csv
analyte,value,unit,data_type
Lead,0.42,mg/L,float
Cadmium,0.019,mg/L,float
Chromium VI,0.0035,mg/L,float
```

**Mixed types, with extra vendor columns that are ignored:**

```csv
analyte,value,unit,data_type,run_id,operator
Coating thickness,1.24,µm,float,R-20260821-03,J. Cruz
Substrate,Silicon,,text,R-20260821-03,J. Cruz
Passes,3,,int,R-20260821-03,J. Cruz
```

**Quoted field containing a comma:**

```csv
analyte,value,unit
"Lead, total",0.42,mg/L
```

---

## 7. What the LIMS will not take from your file

This is the part most likely to differ from what an instrument's report
template does by default. These are deliberate.

- **Pass/fail, or any in-spec / out-of-spec flag.** The LIMS computes it
  from the test method's own specification limits, and never reads it from
  the file. An instrument's threshold can be configured on the instrument;
  the limits of record live in the LIMS. If both were trusted, the two would
  eventually disagree and the file would win. Send the measured value and
  nothing else. A column named `result`, `pass_fail`, `status`, or `verdict`
  will be ignored, not honoured.
- **Sample identity.** Taken from the test request the file is uploaded
  against.
- **The analyst.** Taken from the authenticated session.
- **The timestamp.** Recorded by the LIMS at ingestion.
- **Unit conversion.** None is performed. `unit` is stored verbatim, so send
  values in the unit the method expects.

---

## 8. Rejection rules

A rejected file returns HTTP **400** with a message naming the row. All of
these are the parser's own text, and all of them are safe to test against.

The message is under the `detail` key, except for the two cases detected
before parsing begins — a missing or empty upload — which are under `file`.

| Condition | Message |
|---|---|
| No file in the request | `No file was uploaded.` (under `file`) |
| File is zero bytes | `Uploaded file is empty.` (under `file`) |
| Not valid UTF-8 | `File is not valid UTF-8 text. Export the instrument data as CSV rather than the instrument's native binary format.` |
| No header at all | `File is empty.` |
| Header present, no data rows | `File contains a header row but no data rows.` |
| No `value` column | `Missing required column(s): value. Expected a header row with 'value' and optionally analyte, data_type, unit.` |
| Empty `value` in a row | `Row {n}: 'value' is empty.` |
| Non-numeric value in a `float`/`int` row | `Row {n}: value '{v}' is not numeric, but data_type is 'float'.` |
| Unrecognised `data_type` | `Row {n}: unknown data_type '{d}'. One of: float, int, text, date, list, file, calculated, boolean, interval.` |
| Row has more values than the header has columns | `Row {n}: {a} values for {b} columns. Every row must have the same number of fields as the header.` |
| `analyte` over 255 / `unit` over 32 characters | `Row {n}: '{column}' is longer than {limit} characters.` |

Row numbers count the header as row 1, so the first data row is **row 2** —
the same number your text editor shows.

**A trailing delimiter is tolerated.** `Lead,0.42,` under a two-column header
is accepted: the surplus field is empty, so it carries no data and is a
formatting artifact rather than a misalignment. A surplus field *with content
in it* is rejected, because when a row has more values than the header has
columns there is no way to know which value belongs to which column, and
storing a guess in a regulated record is worse than refusing the file.

**A rejected file is still stored.** The upload is written to object storage
before parsing is attempted, and stays there whether or not the parse
succeeded. Traceability wants the artifact the lab actually received,
including the one that turned out to be malformed.

---

## 9. Uploading

```
POST /api/v1/test-requests/{id}/ingest
Content-Type: multipart/form-data
```

| Field | Required | Notes |
|---|---|---|
| `file` | Yes | The CSV. |
| `instrument` | No | Numeric ID of the instrument. Selects a vendor parser if one is registered for that instrument's model, and links each result to the instrument that produced it. |

The caller must be an authenticated staff user with the **Analyst** role who
is **certified for the test method** on that request. An analyst who may not
type a result in may not upload one either.

**Responses**

- `201` — parsed. Body carries `created` (row count), `raw_file_id` (the
  object storage key), `checksum_sha256`, and the created results.
- `400` — rejected, with one of the messages in
  [section 8](#8-rejection-rules).
- `409` — **this exact file has already been ingested for this test
  request**, matched on the SHA-256 of its bytes. Re-uploading would double
  every result on the request, which in a regulated record is a
  data-integrity incident rather than a nuisance. Change the data or use a
  different test request.

Note that the duplicate check is on content, not filename. Two different runs
that happen to produce byte-identical files will collide; a re-export of the
same run under a different filename will still be caught.

---

## 10. If you would rather we parsed your native format

Registering a vendor parser is a decorator on a function, keyed by instrument
model — a contained change, not an architectural one. What we need from you
before it can be written:

1. **Real export files.** At least three, from a real run, including at least
   one multi-analyte run and, if the format has one, one containing a
   non-detect or error value. Synthetic samples reproduce the happy path and
   miss exactly the cases a parser has to get right.
2. **A format specification**, or failing that, a description of the header
   or preamble structure and how a reader is meant to find where the data
   begins.
3. **The instrument model string** as it will be configured in the LIMS
   equipment register.
4. **What the file does at the edges** — how a non-detect is written, how a
   failed measurement is written, whether units can vary between rows, and
   whether the file can contain more than one run.

Until then the generic CSV path above is fully supported, and every
instrument in NASAT's register can export to it from its own software.

---

## Reference

The format is implemented in `backend/apps/testing/ingestion.py` and its
behaviour is pinned by `backend/tests/test_instrument_ingestion.py`. Where
this document and those tests disagree, the tests are correct — please report
the discrepancy.
