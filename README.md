# NASAT LIMS Backend

A working Django/DRF backend for the NASAT Laboratory Information
Management System, built directly from the locked-in decisions in the
NASAT LIMS Blueprint (all 12 gaps in Blueprint Section 13 resolved). This
is not a schema mockup — every piece described below has been exercised
against a live PostgreSQL 18 database, a live Redis broker, a live
S3-compatible object store, and (for staff SSO) a live Microsoft Entra ID
tenant, not just imported cleanly.

Grounding: every entity, endpoint, and background task traces back to ASTM
E1578-18, ISO/IEC 17025:2017, the NASAT service list, or an explicit NASAT
architectural-review decision recorded in the Blueprint. No feature here
was invented outside that grounding.

## What's actually working, end to end

- **Data layer**: full 26-entity PostgreSQL schema, monthly-partitioned
  audit log, row-level security *forced* (not just enabled) on
  customer-visible tables, retention policy seeded per Blueprint defaults.
- **API layer**: DRF resource groups for the full sample → testing →
  review → approval → report FSM chain, with the segregation-of-duties
  guard enforced server-side, not just documented.
- **Two segregated identity domains** (Blueprint Section 2.1 item 7):
  staff via Microsoft Entra ID SSO (live-tested against a real Azure AD
  tenant), customers via a self-service email/password + optional TOTP MFA
  backend — neither can reach the other's session or role.
- **Row-level security session middleware** setting the Postgres session
  variables the RLS policies actually check, verified to produce correct
  per-customer data isolation at the database level.
