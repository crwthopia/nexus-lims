/**
 * NASAT LIMS infrastructure (Blueprint Section 2.2).
 *
 * Provisions the four things the application cannot run without: object
 * storage for reports and raw instrument exports, a PostgreSQL database,
 * a Redis instance for the Celery broker, and the network they sit in.
 *
 * NOT provisioned here, deliberately:
 *   - Compute. How Django and the Celery worker/beat are run (ECS, ACK,
 *     Serverless App Engine) is an operational decision nobody has made
 *     yet, and guessing would produce a module that has to be deleted
 *     rather than adapted.
 *   - The Entra ID App Registration. It lives in Microsoft's tenant, not
 *     Alibaba's, and is created through Azure.
 *   - DirectMail for real SMTP. Sending domains need DNS verification that
 *     Terraform cannot complete on its own.
 *
 * See README.md in this directory for what to do before the first apply.
 */

locals {
  name = "${var.project}-${var.environment}"

  common_tags = merge(
    {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    },
    var.tags,
  )
}

# Falls back to the first zone the region reports as supporting the chosen
# PostgreSQL engine, so a fresh account does not need the operator to look
# a zone id up by hand.
data "alicloud_db_zones" "postgres" {
  engine         = "PostgreSQL"
  engine_version = var.postgres_version
}

locals {
  zone_id = coalesce(var.zone_id, data.alicloud_db_zones.postgres.zones[0].id)
}

# --- Network ---------------------------------------------------------------

resource "alicloud_vpc" "main" {
  vpc_name   = local.name
  cidr_block = var.vpc_cidr
  tags       = local.common_tags
}

resource "alicloud_vswitch" "app" {
  vpc_id       = alicloud_vpc.main.id
  cidr_block   = var.app_subnet_cidr
  zone_id      = local.zone_id
  vswitch_name = "${local.name}-app"
  tags         = local.common_tags
}

resource "alicloud_vswitch" "data" {
  vpc_id       = alicloud_vpc.main.id
  cidr_block   = var.data_subnet_cidr
  zone_id      = local.zone_id
  vswitch_name = "${local.name}-data"
  tags         = local.common_tags
}

resource "alicloud_security_group" "app" {
  security_group_name = "${local.name}-app"
  vpc_id              = alicloud_vpc.main.id
  tags                = local.common_tags
}

# --- Object storage --------------------------------------------------------

# OSS bucket names are globally unique across all of Alibaba Cloud, so a
# suffix is required -- without it the first apply in a fresh account fails
# on a name somebody else already holds.
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "alicloud_oss_bucket" "main" {
  bucket = "${local.name}-${random_id.bucket_suffix.hex}"
  tags   = local.common_tags

  # Reports are immutable once issued (FR-E17-01/03) and raw exports are
  # evidence. Versioning is the backstop for an accidental overwrite of
  # either.
  versioning {
    status = "Enabled"
  }

  server_side_encryption_rule {
    sse_algorithm = "AES256"
  }

  # Inline rather than a standalone resource, which the provider does not
  # have. `dynamic` so raw_file_retention_days = 0 omits the rule entirely
  # instead of writing a disabled one.
  dynamic "lifecycle_rule" {
    for_each = var.raw_file_retention_days > 0 ? [1] : []

    content {
      id = "archive-raw-instrument-exports"
      # Scoped to the prefix apps/testing/ingestion.object_key_for writes
      # to, so this cannot reach reports/ -- an issued COA must stay
      # immediately retrievable for the customer holding it.
      prefix  = "raw-instrument-exports/"
      enabled = true

      transitions {
        days          = var.raw_file_retention_days
        storage_class = "IA"
      }
    }
  }
}

# Private, always. Every object here is either a customer's report or a raw
# instrument export; both are reached through the presigned URLs
# apps/audit/oss.py mints, never by public read. Its own resource since
# provider 1.220.0 deprecated the bucket's `acl` argument.
resource "alicloud_oss_bucket_acl" "main" {
  bucket = alicloud_oss_bucket.main.bucket
  acl    = "private"
}

# Blocks public access at the bucket level as well as via the ACL above.
# Belt and braces on purpose: an ACL is one API call away from being
# widened by hand.
resource "alicloud_oss_bucket_public_access_block" "main" {
  bucket              = alicloud_oss_bucket.main.bucket
  block_public_access = true
}

# --- PostgreSQL ------------------------------------------------------------

resource "random_password" "postgres" {
  length  = 32
  special = true
  # Alibaba rejects several punctuation characters in RDS passwords; this is
  # the subset it documents as accepted.
  override_special = "!#$%^&*()_+-="
}

resource "alicloud_db_instance" "postgres" {
  engine           = "PostgreSQL"
  engine_version   = var.postgres_version
  instance_type    = var.postgres_instance_class
  instance_storage = var.postgres_storage_gb
  instance_name    = local.name
  vswitch_id       = alicloud_vswitch.data.id
  zone_id          = local.zone_id
  tags             = local.common_tags

  # No public endpoint. The database is reachable only from inside the VPC,
  # which is what makes the row-level security policies a second line of
  # defence rather than the only one.
  security_ips = [var.app_subnet_cidr]

}

# Backups are their own resource; alicloud_db_instance takes none of these
# arguments. An audit trail that cannot be restored to a moment in time is
# not much of an audit trail.
resource "alicloud_db_backup_policy" "postgres" {
  instance_id             = alicloud_db_instance.postgres.id
  preferred_backup_period = ["Monday", "Wednesday", "Friday", "Sunday"]
  preferred_backup_time   = "18:00Z-19:00Z"
  backup_retention_period = 30
}

resource "alicloud_db_database" "main" {
  instance_id   = alicloud_db_instance.postgres.id
  name          = replace("${var.project}_${var.environment}", "-", "_")
  character_set = "UTF8"
}

# NOT a superuser, and not BYPASSRLS. Postgres exempts both from row-level
# security, so an over-privileged application role silently disables the
# policies on order/sample/report -- see the Row-level security section of
# the root README, and the CI workflow, which creates its role the same way.
resource "alicloud_db_account" "app" {
  db_instance_id   = alicloud_db_instance.postgres.id
  account_name     = replace("${var.project}_app", "-", "_")
  account_password = random_password.postgres.result
  account_type     = "Normal"
}

resource "alicloud_db_account_privilege" "app" {
  instance_id  = alicloud_db_instance.postgres.id
  account_name = alicloud_db_account.app.account_name
  privilege    = "DBOwner"
  db_names     = [alicloud_db_database.main.name]
}

# --- Redis (Celery broker) -------------------------------------------------

resource "random_password" "redis" {
  length           = 32
  special          = true
  override_special = "!#$%^&*()_+-="
}

resource "alicloud_kvstore_instance" "redis" {
  db_instance_name = local.name
  instance_class   = var.redis_instance_class
  instance_type    = "Redis"
  vswitch_id       = alicloud_vswitch.data.id
  zone_id          = local.zone_id
  password         = random_password.redis.result
  security_ips     = [var.app_subnet_cidr]
  tags             = local.common_tags
}
