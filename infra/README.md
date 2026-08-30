# Infrastructure (Blueprint Section 2.2)

Terraform for the Alibaba Cloud resources NexusLIMS needs. **Nothing here
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
- **Mail.** Sending goes through an M365 shared mailbox via Microsoft Graph,
  which is in Microsoft's tenant and so is not Terraform's to create either.
  [m365-graph-mail.md](m365-graph-mail.md) has the procedure. It needs no DNS
  work if the domain is already in M365 -- SPF, DKIM and DMARC come with the
  tenant. The step not to skip is narrowing an admin-consented `Mail.Send`
  with an Exchange application access policy: unnarrowed, that permission
  sends as any mailbox in the tenant, the Laboratory Director's included.
- **Remote state.** State belongs in an OSS bucket with locking, but that
  bucket cannot be created by the configuration whose state it holds. Create
  it once, then `terraform init -backend-config=...`.

## What is verified, and what is not

**Verified:** `terraform fmt -check` is clean and `terraform validate`
passes against `aliyun/alicloud` v1.289.0 (Terraform 1.15.9). CI runs both
on every pull request — see the `infra` job in
`.github/workflows/ci.yml`. `validate` is a schema check against the
provider rather than a call to Alibaba, so it needs no credentials.

That check earned its place immediately: the first version of this
configuration failed it with four errors, all invisible to `fmt`.
`alicloud_oss_bucket_lifecycle_rule` does not exist as a resource type (the
rule is an inline `lifecycle_rule` block), and `alicloud_db_instance` takes
none of `backup_period` / `backup_time` / `backup_retention_period` — those
belong to `alicloud_db_backup_policy`, under different names. Two
deprecations came with it: the bucket's `acl` argument moved to
`alicloud_oss_bucket_acl` in provider 1.220.0, and
`alicloud_security_group`'s `name` became `security_group_name` in 1.239.0.

**Still not verified:** anything only a real account can answer — whether
the chosen instance classes exist in the region, whether quotas allow them,
and whether `plan` and `apply` succeed. `validate` checks shapes, not
reality.

**The `.terraform.lock.hcl` is not committed yet**, because the environment
this was authored in cannot reach the provider registry to generate one.
Run `terraform init` once on a machine that can, and commit the lock file
it writes — it pins provider versions and hashes for everyone else.

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
