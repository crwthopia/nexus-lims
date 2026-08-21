# NASAT LIMS

A working Django/DRF backend, plus both React/TypeScript frontends the
Blueprint calls for — a Staff Console and a Customer Portal — for the
NASAT Laboratory Information Management System, built directly from the
locked-in decisions in the NASAT LIMS Blueprint (all 12 gaps in Blueprint
Section 13 resolved). This is not a schema mockup — every piece described
below has been exercised against a live PostgreSQL 18 database, a live
Redis broker, a live S3-compatible object store, and (for staff SSO) a
live Microsoft Entra ID tenant, not just imported cleanly.

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
- **217-test automated regression suite** (`backend/tests/`, pytest +
  pytest-django + factory_boy), run against the same live Postgres/Redis/
  MinIO stack rather than mocked — see Running the test suite below.
- **CI on every pull request** (`.github/workflows/ci.yml`): the backend
  suite against live Postgres/Redis/MinIO service containers, plus lint,
  tests, typecheck, and production build for both frontends — see
  Continuous integration below.
- **200-test frontend suite** (Vitest + React Testing Library): 150 in the
  Staff Console and 50 in the Customer Portal — every screen on either side
  with a server-side rule behind it — covering role gating, the route
  guards, the Sample and TrainingSession FSM action sets, payment
  reconciliation, FR-E3-02 calibration, FR-D1-03 version approval,
  FR-E9-01 investigation closure, the Reports screen, the customer report
  download flow, TOTP MFA enrollment, and credit-note redemption — see
  Frontend test suites below.
- **Staff Console frontend** (`frontend/`,
  React + TypeScript + Vite, Blueprint Section 2.1 item 1): real Entra ID
  SSO login through Django, a live samples worklist with the full Sample
  FSM action set (register → receive → prep → testing → review →
  approve/reject → …), a Review Queue with segregation-of-duties
  awareness, a Testing Queue with results entry (competency check, OOS
  flagging), a Documents screen (version history, FR-D1-03 approval),
  Investigations/CAPA tracking (FR-E9-01), an Equipment screen
  (instruments, standard reagents, calibration logging with FR-E3-02
  status sync), Training (courses, sessions, credit notes, attendee
  export), and Billing (invoices, manual payment reconciliation) — all
  driven against the real API, not a mockup, see "Staff Console" below.
  Reports (generate from an approved sample, live generation status,
  presigned download). Every staff-facing resource group in the
  Blueprint's API now has a screen.