- **Celery worker + beat**, running the two automations the Blueprint
  specifies (Section 7.4a retention sweep, Section 3.6/4.3 training
  capacity check), with a real S3-compatible object storage client
  (`boto3` against OSS's S3-compatible API — see Object storage below).
- **43-test automated regression suite** (`backend/tests/`, pytest +
  pytest-django + factory_boy), run against the same live Postgres/Redis/
  MinIO stack rather than mocked — see Running the test suite below.

## What is in this package

```
nasat-lims/
├── README.md                  <- this file
├── nasat_erd_core.png         <- rendered ERD: core sample-to-report workflow (12 entities)
├── nasat_erd_core.mmd         <- Mermaid source for the core-workflow ERD
├── nasat_erd_support.png      <- rendered ERD: supporting subsystems (16 entities)
├── nasat_erd_support.mmd      <- Mermaid source for the supporting-subsystems ERD
├── .claude/launch.json        <- dev-server configs (backend, celery-worker, celery-beat)
└── backend/
    ├── manage.py
    ├── requirements.txt
    ├── requirements-dev.txt       <- adds pytest, pytest-django, factory_boy
    ├── pytest.ini
    ├── .env.example
    ├── tests/                     <- see "Running the test suite" below
    ├── config/
    │   ├── settings.py        <- Postgres, Celery/Redis, OSS, Entra ID, DRF, TIME_ZONE=Asia/Manila
    │   ├── urls.py             <- /admin/, /api/v1/, /api-auth/, /oauth2/ (Entra ID SSO)
    │   └── celery.py           <- Celery app + CELERY_BEAT_SCHEDULE consumer
    └── apps/
        ├── accounts/          <- Role, StaffUser, CustomerUser, ESignature
        │   ├── authentication.py   <- CustomerSessionAuthentication (DRF)
        │   ├── customer_auth.py    <- register/verify-email/login/MFA business logic
        │   ├── customer_views.py   <- /auth/customer/* endpoints
        │   ├── history.py          <- shared django-simple-history get_user hook
        │   ├── middleware.py       <- RLSContextMiddleware
        │   ├── permissions.py      <- HasRole / roles_required(), IsCustomerAuthenticated
        │   ├── serializers.py, views.py, urls.py  <- staff-facing read endpoints
        │   └── services.py         <- e-signature capture helper
        ├── documents/         <- Document, DocumentVersion
        │   └── views.py             <- POST /document-versions/{id}/approve/ (FR-D1-03)
        ├── equipment/         <- StandardReagent, Instrument, CalibrationRecord
        │   └── views.py             <- logging a CalibrationRecord auto-syncs Instrument.status (FR-E3-02)
        ├── samples/           <- Order, Sample (FSM), ChainOfCustodyEvent
        │   └── views.py             <- FSM transition actions, review/approve/reject,
        │                               CustomerOrderViewSet/CustomerSampleViewSet ("my/orders", "my/samples")
        ├── testing/           <- TestMethod, TestRequest (FSM), TestResult
        │   └── views.py             <- FR-C3-02 competency check, FR-C3-08 OOS auto-flag
        ├── review/            <- ReviewAction, ApprovalAction
        │   └── services.py          <- segregation-of-duties guard (check_can_approve)
        ├── reporting/         <- Report (create/list/retrieve only, FR-C6-03 approved-sample guard)
        ├── investigations/    <- Investigation/CAPA
        │   └── views.py             <- POST /investigations/{id}/close/ (closed_at set atomically)
        ├── training/          <- TrainingCourse, TrainingSession (FSM), Enrollment (FSM), CreditNote
        │   ├── services.py          <- discount computation, apply_credit_note
        │   ├── views.py             <- public catalog, /my/enrollments/, /my/credit-notes/, attendee-export CSV
        │   └── tasks.py              <- Celery: check_session_capacity
        ├── billing/            <- Invoice, Payment
        │   └── views.py              <- POST /invoices/{id}/payments/ auto-transitions Invoice.status
        └── audit/              <- AuditLogEntry (partitioned), RetentionPolicy
            ├── oss.py                <- boto3 client, S3-compatible OSS/MinIO
            └── tasks.py              <- Celery: run_retention_sweep
```

Each app's `models.py` carries docstrings citing the specific Blueprint
section, ASTM E1578-18 clause, or ISO/IEC 17025:2017 clause that grounds
every non-obvious field or transition.

## Entity relationship diagrams

The full 26-entity schema was split into two diagrams for readability
rather than one dense chart:

- **`nasat_erd_core.png`** — the core sample-to-report workflow: accounts
  (StaffUser/CustomerUser), samples, testing, review, reporting, and
  investigations. This is the operational heart of the LIMS.
- **`nasat_erd_support.png`** — the supporting subsystems: RBAC roles,
  e-signatures, documents, equipment/calibration, training/enrollment, and
  billing/audit.

Open the corresponding `.mmd` file in any Mermaid-compatible renderer
(GitHub renders `.mmd`/fenced mermaid blocks natively, as does the
[Mermaid Live Editor](https://mermaid.live)) if you need to edit or
regenerate them.

Together the two diagrams cover all 26 entities across the 10 apps and
every foreign key, many-to-many, and self-referential relationship in the
schema, including:

- The **StaffUser / CustomerUser** split with no shared table and no FK
  between them (Blueprint Section 2.1 item 7: two segregated identity
  domains, Entra ID for staff vs. self-service for customers).
- The **Sample** finite-state machine, covering the full ISO 7.10
  nonconforming-work routing (`under_review` -> `rejected` ->
  `under_investigation` -> `retest_pending`).
- The **Instrument** self-referential FK (`parent_instrument`) modeling
  composite instruments such as FESEM+EDX.
- The **TrainingSession** / **Enrollment** / **CreditNote** triangle
  implementing the non-cash-refund policy (Blueprint Section 13 gap 7).

## Data layer: migrations, RLS, and partitioning

1. Models were written by hand from the Blueprint's Section 3 data model,
   Section 7 security/compliance requirements, and Section 10 repository
   scaffold — not reverse-engineered from a database.
2. `python manage.py makemigrations` generated the schema migrations for
   all 10 apps. Django's dependency resolver automatically split the
   `accounts` app into two migrations (`0001_initial`, `0002_initial`) to
   resolve the circular FK between `StaffUser.instrument_certifications`
   and `testing.TestMethod`.
3. Hand-written migrations implement decisions that aren't representable
   as plain Django `Field` declarations:
   - `accounts/migrations/0003_seed_roles.py` — seeds the 10 named RBAC
     roles (Blueprint Section 7.1).
   - `accounts/migrations/0004_customeruser_mfa_secret_and_more.py` —
     adds `CustomerUser.mfa_secret` for TOTP-based MFA.
   - `audit/migrations/0002_seed_retention_policy.py` — seeds the 5-year
     (1825-day) `archive_to_cold_storage` retention default per record
     type (Blueprint Section 13 gap 3, ISO/IEC 17025:2017 8.4.2).
   - `audit/migrations/0003_partition_audit_log_entry.py` — converts
     `audit_log_entry` into a native PostgreSQL **RANGE**-partitioned table
     by month, with a default partition and 3 months of partitions
     pre-created (Blueprint Section 2.1 item 5a).
   - `samples/migrations/0002_row_level_security.py` — enables PostgreSQL
     **row-level security** on `order` and `sample`, with a staff-bypass
     policy and a customer-scoping policy (Blueprint Section 2.1 item 3b).
   - `samples/migrations/0003_force_row_level_security.py` — closes a real
     gap in the migration above: PostgreSQL does not enforce RLS against a
     table's *owning* role unless `FORCE ROW LEVEL SECURITY` is also set,
     and the app's own DB connection role owns these tables (it's the role
     that ran `migrate`). Without this migration, `ENABLE ROW LEVEL
     SECURITY` alone was a silent no-op for every query the Django app
     itself makes — confirmed empirically, not assumed (see "Row-level
     security" below).
4. `python manage.py migrate` applies cleanly against a live PostgreSQL 18
   instance, in dependency order, no errors.
5. Verified beyond DDL: `Sample` correctly transitions through
   `pre_registered -> registered -> received -> in_prep -> in_testing ->
   under_review -> approved`, `audit_log_entry` is a genuine partitioned
   table (`pg_inherits` confirms child partitions), and `pg_policies` /
   direct queries as the app's own non-superuser role confirm RLS actually
   restricts rows (not just that the policies exist).

## API layer

DRF resource groups under `/api/v1/`, matching Blueprint Section 6. Every
app now has a full API layer — nothing left with models but no
serializers/views/urls.

| Prefix | App | Notes |
|---|---|---|
| `/roles/`, `/staff-users/`, `/customer-users/`, `/e-signatures/` | `accounts` | staff-facing, read-only |
| `/auth/customer/{register,verify-email,login,logout,me,mfa/enable,mfa/confirm}` | `accounts` | see Authentication below |
| `/orders/`, `/samples/`, `/chain-of-custody-events/` | `samples` | staff-facing, full CRUD + FSM actions |
| `/my/orders/`, `/my/samples/` | `samples` | customer-facing, read-only, scoped to the logged-in customer |
| `/test-methods/`, `/test-requests/`, `/test-results/` | `testing` | |
| `/review-actions/`, `/approval-actions/` | `review` | read-only listings; creation only via `Sample` actions above |
| `/reports/` | `reporting` | create/list/retrieve only, no edit |
| `/documents/`, `/document-versions/` | `documents` | write restricted to QA Officer/Lab Supervisor |
| `/standard-reagents/`, `/instruments/`, `/calibration-records/` | `equipment` | write restricted to Instrument Custodian/Lab Supervisor |
| `/investigations/` | `investigations` | write restricted to QA Officer/Lab Supervisor |
| `/training-courses/`, `/training-sessions/` | `training` | **public read** (no auth), write restricted to Training Coordinator/Lab Supervisor/System Administrator |
| `/enrollments/`, `/credit-notes/` | `training` | staff-facing |
| `/my/enrollments/`, `/my/credit-notes/` | `training` | customer-facing |
| `/invoices/`, `/payments/` | `billing` | write restricted to Training Coordinator/Lab Supervisor/System Administrator (no dedicated "billing" role exists in the RBAC model) |
| `/my/invoices/` | `billing` | customer-facing, read-only |

`Sample` exposes its full FSM as POST actions on `/samples/{id}/`:
`register`, `receive`, `start-prep`, `start-testing`, `submit-for-review`,
`review`, `approve`, `reject`, `authorize-retest`, `dispose`,
`requeue-for-retest`. `review`/`approve`/`reject` live here rather than as
direct `ReviewAction`/`ApprovalAction` writes specifically so there's one
write path that can move a sample through the workflow — the
segregation-of-duties guard can't be bypassed by posting a
`ReviewAction`/`ApprovalAction` directly.

**Segregation-of-duties guard** (`apps/review/services.py`,
`check_can_approve`): for `service_line == water_environmental` (a
regulated scope), the guard hard-blocks an Approver from approving a
sample they themselves reviewed. For `failure_analysis`/`training`, a
self-approve bypass is permitted. Verified live over HTTP: same user
review-then-approve on a Water/Environmental sample gets rejected with the
ASTM-cited message and the FSM state is untouched by the failed attempt; a
different, properly-`Approver`-roled user then succeeds.

**FR-C3-02 competency check** (`apps/testing/serializers.py`): entering a
`TestResult` requires the acting user to hold a certification
(`StaffUser.instrument_certifications`) for the `TestRequest`'s
`TestMethod`. **FR-C3-08 OOS auto-flag**: `is_out_of_spec` is computed
server-side from `TestMethod.specification_limits`, not accepted as client
input.

**Document approval** (FR-D1-03): `POST /document-versions/{id}/approve/`
is the only path to `is_current=True` — direct field edits can't set it.
Approving one version archives (not deletes) the prior current version of
the same `Document` and syncs `Document.current_version`.

**Calibration keeps Instrument status in sync** (FR-E3-02): logging a
`CalibrationRecord` via `POST /calibration-records/` automatically flips
the parent `Instrument.status` (`in_service` on a pass, `out_of_calibration`
otherwise) and advances `calibration_due_date` — verified live: a failing
calibration flips the instrument, a subsequent passing one flips it back.

**Investigation closing** (FR-E9-01): `status` can't be set to `closed` via
plain PATCH, only `POST /investigations/{id}/close/`, which sets
`closed_at` atomically alongside it.

**Training discounts and credit notes** (Blueprint Section 3.6): customer
self-enrollment (`POST /my/enrollments/`) computes `discount_applied`
server-side — only the student discount is actually computable
(`CustomerUser.school_id_document` eligibility); early-bird has no cutoff-date
field in the schema to compute against, so it isn't auto-applied.
`CreditNote.apply` (staff and customer variants) share one
`apps/training/services.apply_credit_note()` so the "same customer,
available status" rules can't drift between the two entry points.
`GET /training-sessions/{id}/attendee-export/` returns a real CSV;
`CustomerUser` has no name field under the current schema, so email is
used as the attendee identifier instead.

**Invoice/Payment auto-transition** (Blueprint Section 3.7): recording a
`CONFIRMED` `Payment` via `POST /invoices/{id}/payments/` flips the parent
`Invoice.status` to `paid`. `Payment` has no per-payment amount field in
the current schema, so this treats any confirmed payment as paying the
invoice in full — the same documented limitation the training-capacity
Celery task's `CreditNote` amount calculation has.

## Authentication

Two identity domains, no shared table, no FK between them (Blueprint
Section 2.1 item 7):

### Staff: Entra ID (Azure AD) SSO

`django-auth-adfs`, wired in `config/settings.py` (`AUTH_ADFS`) and
`config/urls.py` (`/oauth2/login`, `/oauth2/callback`, `/oauth2/logout`).
Live-tested against a real Azure AD tenant end to end: `/oauth2/login`
redirects to a real `login.microsoftonline.com` authorize URL, and a real
Microsoft sign-in produced a correctly-populated `StaffUser` (`email` from
the `upn` claim, `entra_oid` from `oid`, `display_name` from `name`,
unusable local password) with a normal Django session afterward.

Two real bugs were found and fixed getting here, both still documented in
`config/settings.py`: the library's default `CLAIM_MAPPING` (auto-set when
`TENANT_ID` is configured) references `first_name`/`last_name` fields
`StaffUser` doesn't have, and separately conflicts with `USERNAME_FIELD =
"email"` — both required an explicit `CLAIM_MAPPING` override. Local
password auth (`ModelBackend`) is also still enabled, for
`createsuperuser`/local-dev accounts — `StaffUserManager.create_user` only
sets a real password when one is explicitly passed, otherwise the account
is SSO-only.

### Customers: self-service email/password + optional MFA

`apps/accounts/customer_auth.py` + `customer_views.py`. Not built on
Django's `AUTH_USER_MODEL`/`authenticate()`/`login()` machinery at all —
`CustomerUser` is a plain model, and identity lives in
`request.session["customer_user_id"]`, read back by
`CustomerSessionAuthentication` (`apps/accounts/authentication.py`) on
customer-facing views only. A customer session cannot authenticate against
staff-only endpoints; verified live (same browser session, same cookie
jar: `/auth/customer/me` returns 200, `/api/v1/samples/` returns 403).

- **Register** → email verification token (`django.core.signing`,
  since there's no password/last_login to hash into a token the way
  Django's built-in generator does) sent via `EMAIL_BACKEND` (console
  backend in dev — prints to the runserver log; swap for real SMTP/Alibaba
  DirectMail in production).
- **Login** requires `is_email_verified`, and an `mfa_code` if
  `mfa_enabled` (TOTP via `pyotp`, RFC 6238).
- **MFA enrollment** is two steps: `POST /auth/customer/mfa/enable`
  generates and stores a secret (unconfirmed), `POST
  /auth/customer/mfa/confirm` activates it once a real code round-trips
  correctly — verified with `pyotp`-generated codes against a real stored
  secret, not just that the endpoints return 200.

A real bug surfaced and was fixed while wiring this in: `django-simple-history`'s
default `get_user` hook hands `request.user` straight to a FK hard-typed to
`StaffUser`, with no type check — a customer-authenticated request (where
`request.user` is a `CustomerUser`) raised `ValueError` on *any* write to a
history-tracked model. Fixed once, centrally, in
`apps/accounts/history.py` (`get_history_user`), applied to every
`HistoricalRecords()` declaration across all 10 apps.

## Row-level security

`apps/accounts/middleware.py` (`RLSContextMiddleware`) sets
`rls.is_staff`/`rls.customer_id` Postgres session variables on every
request, which the RLS policies on `order`/`sample` check via
`current_setting(...)`. Key design points, documented in the file:

- `set_config(..., is_local=false)` (connection-scoped), not `true`
  (transaction-scoped) — Django's default autocommit-per-statement
  behavior would reset a transaction-scoped value before the view's own
  queries even ran.
- `rls.customer_id` defaults to `'0'` (a sentinel), not `''` — an empty
  string makes `current_setting(...)::bigint` raise and take down every
  `order`/`sample` query for the request, staff included.
- Customer identity is read straight from `request.session`, not
  `request.user` — customer identity only resolves to `request.user`
  later, inside DRF's per-view authentication, which runs *after* this
  middleware.

Verified directly against Postgres, not just via HTTP status codes: as the
app's own (non-superuser) DB role, zero RLS context returns zero rows;
`rls.is_staff='true'` returns everything; two customers seeded with their
own `Order`+`Sample` each see only their own row, with zero cross-visibility.

## Async tasks: Celery + object storage

Two Celery beat tasks (Blueprint Section 7.4a, Section 3.6/4.3), both
verified by actually dispatching them through a real worker against real
data, not just unit-testing the functions in isolation:

- **`apps.audit.tasks.run_retention_sweep`** (daily, 02:00) — sweeps all 5
  `RetentionPolicy` record types, applies
  `archive_to_cold_storage`/`lock_record`/`anonymize`. Idempotent via the
  existing `AuditLogEntry` ledger (a `field_changed="retention_locked"`
  row *is* the lock flag any future write-guard can query — no separate
  table needed).
- **`apps.training.tasks.check_session_capacity`** (daily, 03:00) — flags
  under-capacity `TrainingSession`s to `pending_reschedule`, reschedules
  enrollments, issues `CreditNote`s only where money was actually paid
  (per-`Invoice`, since `Payment` has no per-payment amount field in the
  current schema), sends notification emails.

### Object storage (`apps/audit/oss.py`)

`archive_to_cold_storage` talks to real S3-compatible object storage via
`boto3`, not Alibaba's own `oss2` SDK — specifically because OSS documents
an S3-compatible mode, so the *same client code* runs against a real
Alibaba OSS bucket in production and a local [MinIO](https://min.io/)
instance in dev (just an `OSS_ENDPOINT`/credential swap). `oss2` uses
Alibaba's own request-signing scheme and can't target anything
non-Alibaba, which would make this untestable without a live Alibaba Cloud
account.

Verified against a real local MinIO bucket: uploaded a real object,
zeroed a retention window, dispatched the task, and confirmed via
`head_object` that the object's storage class *actually changed* in
MinIO — not just that an audit row got written. A real bug came out of
this: `StorageClass="STANDARD_IA"` (the standard AWS/boto3 enum value) is
rejected outright by MinIO's default config (`InvalidStorageClass`), which
only recognizes `STANDARD`/`REDUCED_REDUNDANCY`. Made configurable
(`OSS_ARCHIVE_STORAGE_CLASS`) rather than hardcoding a second unverified
guess, since what real Alibaba OSS's S3-compatible surface accepts hasn't
been confirmed against a live account either.

If OSS is unreachable/unconfigured or the call fails unexpectedly, the
record is **not** marked processed, so the next daily sweep retries it
rather than silently losing the archival action.

## Running it yourself

### Prerequisites

- **PostgreSQL** (18 used in dev) — the app database.
- **Redis** — Celery broker/result backend.
- **An S3-compatible object store** — a local [MinIO](https://min.io/)
  server works for dev (`minio.exe server <data-dir> --console-address
  ":9001"`); real Alibaba Cloud OSS in production.
- **An Entra ID (Azure AD) App Registration**, if you want staff SSO to
  actually work — single tenant, Web platform redirect URI
  `http://localhost:8000/oauth2/callback`. The app **will not boot**
  without `AZURE_AD_TENANT_ID`/`AZURE_AD_CLIENT_ID`/`AZURE_AD_CLIENT_SECRET`
  set to *something* (django-auth-adfs validates required settings at
  import time), even if you don't plan to use SSO locally — put in
  syntactically-valid placeholder values if you just need the app to run.

### Setup

```bash
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\python.exe
pip install -r requirements.txt

cp .env.example .env
# edit .env: real Postgres credentials, OSS_ACCESS_KEY_ID/SECRET pointed at
# your MinIO (or real OSS) instance, and the AZURE_AD_* values above

# create the database (adjust for your Postgres setup):
createdb nasat_lims

python manage.py migrate
python manage.py createsuperuser --username admin --email admin@nasatlabs.test
python manage.py runserver
```

`.env` is actually loaded (via `python-dotenv` in `config/settings.py`) —
worth calling out because it silently wasn't, for a while, earlier in this
project's history.

### Running the Celery worker and beat scheduler

From `backend/`, in two separate terminals:

```bash
# Worker: --pool=solo is required on Windows (the default "prefork" pool
# needs os.fork(), which Windows doesn't have).
celery -A config worker --pool=solo -l info

# Beat: dispatches run_retention_sweep daily at 02:00 and
# check_session_capacity daily at 03:00 (config/settings.py CELERY_BEAT_SCHEDULE).
celery -A config beat -l info
```

If you're using Claude Code, `.claude/launch.json` already defines
`celery-worker` and `celery-beat` alongside `backend`, invoked from the repo
root via Celery's `--workdir backend` flag rather than `cd backend` first
(the launch config has no working-directory field of its own) — start them
with the preview tool the same way as the Django server.

To dispatch a task immediately rather than waiting for its schedule (e.g.
to sanity-check the worker is picking things up):

```bash
python manage.py shell -c "from apps.audit.tasks import run_retention_sweep; print(run_retention_sweep.delay().get(timeout=20))"
```

## Running the test suite

`backend/tests/` (pytest + pytest-django + factory_boy) covers the
behaviors this README calls "verified live" above, run for real against a
live Postgres/Redis/MinIO stack (a real `test_nasat_lims` database, created
and migrated by pytest-django) rather than mocked — consistent with how
everything else in this project has been verified:

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

43 tests, organized by behavior rather than by app:

| File | Covers |
|---|---|
| `test_sample_fsm.py` | `Sample` FSM transitions end to end, illegal-transition 400s, per-action role gates |
| `test_segregation_of_duties.py` | `check_can_approve`: regulated (Water/Environmental) hard split vs. Failure Analysis self-approve bypass |
| `test_row_level_security.py` | Customer order/sample isolation through the real API *and* directly against the DB connection (bypassing the ORM's own filtering) — proves the Postgres policy itself enforces the boundary |
| `test_customer_auth.py` | Register → verify-email → login, generic invalid-credentials error, TOTP MFA enroll/confirm/login |
| `test_auth_domain_isolation.py` | Customer session can't reach staff endpoints and vice versa; a customer-authenticated write doesn't crash `django-simple-history` |
| `test_testing_competency_and_oos.py` | FR-C3-02 competency gate, FR-C3-08 server-computed OOS flag, expired-reagent rejection |
| `test_documents.py` | FR-D1-03 version approval archives the prior current version and syncs `Document.current_version` |
| `test_equipment_calibration.py` | FR-E3-02: a calibration result flips `Instrument.status` and advances `calibration_due_date` |
| `test_investigations.py` | FR-E9-01: `close` is the only path to `closed`, sets `closed_at` atomically, can't double-close |
| `test_training.py` | Discount computation, `CreditNote.apply` validation, the `check_session_capacity` Celery task (called directly, not via a broker) |
| `test_billing.py` | A confirmed `Payment` auto-transitions its `Invoice` to `paid`; a pending one doesn't |
| `test_audit_retention.py` | `run_retention_sweep` idempotency via the `AuditLogEntry` ledger, and the real boto3-against-MinIO archive path |

Two non-obvious fixtures in `tests/conftest.py` are worth knowing about
before adding more tests:

- **Staff login uses `client.force_login(user, backend=...)`, never DRF's
  `force_authenticate`.** `force_authenticate` only patches the DRF-wrapped
  `Request` seen inside the view; `RLSContextMiddleware` reads the plain
  Django `request.user` *before* DRF ever wraps it, so `force_authenticate`
  would silently defeat the RLS staff-bypass policy. `force_login` drives a
  real session through `AuthenticationMiddleware`, same as a real
  Entra ID-authenticated request.
- **`_rls_staff_bypass_for_fixture_setup` (autouse)** defaults every test's
  DB connection to the RLS staff-bypass policy, because `order`/`sample`
  carry `FORCE ROW LEVEL SECURITY` and factory setup writes directly via the
  ORM outside of any HTTP request (so `RLSContextMiddleware` never runs to
  set the session variables the policies check). Without it, an ordinary
  `OrderFactory()` call in test setup is rejected by Postgres itself.
  `test_row_level_security.py` overrides this explicitly to test the real
  policy; any actual API request in any other test overwrites it via the
  middleware regardless.
- **Use `tests/helpers.reload(instance)`, not `instance.refresh_from_db()`,
  for models with a `django-fsm` `protected=True` field** (`Sample`,
  `TestRequest`, `TrainingSession`, `Enrollment`). None of them mix in
  `django_fsm.FSMModelMixin` (which teaches `refresh_from_db` to skip
  protected fields), so calling it directly raises `AttributeError: Direct
  status modification is not allowed` — a real, currently-latent footgun in
  the models themselves, not just a test artifact.

Not covered yet: Entra ID SSO (needs a live Azure AD tenant, per the
Authentication section above), report PDF generation and instrument
file-parsing (neither is built — see Known gaps below), and the two Celery
beat schedule entries themselves (the task *logic* is tested directly;
`CELERY_BEAT_SCHEDULE`'s cron wiring isn't).

## Known gaps / next steps

Genuinely not built yet, not just undocumented:

- **No frontend.** Staff Console and Customer Portal (Blueprint Section
  2.1 item 1, React/TypeScript) don't exist — this is API-only. `/` and
  `/admin/` are the only browsable entry points.
- **No report PDF generation.** `Report` is metadata + an OSS object key
  (`file_id`) supplied by the caller; the decoupled WeasyPrint/Jinja2
  rendering pipeline described in Blueprint Section 2.1a hasn't been
  built. Nothing currently produces the PDF `file_id` is supposed to
  point at.
- **No instrument file-parsing / raw-data ingestion.** `TestResult`
  references a raw file key but nothing parses instrument export files
  into results automatically (Blueprint Section 11).
- **`/my/orders/` and `/my/samples/` are still read-only.** Customers can
  self-enroll in training (`POST /my/enrollments/`) and apply their own
  credit notes, but there's no customer-initiated *order* creation yet —
  walk-in/staff-initiated intake is still the only path onto a `Sample`.
- **No CI/CD, no IaC.** No GitHub Actions workflows, no Terraform for the
  Alibaba Cloud resources described in Blueprint Section 2.2 — this all
  runs from a local dev environment only.
- **Real Alibaba Cloud OSS is unverified.** The object storage
  integration is proven against local MinIO; whether Alibaba's actual
  S3-compatible surface accepts the same storage-class values, auth
  flow, etc. has not been confirmed against a live account.
- **Real SMTP is unverified.** `EMAIL_BACKEND` is the console backend;
  verification/MFA emails print to the server log rather than sending.
- **No Odoo ERP integration** — explicitly out of scope for this phase
  per the Blueprint.
- **Retention `anonymize` action is a documented no-op.** None of the 5
  `RetentionPolicy` record types carry PII fields directly on themselves
  under the current schema (it lives on `CustomerUser`); see
  `apps/audit/tasks.py`.
