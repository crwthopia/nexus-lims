# Infrastructure (Blueprint Section 2.2)

Terraform for the Alibaba Cloud resources NASAT LIMS needs. **Nothing here
has been applied against a real account.** See "What is verified" below
before trusting it.

## What this provisions

| Resource | Why |
|---|---|
| VPC + two vSwitches | The data vSwitch holds RDS and Redis; the app vSwitch holds compute. Separate subnets are what let database access be restricted by network, not only by password. |
| OSS bucket | Reports (`reports/`) and raw instrument exports (`raw-instrument-exports/`). Private, versioned, encrypted, with public access blocked at the bucket level as well as by ACL. |
| OSS lifecycle rule | Transitions raw exports to the `IA` storage class after `raw_file_retention_days`. Scoped to the `raw-instrument-exports/` prefix so it can never reach `reports/` — an issued COA must stay immediately retrievable. |
| RDS PostgreSQL | The application database. No public endpoint; reachable only from the app subnet. Point-in-time backups retained 30 days. |
| RDS account | **Not** a superuser and **not** `BYPASSRLS` — Postgres exempts both from row-level security, so an over-privileged role silently disables the policies on `order`/`sample`/`report`. CI creates its role the same way for the same reason. |
| ApsaraDB for Redis | Celery broker (db 0) and result backend (db 1), matching `backend/.env.example`. |

`terraform output` emits every value `backend/.env` needs; the secrets are
marked `sensitive`.

## What this deliberately does not provision

- **Compute.** How Django and the Celery worker/beat run — ECS, ACK,
  Serverless App Engine — has not been decided. Guessing would produce a
  module to delete rather than adapt.
- **The Entra ID App Registration.** It lives in Microsoft's tenant and is
  created through Azure, not Alibaba.
- **DirectMail for real SMTP.** Sending domains need DNS verification
  Terraform cannot complete on its own.
- **Remote state.** State belongs in an OSS bucket with locking, but that
  bucket cannot be created by the configuration whose state it holds. Create
  it once, then `terraform init -backend-config=...`.

## What is verified, and what is not

**Verified:** the HCL parses and `terraform fmt -check` is clean
(Terraform 1.15.9).

**Not verified:** that every resource type and attribute matches the
`aliyun/alicloud` provider's actual schema. The environment this was written
in cannot reach `registry.terraform.io`, so `terraform init` and therefore
`terraform validate` could not run. The provider has reorganised its OSS
resources across recent minor versions in particular — `alicloud_oss_bucket`
sub-resources have moved in and out of the parent resource — so treat the
following as the most likely places to need adjustment:

- `alicloud_oss_bucket_public_access_block`
- the `versioning` / `server_side_encryption_rule` blocks on `alicloud_oss_bucket`
- `alicloud_oss_bucket_lifecycle_rule` attribute names
- `alicloud_db_instance` backup attribute names
- the `alicloud_db_zones` data source arguments

**The first thing to do on a machine with registry access is:**

```bash
cd infra
terraform init -backend=false
terraform validate
```

Fix whatever that reports before going near `plan`. It is a schema check,
not a network call to Alibaba, so it needs no credentials.

## First apply

```bash
export ALICLOUD_ACCESS_KEY=...      # never committed
export ALICLOUD_SECRET_KEY=...
cd infra
terraform init -backend=false       # or -backend-config=... once state exists
terraform validate
terraform plan -var environment=staging
terraform apply -var environment=staging
```

Then wire the outputs into the application's environment:

```bash
terraform output -raw postgres_password    # etc.
```

`OSS_ARCHIVE_STORAGE_CLASS` is **not** an output, because the correct value
is a property of the storage backend rather than of this configuration —
`apps/audit/oss.py` documents that S3-compatible backends disagree about
which enum values they accept, and that Alibaba's S3-compatible surface has
never been tested against. Confirm it against the real account and set it
explicitly.
