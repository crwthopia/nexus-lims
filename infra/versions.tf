terraform {
  required_version = ">= 1.6"

  required_providers {
    alicloud = {
      source = "aliyun/alicloud"
      # Pinned to a major line rather than floating: an IaC change should be
      # a deliberate commit, not something a provider release does to you
      # between one apply and the next.
      version = "~> 1.230"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State is deliberately not configured here. It belongs in an OSS bucket
  # with locking, but that bucket cannot be created by the configuration
  # that stores its own state in it -- so it is provisioned once, by hand or
  # by a separate bootstrap, and wired in via `terraform init -backend-config`.
  # See README.md in this directory.
}

provider "alicloud" {
  region = var.region
  # Credentials come from ALICLOUD_ACCESS_KEY / ALICLOUD_SECRET_KEY in the
  # environment, never from a variable in this repository.
}