- **Customer Portal frontend** (`customer-portal/`, React + TypeScript +
  Vite, Blueprint Section 2.1 item 1's second frontend): register → verify
  email → login with optional TOTP MFA, My Orders/My Samples (RLS-scoped
  read-only), a public Training catalog with self-enrollment, My
  Enrollments, My Credit Notes (redeem to a future session), My Invoices,
  My Reports (download your own COA via a presigned URL), and an Account
  page with MFA enrollment — see "Customer Portal" below.
  Needed **zero backend changes** to build; every endpoint it uses already
  existed and was already tested.

## What is in this package

```
nasat-lims/
├── README.md                  <- this file
├── nasat_erd_core.png         <- rendered ERD: core sample-to-report workflow (12 entities)
├── nasat_erd_core.mmd         <- Mermaid source for the core-workflow ERD
├── nasat_erd_support.png      <- rendered ERD: supporting subsystems (16 entities)
├── nasat_erd_support.mmd      <- Mermaid source for the supporting-subsystems ERD
├── .github/workflows/ci.yml   <- CI: backend pytest (live Postgres/Redis/MinIO), infra terraform validate, both frontends' lint/test/typecheck/build
├── docs/                      <- external-facing specs
│   └── instrument-export-csv.md <- the instrument export CSV format, written to hand to a vendor
├── infra/                     <- Terraform for Blueprint Section 2.2 (VPC, OSS, RDS, Redis) -- never applied, see infra/README.md
├── .claude/launch.json        <- dev-server configs (backend, celery-worker, celery-beat, frontend, customer-portal)
├── frontend/                   <- Staff Console (React + TypeScript + Vite) -- see "Staff Console" below
│   ├── vite.config.ts          <- dev server on :5174, proxies /api,/admin,/static to Django on :8000
│   └── src/
│       ├── api/                <- client.ts (fetch wrapper), types.ts, queries.ts (React Query hooks)
│       ├── auth/AuthContext.tsx <- staff-me query, login/logout, hasRole()
│       ├── components/         <- Layout, ProtectedRoute, StatusBadge
│       ├── test/                <- Vitest setup + stubApi/renderWithProviders helpers
│       └── pages/               <- Login, SamplesList, SampleDetail, ReviewQueue,
│                                    TestingQueue, TestRequestDetail,
│                                    DocumentsList, DocumentDetail,
│                                    InvestigationsList, InvestigationDetail,
│                                    EquipmentList, InstrumentDetail,
│                                    TrainingList, TrainingSessionDetail,
│                                    BillingList, InvoiceDetail, ReportsList
├── customer-portal/            <- Customer Portal (React + TypeScript + Vite) -- see "Customer Portal" below
│   ├── vite.config.ts          <- dev server on :5173, proxies /api to Django on :8000
│   └── src/
│       ├── api/                <- client.ts, auth.ts (register/login/MFA calls), types.ts, queries.ts
│       ├── auth/AuthContext.tsx <- customer-me query, logout
│       ├── components/         <- Layout, ProtectedRoute
│       ├── test/                <- Vitest setup + helpers (own copy, not shared)
│       └── pages/               <- Register, VerifyEmail, Login, Orders, Samples,
│                                    TrainingCatalog, MyEnrollments, MyCreditNotes,
│                                    MyInvoices, MyReports, Account
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
        ├── common/            <- cross-app helpers with no models of their own
        │   └── params.py           <- int_param/str_param/body_dict: client input coerced to a 400, never a 500
        ├── documents/         <- Document, DocumentVersion
        │   └── views.py             <- POST /document-versions/{id}/approve/ (FR-D1-03)
        ├── equipment/         <- StandardReagent, Instrument, CalibrationRecord
        │   └── views.py             <- logging a CalibrationRecord auto-syncs Instrument.status (FR-E3-02)
        ├── samples/           <- Order, Sample (FSM), ChainOfCustodyEvent
        │   └── views.py             <- FSM transition actions, review/approve/reject,
        │                               CustomerOrderViewSet/CustomerSampleViewSet ("my/orders", "my/samples")
        ├── testing/           <- TestMethod, TestRequest (FSM), TestResult
        │   └── ingestion.py         <- parser registry + generic CSV; shared competency/OOS rules
        │   └── views.py             <- FR-C3-02 competency check, FR-C3-08 OOS auto-flag
        ├── review/            <- ReviewAction, ApprovalAction
        │   └── services.py          <- segregation-of-duties guard (check_can_approve)
        ├── reporting/         <- Report (create/list/retrieve only, FR-C6-03 approved-sample guard)
        │   ├── rendering.py         <- Jinja2 env for report templates (StrictUndefined, autoescape)
        │   ├── tasks.py             <- Celery: generate_report_pdf (WeasyPrint -> OSS)
        │   └── templates/reports/   <- report layouts; currently DRAFT placeholders pending QA
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

## FSM state machines

Four models carry a guarded state machine rather than a plain status
column: `Sample`, `TestRequest` (Blueprint Section 2.1 item 3a),
`TrainingSession`, and `Enrollment`. Each declares an
`FSMField(protected=True)` plus `@transition`-decorated methods, so an
illegal transition raises at the *model* layer no matter which endpoint,
admin action, or shell session attempts it — the API's 400 responses are a
translation of that model-layer refusal (`TransitionNotAllowed`), not an
independent check that could drift from it.

The library is **`django-fsm-2`** (MIT, maintained under the
[django-commons](https://github.com/django-commons/django-fsm-2)
organization), not the original `django-fsm`, which was abandoned at 3.0.1
and emits an import-time `UserWarning` on every management command and test
run. The fork keeps the `django_fsm` module name and public API, so this is
a requirements-file change only: imports, the `django_fsm.FSMField`
deconstruct paths recorded in the existing migrations, and MIT licensing
all carry over unchanged, and `makemigrations --check` reports no schema
drift.

That deprecation warning points at `viewflow.fsm` as the successor, which
this project deliberately did **not** adopt, for two reasons:

- **Licensing.** `django-viewflow` is AGPL-3.0-or-later. Its own
  `viewflow/fsm/__init__.py` header describes a dual AGPL/commercial
  arrangement, but the published wheel ships only the AGPL text — no
  exception or commercial-license file. AGPL's network-use clause is
  squarely aimed at software users interact with remotely, which is exactly
  what the Customer Portal makes this.
- **It would reintroduce a bug this project already fixed.**
  `viewflow.fsm` has no `FSMModelMixin`; its own `FSMField` docstring notes
  that `protected=True` blocks `refresh_from_db()` and that there is "no
  workaround for that yet". That is precisely the `AttributeError` the test
  suite surfaced on all four of these models, and
  `test_fsm_refresh_from_db.py` exists to keep it fixed (see Running the
  test suite below). Adopting `viewflow.fsm` would mean either dropping
  `protected=True` — the whole point of the field — or accepting the broken
  `refresh_from_db()` again.

`viewflow.fsm` is otherwise a reasonable target: it *does* ship a
backward-compatible `FSMField` and a django-fsm-shaped `@transition`
decorator, so if the licensing question is ever settled the port is small.
The `FSMModelMixin` gap would still need an answer.

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

## Theme

Both frontends run a dark theme matched to the **NexusCRM Enterprise**
console, so the two products read as one suite. It lives entirely in the
`:root` custom properties at the top of each app's `src/index.css` — the two
blocks are identical, and are the only place colour is defined. There are no
hardcoded colours left in any component. That last point is what made adding
a second theme cheap: a light palette is a second block of the same tokens,
not a sweep through the components.

**A light theme ships alongside it, opt-in.** Dark stays the default,
because the palette was matched to a sibling product on purpose and
following the operating system instead would split that identity across
whichever machine a user happened to log in from. A toggle in both headers
sets `data-theme` on the root element and remembers the choice per browser;
`src/theme.ts` owns reading and writing it. Making it follow the OS instead
is a one-block change, described in the comment above the light palette.

Two details in there are load-bearing:

- **The preference is applied by an inline script in `index.html`, before
  first paint.** Setting `data-theme` from React would paint the dark
  default and then swap, flashing on every load for anyone who chose light.
  That script necessarily duplicates the storage key and the default from
  `theme.ts`, so `themeBootstrap.test.tsx` asserts the two agree — if the
  key drifts nothing throws, the toggle simply appears to forget the choice
  on refresh, which looks like a React state bug and is not.
- **Every read and write of `localStorage` is wrapped.** Private browsing
  and "block site data" throw on *access* rather than returning `null`. A
  theme is a convenience; failing to read one must never be why a lab
  technician sees a blank screen.

Colours were **measured, not eyeballed.** Every value carries its WCAG
contrast ratio as a comment, against the surface it is actually used on;
nothing is below AA (4.5:1) for text, and most pairs clear AAA. Three
consequences worth knowing before changing a token:

- **Some accents need two tokens, not one.** A blue light enough to read as
  link text on a near-black surface is too light to carry a white button
  label. Hence `--color-primary` (fill, white label at 4.76:1) versus
  `--color-accent` (links and active nav, 6.75:1 on a card), and
  `--color-danger` (error text, 7.93:1 — used in 47 places) versus
  `--color-danger-fill` (destructive button, white label at 5.42:1). Setting
  one where the other belongs looks fine and fails contrast.
- **Hover lifts, it doesn't sink.** The light theme used `--color-bg` as the
  hover background on cards and table rows, which worked because the canvas
  was *darker* than a white surface. Inverted, that reads as a pressed
  state, so hovers use `--color-surface-hover`, which sits above the surface.
- **Form controls get `--color-border-strong` (3.27:1), not the hairline
  `--color-border` (1.22:1).** A control's border is the only thing marking
  its extent, which WCAG 1.4.11 asks 3:1 of. The hairline is correct for
  separators between surfaces and wrong for an input.

Disabled buttons use a muted fill rather than `opacity: 0.5`, which on a
near-black canvas drops a white label to roughly 2.5:1. WCAG exempts
inactive controls, but the Sample Actions panel deliberately shows
transitions you *can't* perform with the reason in the tooltip, so those
labels have to stay readable.

`components/StatusBadge.tsx` maps each of the 11 `Sample` statuses to a
token pair rather than a literal. The mapping is deliberately many-to-one:
statuses that mean the same thing to a reviewer share a colour, so a
worklist reads as four groups (waiting / in progress / accepted / rejected)
rather than eleven unrelated hues, and `disposed` is muted rather than red
because it is terminal bookkeeping, not a failure.

## Staff Console (React frontend)

`frontend/` (Blueprint Section 2.1 item 1): Vite + React + TypeScript,
React Router, and TanStack Query. Session-cookie auth against the same
Entra ID SSO flow the backend already had — not the MSAL.js
Bearer-token-in-the-browser pattern the API layer's doc comment on
`AdfsAccessTokenAuthentication` anticipates, and that's a deliberate
choice, not an oversight: MSAL.js needs the Azure App Registration to also
expose a "Single-page application" platform redirect (public client, PKCE),
which is an Azure Portal change outside this repo's control. Reusing the
already-live-tested `/oauth2/login` server-side flow needed zero Azure
changes and works today; switching to MSAL.js is a real option later if
NASAT wants the SPA fully decoupled from the Django host.

**Running it**: `cd frontend && npm install && npm run dev` (or the
`frontend` entry in `.claude/launch.json`), alongside the backend on
`:8000`. The dev server listens on `:5174` and proxies `/api`, `/admin`,
and `/static` to `:8000` (`vite.config.ts`), so the browser only ever talks
to one origin and the Django session cookie works with zero CORS setup.

**Login flow**, and why it needs one extra hop: clicking "Log in with
Microsoft" is a real full-page navigation to
`http://localhost:8000/oauth2/login?next=/staff/login-complete/` — Entra ID
SSO can't happen inside a fetch(). `next=` is `django-auth-adfs`'s own
post-login redirect mechanism, but it only allows redirecting within the
*same host:port* the login started on (`url_has_allowed_host_and_scheme`
checks against `request.get_host()`), so it can't send the browser from
Django's port straight back to Vite's port on its own. `StaffLoginCompleteView`
(`apps/accounts/views.py`) closes that gap: `next=` points at it (same-origin,
passes the safety check), and it issues a real `HttpResponseRedirect` to
`settings.STAFF_CONSOLE_BASE_URL` — an app-controlled setting, not
user input, so there's no open-redirect risk in trusting it. The session
cookie set during the Entra ID callback carries over regardless of the
port hop, since cookie scoping is host-based, not port-based.

**Two other real bugs surfaced building this**, both fixed in the backend:
- `GET /auth/staff/me` and `POST /auth/staff/logout` (`apps/accounts/views.py`
  `StaffMeView`/`StaffLogoutView`) didn't exist before — `StaffUserViewSet`
  is a paginated listing of *every* staff user, not scoped to the caller, so
  there was previously no way for a client to ask "who am I / what roles do
  I hold," which the console needs on every page load to render role-gated
  actions (`SampleViewSet._ROLE_MAP`, mirrored client-side in
  `frontend/src/api/types.ts SAMPLE_ACTION_ROLES` — kept in sync by hand,
  no codegen yet). `StaffLogoutView` clears only the Django session, not the
  Entra ID/Microsoft SSO session — deliberately separate from
  `/oauth2/logout`, which this version of `django-auth-adfs` can't be told
  a post-logout redirect for, so following it would strand the browser on a
  bare Microsoft page with no way back to the console.
- Every state-changing request from the SPA (e.g. a Sample FSM action)
  failed with `CSRF Failed: Origin checking failed`, even though the
  session/CSRF cookies themselves were flowing correctly through the proxy.
  Django 4+'s `CsrfViewMiddleware` checks the browser's real `Origin` header
  (`http://localhost:5174`) against `request.get_host()`, and Vite's proxy
  doesn't make that match — confirmed live via the browser preview, not
  just reasoned about. Fixed with `CSRF_TRUSTED_ORIGINS`
  (`config/settings.py`).

**Verified live** (browser preview, not just unit tests): logged in via a
local password-auth account (real Entra ID SSO needs a live Microsoft
sign-in this environment can't complete non-interactively), loaded the real
samples worklist from Postgres, opened a sample, ran `register` then
`receive` through the actual FSM actions — status and the chain-of-custody
timeline updated from real API responses each time — and logged out
correctly.

**Review Queue** (`frontend/src/pages/ReviewQueue.tsx`): a worklist of
samples in `under_review`, for Reviewer/Approver/QA Officer/Lab Supervisor,
flagging `water_environmental` as a regulated service line. The Sample
detail page's Actions panel now shows the full review/approval history
(`GET /review-actions/?sample=` and `/approval-actions/?sample=`, both
already-existing read-only endpoints, apps/review/views.py) and disables
Approve client-side — with the same ASTM E1578-18 6.6.1 message the server
gives — when the current user already reviewed a regulated sample
themselves, mirroring `apps.review.services.check_can_approve` as defense
in depth rather than letting the click round-trip to a 400.

A real bug surfaced building the queue: `SampleViewSet` had no
`get_queryset()` override, so `?status=`/`?service_line=` were silently
ignored by DRF (it doesn't error on unrecognized query params) — every
Samples-list request returned everything regardless of the filter
dropdown, a bug that predates this feature but only became obvious once
the queue's filtering had to actually work. Fixed in
`apps/samples/views.py`, regression-tested in
`backend/tests/test_sample_filters.py`. Verified live end to end: opened a
pre-reviewed regulated sample and confirmed Approve was disabled, recorded
a review and approved a non-regulated sample through the UI, and rejected
the regulated one into `under_investigation`.

**Testing Queue / results entry** (`frontend/src/pages/TestingQueue.tsx`,
`TestRequestDetail.tsx`): a worklist of `TestRequest`s in
`assigned`/`in_progress`, and a detail screen showing the `TestMethod`'s
specification limits, existing results (with the OOS badge), a
result-entry form (data type, value, unit, instrument, standard
reagents), and the full `TestRequest` FSM action set. A client-side "not
certified" banner mirrors the server-side FR-C3-02 competency check
(`TestResultSerializer.validate`) — same defense-in-depth reasoning as the
Review Queue's segregation-of-duties hint. Sample detail now also lists
its test requests, linking into this screen.

Same class of filtering bug as `SampleViewSet` had, found the same way:
`TestRequestViewSet` had no `get_queryset()` override either, so
`?sample=`/`?status=` (comma-separated, e.g. `assigned,in_progress` for
the queue) did nothing server-side. Fixed in `apps/testing/views.py`,
regression-tested in `backend/tests/test_test_request_filters.py`.
`TestRequestSerializer`/`TestResultSerializer` also gained read-only
display fields (`sample_code`, `test_method_name`,
`assigned_analyst_display_name`, `entered_by_display_name`) matching the
convention already used elsewhere (e.g. `approver_display_name`) — a
list/detail UI would otherwise only see bare FK ids.

Verified live end to end: entered an in-spec and an out-of-spec result on
a certified test method (the OOS badge rendered correctly for the
out-of-spec one), ran `start`/`submit-for-review` through the real FSM,
and confirmed the Sample detail panel picked up the status change. Also
confirmed the "not certified" warning renders for an uncertified method —
and separately confirmed, by deliberately testing with a superuser
account, that the one case where an uncertified result *did* save anyway
is the competency check's own documented superuser bypass
(`apps/testing/serializers.py`, same "System Administrator escape hatch"
pattern as `HasRole`), not a bug in this feature.

**Documents** (`frontend/src/pages/DocumentsList.tsx`,
`DocumentDetail.tsx`, Blueprint Section 3.5, D-1): browse/create
`Document`s, and per-document version history with an "add a new
version" form and per-version Approve (FR-D1-03). Read access is open to
any authenticated staff member per the backend, so unlike the Review/
Testing queues this nav link and page are always visible — only the
create/add-version/approve forms are conditionally rendered, gated to
QA Officer/Lab Supervisor (`DOCUMENT_WRITE_ROLES`).

No new query-param filtering gap this time — `DocumentVersionViewSet`
already supported `?document=` before this feature, unlike the two
screens before it. One small serializer addition:
`DocumentSerializer.current_version_number` (read-only, `source=
current_version.version_number`), matching the display-field convention
used everywhere else — the list view would otherwise only see
`current_version`'s bare FK id. Verified live end to end: created a
document, added a version, approved it (the version's "Current" badge
and the list's `current_version_number` both updated), and confirmed the
suggested next version number advances after each add.

**Investigations** (`frontend/src/pages/InvestigationsList.tsx`,
`InvestigationDetail.tsx`, Blueprint E-9, FR-E9-01): a filterable list and
a detail screen with type, related sample/test result, an editable root
cause/CAPA form (QA Officer/Lab Supervisor only, locked read-only once
`closed`), and the close action. Read access is always visible, same
reasoning as Documents.

The `Investigation` model's own docstring names two trigger points —
"Opened... when a TestResult is flagged OOS/OOT, or when an Approver
rejects a Sample into `under_investigation`" — but neither `Sample.reject`
nor OOS `TestResult` creation actually creates one; both just leave the
FSM state with nothing tracking it. Rather than quietly changing that
backend behavior as a side effect of a UI feature, this adds contextual
**"Open Investigation"** buttons instead: on Sample detail when
`status === "under_investigation"`, and per-row on Test Request detail for
any `is_out_of_spec` result — both pre-fill the right `related_sample`/
`related_test_result` and route straight to the new investigation. Once
one exists, the button becomes a status link instead, so it can't be
opened twice for the same nonconformance.

Same class of filtering bug as the previous two screens, found the same
way: `InvestigationViewSet` had no `get_queryset()` override, so
`?status=`/`?related_sample=`/`?related_test_result=` did nothing
server-side — needed both for the list's status filter and for the
Sample/Test-Request pages to know whether an investigation already
exists. Fixed in `apps/investigations/views.py`, regression-tested
(backend now at 60 tests). `InvestigationSerializer` also gained
`related_sample_code` (display convenience, same convention as
elsewhere). `apiPatch()` was added to `frontend/src/api/client.ts` — the
root cause/CAPA edit form is the first thing in this frontend that needed
PATCH rather than GET/POST.

Verified live end to end: opened an investigation from a rejected
Water/Environmental sample, saved root cause/CAPA and confirmed it
survived a hard reload, closed it and confirmed the form switched to
read-only, then separately opened a second investigation from an
out-of-spec Tensile Strength result and confirmed that row's button
correctly swapped to a status link afterward.

**Equipment** (`frontend/src/pages/EquipmentList.tsx`, `InstrumentDetail.tsx`,
Blueprint Section 3.3, C-2/E-3): instruments and standard reagents/reference
materials, each with a create form, plus per-instrument detail — attached
components (e.g. FESEM+EDX), calibration history, and a log-calibration
form. Read access is always visible, same reasoning as Documents/
Investigations; the create/log-calibration forms are gated to Instrument
Custodian/Lab Supervisor (`EQUIPMENT_WRITE_ROLES`).

Same class of filtering bug as the previous three screens, found the same
way: `InstrumentViewSet` had no `get_queryset()` override, so `?status=`
(the Equipment screen's "which instruments are out of calibration" filter)
did nothing server-side. Fixed in `apps/equipment/views.py`,
regression-tested (backend now at 61 tests). `InstrumentSerializer`/
`CalibrationRecordSerializer` also gained `custodian_display_name`/
`performed_by_display_name`, matching the display-field convention used
everywhere else.

Verified live end to end: created an instrument and a standard reagent,
logged a calibration record and confirmed `Instrument.status`/
`calibration_due_date` synced correctly (FR-E3-02) through this new UI —
not just the API, as originally verified when the endpoint was built — and
confirmed the status filter actually filters. Also deliberately verified
the negative case: the write forms correctly stay hidden for an account
without the required role, then reappear once temporarily granted it.

**Training** (`frontend/src/pages/TrainingList.tsx`,
`TrainingSessionDetail.tsx`, Blueprint Section 3.6): courses, sessions,
and credit notes, each with a create form where applicable; a session
detail screen with its enrollments (complete/cancel), walk-in enrollment
registration, an attendee-export CSV download, and the session FSM
actions. Course/session read is public per the backend (`AllowAny`, since
customers browse the catalog before logging in — Blueprint Section 4.3),
but the console still gates its own write UI to Training Coordinator/Lab
Supervisor/System Administrator (`TRAINING_WRITE_ROLES`) regardless.

Unlike the last four screens, the real gap here wasn't just a missing
filter: `TrainingSession` has `start_session`/`complete_session`/
`cancel_session` `@transition` methods on the model, but
`TrainingSessionViewSet` exposed no action to reach *any* of them — a
session could never actually be started, completed, or cancelled through
the API at all. Added `start-session`/`complete-session`/`cancel-session`
actions using the file's own existing `_run_transition` helper (already
powering `EnrollmentViewSet.complete`/`cancel`), so this exposes existing
model behavior rather than inventing new business logic — the same
principle behind the Investigations screen's contextual buttons instead
of an automatic side effect.

The now-familiar filtering gap showed up twice more on top of that:
neither `TrainingSessionViewSet` nor `EnrollmentViewSet` had a
`get_queryset()` override, so `?status=`/`?course=` and `?session=`/
`?status=` did nothing server-side — needed for the session list and the
per-session enrollee list respectively. Fixed in `apps/training/views.py`,
regression-tested (backend now at 65 tests).
`TrainingSessionSerializer` also gained `instructor_display_name`,
matching the display-field convention used everywhere else.

Verified live end to end: created a course and a session, ran the full
`start-session` → `complete-session` lifecycle, registered a walk-in
enrollment and completed it (certificate correctly marked issued),
downloaded a real attendee-export CSV with real enrollment data, and
applied a credit note to a different session's enrollment — status
flipped to `applied` and the Apply control correctly disappeared
afterward.

**Billing** (`frontend/src/pages/BillingList.tsx`, `InvoiceDetail.tsx`,
Blueprint Section 3.7): a status-filterable invoice list with a create
form, and per-invoice payment history with a record-payment form.
Write access is gated to Training Coordinator/Lab Supervisor/System
Administrator (`BILLING_WRITE_ROLES`); read is open to any authenticated
staff, same reasoning as Documents/Investigations/Equipment/Training.

Same filtering gap as the previous five screens, found the same way:
`InvoiceViewSet` had no `get_queryset()` override, so `?status=` did
nothing server-side. Fixed in `apps/billing/views.py`, regression-tested
(backend now at 68 tests). `InvoiceSerializer` also gained
`customer_email`, a `SerializerMethodField` resolving whichever of
`order`/`enrollment` is actually set — an `Invoice` bills exactly one of
the two, never both, so this is the one case among all these
display-convenience fields that couldn't just be a `source=` lookup.

This is the 8th and last of the currently-planned Staff Console screens.
The frontend now covers every staff-facing resource group in the
Blueprint's API except Reports (`/api/v1/reports/`), which has no screen:
`Report` is metadata pointing at an OSS object key that nothing currently
produces, so a Reports screen would list rows whose actual documents don't
exist. It belongs with the PDF pipeline it depends on — see Known gaps.

Verified live end to end: created an invoice against a real `Order`
(`customer_email` resolved correctly), recorded a confirmed payment and
watched the invoice auto-transition to `paid` through this new UI exactly
as the endpoint's own tests already proved server-side, and confirmed the
status filter actually filters.

### Reports screen

`/reports` lists every generated report with its live generation status;
`SampleDetail` grows a **Reports** card once a sample reaches `approved`,
which is the only place a report can be created.

Three things about it are deliberate:

- **Creation lives on the sample, not on the Reports screen.** FR-C6-03
  scopes generation to an approved sample, so the control belongs where
  that sample already is; a "new report" button on a list screen would
  need a sample picker that could only offer approved samples anyway. The
  empty Reports screen says so rather than being a dead end.
- **No client-side role gate on generating.** `ReportViewSet` requires only
  authentication, and inventing a stricter rule in the UI would hide the
  control from staff the API would have let through. Contrast the Sample
  FSM buttons, which *do* mirror real server-side role gates.
- **The presigned URL is fetched on click, never rendered into an `href`.**
  It expires (15 minutes by default), so a link written when the table
  rendered is one that quietly stops working while the page is open.

The list polls (3s) only while something is `pending` or `generating`, and
stops once nothing is in flight — generation is a background job, so a row
becomes `ready` with no user action, but an idle screen shouldn't be
issuing requests.

Adding this eighth nav item pushed the header past the 1100px content
container, so the header bar is now full-width while `<main>` stays
constrained — a two-row header or a clipped nav link being the alternative.
Below about 1100px the nav scrolls horizontally rather than wrapping.

## Customer Portal (React frontend)

`customer-portal/` (Blueprint Section 2.1 item 1's second frontend, a
genuinely separate app from the Staff Console — not a shared codebase,
matching the two-segregated-identity-domains principle that runs through
this whole project): Vite + React + TypeScript, React Router, TanStack
Query — same stack as the Staff Console, but its own `npm install`/`npm
run dev` on its own port. **Needed zero backend changes to build**: every
endpoint it uses (`/auth/customer/*`, `/my/orders/`, `/my/samples/`, the
public `/training-courses/`/`/training-sessions/`, `/my/enrollments/`,
`/my/credit-notes/`, `/my/invoices/`) already existed and was already
covered by `backend/tests/`.

**Running it**: `cd customer-portal && npm install && npm run dev` (or
the `customer-portal` entry in `.claude/launch.json`), alongside the
backend on `:8000`. The dev server listens on `:5173` — the same port
`CUSTOMER_PORTAL_BASE_URL` already defaulted to (`config/settings.py`,
set up back when only the customer auth *backend* existed) — and proxies
`/api` to `:8000`, same single-origin reasoning as the Staff Console.

**Auth is genuinely simpler here than the Staff Console's**: customer
auth was never Entra ID SSO — it's plain email/password + optional TOTP
MFA against `CustomerSessionAuthentication`, which already uses Django's
own session cookie (just a different session key, `customer_user_id`,
than the staff `_auth_user_id`). So there's no OAuth2 redirect dance, no
port-hop indirection like `StaffLoginCompleteView` — `AuthContext.tsx`
just POSTs to `/auth/customer/login` directly like any other form. One
piece of infrastructure was already in place before this session touched
it: `CSRF_TRUSTED_ORIGINS` already included `http://localhost:5173`
(added proactively alongside `:5174` when the Staff Console's CSRF bug
was fixed), so the same class of "CSRF Failed: Origin checking failed"
bug that hit the Staff Console never happened here.

**Email verification round-trips through this app**: `customer_auth.py`'s
`send_verification_email` builds the link as
`{CUSTOMER_PORTAL_BASE_URL}/verify-email?token=...`; `VerifyEmail.tsx`
reads `?token=` from the URL and POSTs it automatically on mount — no
user input needed beyond clicking the emailed link. `MyEnrollments.tsx`
cross-references the public `/training-sessions/` list to show course
title/date, since `CustomerEnrollmentSerializer` only returns a bare
`session` id (no server-side change needed to fix that — the public
endpoint already has everything).

Verified live end to end, using a **real account this time, no
workaround needed** (unlike the Staff Console, where Entra ID SSO can't
be completed non-interactively in this environment): registered a new
customer, pulled the actual verification link out of the console email
backend's server log, followed it, logged in, browsed the public Training
catalog while still logged out to confirm it's genuinely public, enrolled
in a real session (the seat count updated 1/20 → 2/20), enabled MFA and
confirmed it with a TOTP code computed via `pyotp` against the real
provisioning secret (the same library `backend/tests/test_customer_auth.py`
already uses), logged out, and logged back in with the MFA-required flow
correctly triggered and satisfied on the second attempt.

## Client input is a 400, never a 500

Every `get_queryset` override in this codebase reads its own query
parameters by hand. That is deliberate — DRF silently ignores params it does
not recognise, so a filter the client sends and the server never implements
does nothing, quietly, which is a bug this project has already been bitten by
more than once (see the `?status=`/`?sample=` notes above).

The cost of reading them by hand is that nothing validates them. Django's ORM
takes a lookup value to be already of the field's type: `.filter(sample_id=
"abc")` raises `ValueError`, not `DoesNotExist`. So `?sample=abc` was a
server error on eleven route/parameter pairs across eight apps, and a raw
`request.data` read skipped straight past a `CharField`'s `max_length` and
let Postgres enforce it — `value too long for type character varying(255)`,
a database column name quoted at whoever filled in a form field.

`apps/common/params.py` holds the two helpers that close this:

- `int_param(value, name)` — an integer id or `None`, and a 400 keyed by the
  parameter name for anything else.
- `str_param(value, name, max_length=...)` — a bounded string, rejecting a
  non-string and anything over the destination column's ceiling.

**Guard the result with `is not None`, not truthiness.** `int_param("0")` is
`0`, which is falsy: an `if sample_id:` guard would skip the filter entirely
and return the whole table where the client asked for one row. That is the
opposite of the requested query rather than a near miss, and
`test_malformed_request_params.py` pins it along with the rest.

These are small and explicit rather than a filter backend, because the fix
that fits is one that wraps the existing hand-rolled read rather than one
that replaces the pattern. New `get_queryset` overrides should use them, and
new numeric filters should be added to `NUMERIC_FILTERS` in that test file,
which walks the routes rather than asserting a single case.

The same exposure exists on the **request body**. JSON's top level may
legally be an array, a string, or null, and DRF hands whatever it parsed
straight through — so a hand-rolled action doing `request.data.get(...)` or
`{**request.data}` met a body of `[1, 2]` with an AttributeError or
TypeError. Serializer-backed writes are already safe (DRF answers a non-dict
with "Invalid data. Expected a dictionary" first); it is only the by-hand
readers that were exposed, and `body_dict(request)` is the third helper.

Five sites had it, found by fuzzing every write route rather than by reading
for them — and **two of the five were invisible to the first pass**, because
an FSM guard rejected the request before the body was ever read. Anything
checking this has to put the object into the state that lets execution reach
the body, which is what `test_malformed_request_bodies.py` does.

### Past shape and type: input that is nonsense anyway

A third tier sits past both of those — input that passes every type check
and still describes something that cannot be true. `test_semantic_invariants
.py` covers it, and the line it draws is worth stating, because it is a line
about authority rather than about code:

**A value is refused when no reading of the business makes it valid, and
left alone when refusing it would be inventing policy.** A negative invoice
is the first kind — money owed *to* a customer sitting in the column that
means money owed *by* them, when `CreditNote` already exists for that. A
zero invoice is the second: a fully discounted enrollment is a real thing to
bill at 0.00, and blocking it would be a business decision made by whoever
happened to be editing a serializer.

The consequential find was `TestMethod.specification_limits`. It is a
JSONField, so it accepted `{"min": "abc"}` and stored it cleanly — and then
every result entry and every file ingestion for that method raised
`TypeError` comparing a float to a string. One bad write broke a whole test
method until somebody corrected the data. It is now validated on the way in,
and `compute_out_of_spec` refuses a malformed limit rather than skipping the
check, because degrading to "no limit" would be worse than the crash it
replaces: the result would enter the record *unflagged*, which is exactly
what FR-C3-08 exists to prevent. A min above its max is the quieter half —
nothing crashes, and every result the method ever produces comes out flagged.

## Row-level security

`apps/accounts/middleware.py` (`RLSContextMiddleware`) sets
`rls.is_staff`/`rls.customer_id` Postgres session variables on every
request, which the RLS policies on `order`, `sample` and `report` check via
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

`report` joined this set when the Customer Portal gained a reports route
(`apps/reporting/migrations/0003`). Until then the table was staff-only, so
a viewset filter was the whole story — and a customer-facing list endpoint
filtered only in Python is one dropped `.filter()` away from returning every
customer's report metadata. The policy reaches the customer through
whichever parent the report hangs off (a COA joins `sample`, a training
certificate joins `order`), which is why it is two subqueries rather than
one column comparison; the `report_target_required` check constraint
guarantees at least one is non-null, so a row can never end up invisible to
its own owner.

Verified directly against Postgres, not just via HTTP status codes: as the
app's own (non-superuser) DB role, zero RLS context returns zero rows;
`rls.is_staff='true'` returns everything; two customers seeded with their
own `Order`+`Sample` each see only their own row, with zero cross-visibility.

## Instrument raw-data ingestion

`POST /api/v1/test-requests/{id}/ingest` (multipart, field `file`, optional
`instrument`) takes an instrument export, stores it in object storage, and
parses it into `TestResult` rows carrying `raw_file_id` and
`raw_file_checksum_sha256` pointing back at the file they came from — ALCOA
traceability, Blueprint Section 7.3 / Section 11.

**Synchronous, unlike report generation.** An analyst uploading an export is
standing at the instrument waiting to learn whether the file was accepted;
answering "queued" and making them poll for a parse error they could have
been told about immediately is worse than holding the request for the second
it takes. Report rendering is genuinely slow and fire-and-forget, which is
why that one is a Celery task and this one isn't.

The rules that matter:

- **The competency gate and the OOS computation are shared with manual
  entry**, and now live in `apps/testing/ingestion.py` rather than on the
  serializer that used to own them. An analyst who may not type a result in
  may not upload one either, and a limit is read from
  `TestMethod.specification_limits` in both paths. Two copies of "is this
  result out of spec" is how a lab ends up with a hand-entered result
  flagged and an ingested one not.
- **Re-uploading an identical file is refused with 409**, matched on the
  SHA-256 of the content. Double-ingesting would double every result on the
  request, which in a regulated record is a data-integrity incident rather
  than a nuisance.
- **The raw file is stored before parsing, and stays stored if the parse
  fails.** Traceability wants the artifact the lab actually received,
  including the one that turned out to be malformed.
- **A non-numeric value in a numeric column is rejected**, not stored: it
  would skip the OOS check entirely and enter the record as in-spec.
- **Parse errors carry the parser's own message** — "Row 2: value 'n/a' is
  not numeric" is actionable, "could not parse file" is not.

**Parsers are registered per `Instrument.model`** via `@register_parser`,
falling back to the generic CSV reader for anything unregistered. Only the
generic reader is implemented; see Known gaps for why. The documented
interchange format is a header row plus one row per measurement:

```csv
analyte,value,unit,data_type
Lead,0.42,mg/L,float
```

`value` is required; `analyte`, `unit` and `data_type` are optional, the
last defaulting to `float`. `analyte` names the parameter each row measures
and is what makes a multi-analyte export usable — an ICP-MS run reporting
twelve elements becomes twelve *labelled* results against one
`TestRequest`. Leave it blank for a single-parameter method, where the
method name already says what was measured.
Headers are matched case- and whitespace-insensitively, and a UTF-8 BOM is
tolerated because instrument software on Windows writes one often enough
that failing on it would make the feature look broken. A trailing delimiter
(`Lead,0.42,`) is tolerated as the formatting artifact it is; a row with a
*non-empty* surplus field is refused, because when a row has more values
than the header has columns there is no knowing which value belongs to which
column, and a guess stored in a regulated record is worse than a refused
file. Over-length `analyte`/`unit` values are refused by the parser too,
rather than reaching Postgres as a `value too long for type character
varying(32)` 500 quoting a column name at whoever uploaded the file.

**The vendor-facing specification is
[`docs/instrument-export-csv.md`](docs/instrument-export-csv.md)** — a
self-contained document to hand to an instrument vendor or integrator,
covering the format, every rejection message, what the LIMS deliberately
refuses to read from the file (pass/fail flags above all), and what we would
need from a vendor to write a native-format parser.

## Report PDF generation

The decoupled pipeline Blueprint Section 2.1a describes, and the thing
`Report.file_id` has always pointed at. `POST /api/v1/reports/` creates a
row in `pending` and enqueues `apps.reporting.tasks.generate_report_pdf`;
the worker renders the Jinja2 template selected by `report_type`, hands the
HTML to WeasyPrint, uploads the bytes to object storage, and moves the row
to `ready` with `file_id` set. `GET /api/v1/reports/{id}/download/` returns
a short-lived presigned URL.

**Asynchronous, not inline.** A COA renders in hundreds of milliseconds for
a small sample and seconds for one with many results; holding the request
open for that makes the Reports screen the slowest page in the application.
The client creates and polls.

Six decisions in here are load-bearing:

- **`Report.status` is a plain `CharField`, not a `django-fsm` `FSMField`**
  like `Sample`/`TestRequest`. Those four model regulated processes where
  every transition has a role gate and an audit consequence. This one is
  moved only by the worker, has no operator-facing transitions, and gating
  it would mean the worker needed a role to do its job.
- **`file_id` and `status` are read-only on the serializer.** A
  client-supplied `file_id` is a pointer into the shared bucket — including
  at another customer's report — and a client-supplied `status` would let a
  caller claim a report was ready before anything rendered.
- **Object keys are versioned** (`reports/{type}/{id}-v{version}.pdf`).
  Regenerating at the same version overwrites rather than orphaning
  objects; a corrected report is a new row with an incremented version
  (FR-E17-01/03) and so lands at its own key, and can never overwrite the
  document already issued to a customer.
- **A failure is recorded on the row *and* re-raised.** The row is what a
  Reports screen reads (`status='failed'`, `failure_reason`); the exception
  is what surfaces in Celery's own monitoring. Swallowing it would leave a
  report stuck at `generating` with nothing anywhere saying why.
- **The task is dispatched via `transaction.on_commit`.** Without it the
  worker can pick the task up before the `Report` row is visible and fail
  with `DoesNotExist` — the classic Celery-with-Django race, and one that
  only appears under load.
- **Jinja2 is configured with `StrictUndefined` and autoescaping.** A
  template referencing a field the context doesn't supply fails loudly
  rather than printing an empty string, because the silent version means
  shipping a COA with a blank result column. Autoescaping matters because a
  COA interpolates customer-supplied text, and an unescaped `<` corrupts
  the document it lands in.

**Templates live in `apps/reporting/templates/reports/`**, loaded by a
Jinja2 environment local to `apps/reporting/rendering.py` rather than wired
into Django's `TEMPLATES` setting — Blueprint Section 2.1a wants them
outside application code so QA can revise them without a code change.
Adding one is dropping a file in that directory. The five currently there
are **pipeline placeholders**, each carrying a "DRAFT TEMPLATE — not valid
for issue" banner; the context contract they write to is built explicitly
in `tasks.build_report_context`, which is what a replacement should target.
An unknown `report_type` raises `ReportTemplateMissing` rather than falling
back to a generic layout, since substituting a different template produces
an official-looking document that says the wrong thing.

**WeasyPrint needs system libraries** (Pango, cairo, GDK-PixBuf) present at
import time, not just the pip package — see `backend/requirements.txt` and
the CI step that installs them.

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

- **Node.js** (v24 used in dev) — only needed for the two frontends
  (`frontend/` Staff Console, `customer-portal/` Customer Portal); the
  backend alone doesn't need it.
- **PostgreSQL** (18 used in dev) — the app database.
- **Redis** — Celery broker/result backend.
- **An S3-compatible object store** — a local [MinIO](https://min.io/)
  server works for dev (`minio.exe server <data-dir> --console-address
  ":9001"`); real Alibaba Cloud OSS in production.
- **WeasyPrint's system libraries**, for report PDF generation. WeasyPrint
  links against Pango, cairo and GDK-PixBuf *at import time*, so without
  them `import weasyprint` fails and the whole app won't start. On
  Debian/Ubuntu: `sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0
  libgdk-pixbuf-2.0-0 libcairo2`. On Windows, install the GTK runtime
  (WeasyPrint documents the current installer); on macOS,
  `brew install pango gdk-pixbuf libffi`.
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

217 tests, organized by behavior rather than by app:

| File | Covers |
|---|---|
| `test_sample_fsm.py` | `Sample` FSM transitions end to end, illegal-transition 400s, per-action role gates |
| `test_segregation_of_duties.py` | `check_can_approve`: regulated (Water/Environmental) hard split vs. Failure Analysis self-approve bypass |
| `test_row_level_security.py` | Customer order/sample isolation through the real API *and* directly against the DB connection (bypassing the ORM's own filtering) — proves the Postgres policy itself enforces the boundary |
| `test_customer_auth.py` | Register → verify-email → login, generic invalid-credentials error, TOTP MFA enroll/confirm/login |
| `test_auth_domain_isolation.py` | Customer session can't reach staff endpoints and vice versa; a customer-authenticated write doesn't crash `django-simple-history` |
| `test_testing_competency_and_oos.py` | FR-C3-02 competency gate, FR-C3-08 server-computed OOS flag, expired-reagent rejection |
| `test_documents.py` | FR-D1-03 version approval archives the prior current version and syncs `Document.current_version` |
| `test_equipment_calibration.py` | FR-E3-02: a calibration result flips `Instrument.status` and advances `calibration_due_date`; `?status=` filter actually filters |
| `test_investigations.py` | FR-E9-01: `close` is the only path to `closed`, sets `closed_at` atomically, can't double-close; `?status=`/`?related_sample=` filters actually filter |
| `test_training.py` | Discount computation, `CreditNote.apply` validation, the `check_session_capacity` Celery task (called directly, not via a broker), `TrainingSession` FSM actions reachable over the API, `?session=`/`?status=`/`?course=` filters |
| `test_billing.py` | A confirmed `Payment` auto-transitions its `Invoice` to `paid`; a pending one doesn't; `?status=` filter and `customer_email` resolution (order- and enrollment-based) |
| `test_audit_retention.py` | `run_retention_sweep` idempotency via the `AuditLogEntry` ledger, the real boto3-against-MinIO archive path, and that an `anonymize` policy writes `retention_anonymize_no_pii` rather than claiming `retention_anonymized` when nothing was stripped |
| `test_fsm_refresh_from_db.py` | Regression test for the `FSMModelMixin` fix below |
| `test_staff_me.py` | `GET /auth/staff/me`, `POST /auth/staff/logout`, and the Entra ID login-complete redirect (Staff Console support endpoints) |
| `test_report_generation.py` | FR-C6-03 creation guard; the Celery render task producing a real PDF; per-version object keys so a correction can't overwrite an issued document; failure recorded on the row *and* re-raised; the download endpoint's 409-with-status; a real MinIO round trip |
| `test_customer_reports.py` | `GET /my/reports/` isolation asserted twice — through the API, and against the raw DB connection with the ORM bypassed (the RLS policy added for this route); `ready`-only filtering; another customer's report 404s rather than 403s; internal fields absent from the payload |
| `test_instrument_ingestion.py` | Generic CSV parsing (BOM, case/space-insensitive headers, binary and non-numeric rejection, trailing delimiter tolerated, ragged and over-length rows refused as 400s rather than 500s); OOS computed from the method rather than the file; the competency gate applying to uploads as it does to typed entry; re-uploading an identical file refused with 409; the raw file stored even when the parse fails |
| `test_celery_beat_schedule.py` | That every `CELERY_BEAT_SCHEDULE` entry resolves to a task a worker would actually answer to. Beat dispatches by dotted name, so a rename or typo produces an unroutable message: beat keeps running, the worker logs and moves on, every other test passes, and the retention sweep silently never runs |
| `test_semantic_invariants.py` | Well-typed input that is nonsense anyway: unusable `specification_limits` (non-numeric, or a min above its max) refused on write and refused again at result entry for rows already carrying them; a calibration due before it was performed or performed in the future; a session ending before it starts or with a minimum above its capacity; a negative invoice. Each paired with the boundary case that must still be accepted (same-day calibration, single-day session, minimum equal to capacity, zero invoice) |
| `test_malformed_request_bodies.py` | A non-object JSON body (array, string, null, number) is a 400 on every write route, walked from the router rather than listed; the five hand-rolled actions that read `request.data` as a dict individually pinned, including the customer-reachable credit-note apply; a bodyless POST still works and a long review comment is still accepted |
| `test_malformed_request_params.py` | Every numeric query-string filter across eight apps returns 400 rather than 500 for a non-numeric id, still filters for a valid one, ignores an empty one, and treats `0` as a filter rather than as "no filter"; over-length and non-string chain-of-custody locations refused before Postgres sees them |
| `test_sample_filters.py` | `SampleViewSet`'s `?status=`/`?service_line=` filters actually filter (a real bug the Review Queue surfaced) |
| `test_test_request_filters.py` | `TestRequestViewSet`'s `?sample=`/`?status=` filters (same class of bug, found the same way, building the Testing Queue) |

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
- **`tests/helpers.reload(instance)`** fetches a fresh instance via
  `Model.objects.get(pk=...)` instead of calling `instance.refresh_from_db()`
  in place. It predates a real bug this test suite surfaced: `Sample`,
  `TestRequest`, `TrainingSession`, and `Enrollment` all declare a
  `django-fsm-2` `protected=True` field but didn't mix in
  `django_fsm.FSMModelMixin`, so `Model.refresh_from_db()`'s plain `setattr`
  on every field hit the protected FSM descriptor's rejection of any second
  direct assignment, raising `AttributeError: Direct status modification is
  not allowed` — on any instance of any of these four models, not just in
  tests. Now fixed (`FSMModelMixin` added to all four,
  `test_fsm_refresh_from_db.py` regression-tests it), so plain
  `refresh_from_db()` works again; `reload()` is kept as a convenience for
  new tests that don't need to mutate the same instance in place.

Not covered yet: Entra ID SSO, which needs a live Azure AD tenant (per the
Authentication section above). That is the only remaining hole — report PDF
generation and instrument file-parsing are both built and tested
(`test_report_generation.py`, `test_instrument_ingestion.py`), and
`CELERY_BEAT_SCHEDULE`'s wiring is now covered by
`test_celery_beat_schedule.py`.

## Frontend test suites

Vitest + React Testing Library + jsdom, run by `npm run test` in either
frontend (`npm run test:watch` while developing). 200 tests: 150 in
`frontend/`, 50 in `customer-portal/`.

**`fetch` is the only thing stubbed.** Not `AuthContext`, not the React
Query hooks, not `api/client.ts` — so every test drives the real API client
(CSRF header, `ApiError` mapping, the 204 case), the real provider, and the
real component. Mocking the hooks instead would leave exactly the wiring
these tests exist to protect untested, and would keep passing after that
wiring broke. `src/test/helpers.tsx` provides `stubApi()` (a route table
keyed on `"METHOD /path"`, which throws on an unmatched request rather than
returning a plausible empty result) and `renderWithProviders()`.

| File | Covers |
|---|---|
| `frontend/src/auth/AuthContext.test.tsx` | `hasRole` as a variadic OR, false for every role while unauthenticated; `logout` clearing the cached user to `null` **not** `undefined`, dropping other cached queries while keeping the `staff-me` entry, and posting to the endpoint rather than only clearing local state |
| `frontend/src/components/ProtectedRoute.test.tsx` | The three-state guard: renders for an authenticated user, redirects on 401/403, and shows a loading state *instead of redirecting* while `staff-me` is still in flight |
| `frontend/src/pages/SampleDetail.test.tsx` | Which FSM edges are offered per status; per-action role gating with the required role named in the tooltip; the `water_environmental` segregation-of-duties block and its `failure_analysis` bypass; a disabled action firing no request; review comments in the body; a server rejection reaching the user |
| `frontend/src/pages/ReportsList.test.tsx` | Download offered only for a `ready` report and disabled with a reason otherwise; the presigned URL fetched at click time rather than written into an href at render time (it expires); a failed report's reason reaching the screen; the status filter reaching the query string |
| `frontend/src/api/client.test.ts` | CSRF header on unsafe methods only and url-decoded; `credentials: include`; 204 → `undefined`; `ApiError` status/body; `describeApiError` unwrapping `detail`, field-error arrays, plain strings, and non-`ApiError` values |
| `frontend/src/pages/BillingList.test.tsx` | `BILLING_WRITE_ROLES` gating the invoice form (a hand-maintained mirror of the server's list); billing an order vs an enrollment sending exactly one of the two; the status filter reaching the API |
| `frontend/src/pages/EquipmentList.test.tsx` | `EQUIPMENT_WRITE_ROLES` gating both write forms; filtering for `out_of_calibration`, the status FR-E3-02 sets automatically; a reagent's CRM reference and expiry being sent, since FR-C3-02 depends on both |
| `frontend/src/pages/TrainingList.test.tsx` | `TRAINING_WRITE_ROLES` gating course/session creation and the credit-note control; applying a note posting the typed enrollment; no control offered for an already-applied note; a click with no enrollment posting nothing rather than `NaN` |
| `frontend/src/pages/InvoiceDetail.test.tsx` | The payment form's two gates (billing role, and not on a void invoice, while staying available on a paid one for reversals); optional `reference_number`/`notes` omitted rather than sent as empty strings; the invoice re-read after recording, since a confirmed payment flips its status server-side |
| `frontend/src/pages/TrainingSessionDetail.test.tsx` | `TRAINING_SESSION_ACTIONS_BY_STATUS` offering only the legal FSM edges per status; the role gate showing actions disabled with the required role named; per-enrollment complete/cancel offered only while `confirmed`, and posted against the enrollment rather than the session |
| `frontend/src/pages/InstrumentDetail.test.tsx` | `EQUIPMENT_WRITE_ROLES` gating the calibration form (and it staying available on an out-of-calibration instrument, since a passing calibration is how one returns to service); the instrument re-read after logging, because FR-E3-02 flips its status server-side |
| `frontend/src/pages/DocumentDetail.test.tsx` | `DOCUMENT_WRITE_ROLES`; approval offered only on non-current versions and posted against the version; the document re-read afterwards, since FR-D1-03 archives a *different* row; exactly one version badged Current; the next version number re-suggested once the document loads |
| `frontend/src/pages/InvestigationDetail.test.tsx` | `INVESTIGATION_WRITE_ROLES`; a closed investigation offering neither the edit form nor the close button while still displaying its findings; `close` posted as an action rather than a status patch (FR-E9-01); root cause and CAPA prefilled and sent together |
| `customer-portal/src/pages/Login.test.tsx` | The MFA step-up: `mfa_code` omitted (not `""`) on the first attempt, the authenticator field revealed only when the server answers `code: "MFARequiredError"`, the retry carrying `mfa_code` to the same endpoint, the field staying visible on a wrong code, and the server's own message shown for bad credentials |
| `customer-portal/src/components/ProtectedRoute.test.tsx` | Same three-state guard on the customer side, where the screens behind it are RLS-scoped |
| `customer-portal/src/pages/Account.test.tsx` | The three states of TOTP enrollment: no secret revealed before one is requested, `mfa_enabled` **not** claimed between issuing the secret and confirming a code, the account re-read after confirming rather than set locally, and the code field surviving a wrong code so the customer isn't sent back to a secret they already stored |
| `customer-portal/src/pages/MyCreditNotes.test.tsx` | Redemption posting the entered enrollment; no control offered on an already-applied note; a click with nothing entered posting nothing rather than `NaN`; per-row entry state, so typing against one note cannot redeem another |
| `customer-portal/src/pages/MyReports.test.tsx` | That no presigned URL is requested until the customer clicks (they expire, so minting on load hands out links that silently fail), navigation to the returned URL, and a download failure reported against the row instead of navigating |

Two things worth knowing before adding more:

- **`renderWithProviders` takes a `path`, and you need it whenever the
  component under test lives at `/login` or `/`.** The helper registers
  placeholder routes at those two paths so a `<Navigate>` is observable as
  rendered text; without `path`, the placeholder wins the route match and
  the test silently asserts against "Login page" instead of the component.
- **Assert on the query cache, not on `result.current`, for anything that
  must happen synchronously.** React Query's observer notifications reach a
  `renderHook` result asynchronously, so a synchronous assertion on
  `result.current` right after an `act()` is testing the notification
  scheduler, not the code under test. `AuthContext.test.tsx`'s logout test
  checks `queryClient.getQueryData(["staff-me"])` for exactly this reason.

Not covered: the pure list and read views on either side — the Staff
Console's `SamplesList`/`DocumentsList`/`InvestigationsList`, and the
Customer Portal's `Orders`/`Samples`/`TrainingCatalog`/`MyEnrollments`/
`MyInvoices` — which render what the API returns with no client-side rule
to drift from, and whose filters are covered where they exist. Every screen
on either side that gates on a role, mirrors an FSM, moves money, or
handles credentials is covered. Coverage went where server-side rules exist for a screen to drift
from — role gates, FSM action sets, filters, and money-moving controls —
rather than spreading evenly across every screen. The three
hand-maintained `*_WRITE_ROLES` constants in `api/types.ts` are each now
pinned by tests, since their own comments admit they are copies of the
server's lists kept in sync by hand.

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request, and on pushes to
`main`, in two jobs:

- **Backend** — the full `pytest` suite against live PostgreSQL 18, Redis,
  and MinIO service containers, the same stack the suite is written for
  (see Running the test suite above). Nothing is mocked in CI that isn't
  mocked locally.
- **Infra** — `terraform fmt -check` and `terraform validate` over
  `infra/`. `validate` is a schema check against the provider rather than a
  call to Alibaba, so it needs no credentials — and it needs the provider
  registry, which is exactly why it lives in CI rather than being something
  a developer is relied on to have run.
- **Frontend** — a matrix over `frontend/` and `customer-portal/` running
  `npm ci`, `npm run lint` (oxlint, `--deny-warnings`), `npm run test` (Vitest, see Frontend
  test suites below), and `npm run build` (`tsc -b && vite build`, so a type
  error fails the build — test files live under `src/`, so they are
  typechecked too).

Those two triggers are chosen so every job runs exactly once per commit:
`pull_request` covers branch work and `push` covers `main` itself. Widening
`push` to all branches would double every job for the whole life of a pull
request, buying only CI on a branch with no pull request open yet.

Three details in that workflow are load-bearing and worth knowing before
editing it:

- **The `nasat_lims` role is created `NOSUPERUSER NOBYPASSRLS`.** Postgres
  exempts both attributes from row-level security entirely, so a
  superuser role makes `test_row_level_security.py`'s
  direct-against-the-DB-connection assertion fail with one customer
  reading another customer's orders — which reads like a security
  regression in the application rather than what it is, a CI provisioning
  mistake. `CREATEDB` *is* required: pytest-django creates
  `test_nasat_lims` itself. The same applies to any local Postgres you
  point the suite at.
- **Dummy `AZURE_AD_*` values are set.** `config/urls.py` imports
  `django_auth_adfs.urls`, which validates `AUTH_ADFS` at startup
  (see Authentication above), so the suite can't even be *collected*
  without them. No test performs a real SSO handshake.
- **MinIO runs via `docker run`, not as a service container.** The
  official image needs a `server /data` command and the `services:` block
  has no way to supply one.

The frontend jobs use `npm ci`, never `npm install`: `npm ci` installs
exactly what the lockfile pins and never rewrites it, so CI can't drift
`package-lock.json` out from under you.

## Known gaps / next steps

Genuinely not built yet, not just undocumented:

- **Five business rules are deliberately unenforced, pending NASAT's
  decision.** The semantic sweep (see "Past shape and type" above) refused
  everything internally contradictory and stopped there. These five are
  each defensible in both directions, so a developer picking one would be
  writing policy rather than enforcing it:
  - **Staff can enroll past a session's capacity, and into a cancelled or
    completed session.** The *customer* path already refuses both
    (`CustomerEnrollmentSerializer.validate_session`); the staff path does
    not. Whether a coordinator registering a walk-in should be able to
    override capacity, or backfill attendance onto a session that has
    finished, is a question about how NASAT actually runs its front desk.
  - **The same customer can enroll twice in one session.** Refusing
    outright would break a legitimate re-enrollment after a cancellation;
    doing it properly means deciding which prior states block a new
    enrollment.
  - **A session may be created with a capacity of zero.** Nonsense as a
    live session, plausible as a draft awaiting a room booking.
  - **An invoice may be issued for 0.00.** A fully discounted or fully
    credit-noted enrollment is a real thing to bill at zero.
  - **A payment may be recorded against a void invoice.** The code already
    declines to mark a void invoice paid, so the case was thought about;
    whether recording the payment at all should be refused is a
    reconciliation question.

- **No QA-authored report templates.** The PDF
  pipeline itself is built (see Report PDF generation above), but the five
  templates it renders are pipeline placeholders carrying a "DRAFT
  TEMPLATE — not valid for issue" banner; the real layouts are QA's to
  author per Blueprint Section 2.1a, and the Water/Environmental COA is
  specified by Job Order LABW2410-238. Replacing one is a file swap in
  `apps/reporting/templates/reports/`. Both the Staff Console's Reports
  screen and the Customer Portal's My Reports route now exist, so what is
  missing here is the layouts themselves, not the plumbing.
- **No vendor-specific instrument parsers.** Ingestion itself is built
  (see Instrument raw-data ingestion above) and the generic CSV format
  works today, but no FESEM/EDX/TGA/XRF native export is parsed: those are
  vendor-specific binary or semi-structured text, and writing a parser for
  a format nobody has produced a sample of yields code that looks finished
  and fails on first contact with the instrument. Registering one is a
  decorator on a function once real export files exist to write it
  against — [`docs/instrument-export-csv.md`](docs/instrument-export-csv.md)
  §10 lists exactly what to ask a vendor for.
- **`/my/orders/` and `/my/samples/` are still read-only.** Customers can
  self-enroll in training (`POST /my/enrollments/`) and apply their own
  credit notes, but there's no customer-initiated *order* creation yet —
  walk-in/staff-initiated intake is still the only path onto a `Sample`.
- **No CD, and the IaC has never been applied.** `infra/` now holds
  Terraform for the Alibaba Cloud resources in Blueprint Section 2.2 — VPC,
  OSS bucket, RDS PostgreSQL, Redis — and CI runs `terraform fmt` and
  `terraform validate` against it on every pull request. But **no `plan` or
  `apply` has ever run against a real account**, compute is deliberately
  out of scope until someone decides between ECS/ACK/SAE, and nothing
  deploys: there is still no release pipeline. Outside of CI this runs from
  a local dev environment only. See `infra/README.md`.
- **Real Alibaba Cloud OSS is unverified.** The object storage
  integration is proven against local MinIO; whether Alibaba's actual
  S3-compatible surface accepts the same storage-class values, auth
  flow, etc. has not been confirmed against a live account.
- **Real SMTP is unverified.** `EMAIL_BACKEND` is the console backend;
  verification/MFA emails print to the server log rather than sending.
- **No Odoo ERP integration** — explicitly out of scope for this phase
  per the Blueprint.
- **Retention `anonymize` is still a no-op, but an honest one.** None of
  the 5 `RetentionPolicy` record types carry PII on themselves — it lives
  on `CustomerUser`, which is not a retention-governed record type, and an
  expired `Enrollment` does not mean that customer is gone. The sweep
  therefore strips nothing, and **says so**: it writes
  `retention_anonymize_no_pii` to the audit ledger, never
  `retention_anonymized`. The distinction matters because the ledger is the
  compliance record — an entry claiming a record was anonymized when
  nothing was is a false statement in the one system whose purpose is being
  trustworthy. When a record type does carry PII the label becomes
  `retention_anonymized`, and every row marked with the old label is
  reprocessed automatically, since idempotency matches on the label.
  Closing this needs a decision the schema cannot make: what "last
  activity" means for a customer, and how long after it their identity
  should persist. ISO/IEC 17025's five-year clock governs *records*; RA
  10173 governs *people*, and they are not the same clock.
