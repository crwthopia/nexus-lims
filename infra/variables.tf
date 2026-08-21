variable "region" {
  description = "Alibaba Cloud region. Manila is ap-southeast-6, matching OSS_ENDPOINT in backend/.env.example."
  type        = string
  default     = "ap-southeast-6"
}

variable "environment" {
  description = "Environment name, used as a suffix on every resource so two environments can share an account."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]{2,16}$", var.environment))
    error_message = "environment must be 2-16 lowercase letters, digits or hyphens (it becomes part of an OSS bucket name)."
  }
}

variable "project" {
  description = "Resource name prefix."
  type        = string
  default     = "nasat-lims"
}

variable "vpc_cidr" {
  description = "CIDR for the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "app_subnet_cidr" {
  description = "CIDR for the application vSwitch (Django + Celery)."
  type        = string
  default     = "10.20.1.0/24"
}

variable "data_subnet_cidr" {
  description = "CIDR for the data vSwitch (RDS + Redis). Separate from the app subnet so database access can be restricted by network, not only by password."
  type        = string
  default     = "10.20.2.0/24"
}

variable "zone_id" {
  description = "Availability zone for the vSwitches and data services. Leave null to use the first zone the provider reports as supporting RDS PostgreSQL."
  type        = string
  default     = null
}

variable "postgres_version" {
  description = "RDS PostgreSQL engine version. 18 is what the schema is developed and CI-tested against (monthly partitioning, FORCE ROW LEVEL SECURITY)."
  type        = string
  default     = "18.0"
}

variable "postgres_instance_class" {
  description = "RDS instance class. The default is a small burstable class suitable for a pilot, not for production load."
  type        = string
  default     = "pg.n2.small.2c"
}

variable "postgres_storage_gb" {
  description = "RDS storage in GB."
  type        = number
  default     = 50
}

variable "redis_instance_class" {
  description = "ApsaraDB for Redis instance class. Redis is only a Celery broker/result backend here, so it holds little data."
  type        = string
  default     = "redis.master.micro.default"
}

variable "raw_file_retention_days" {
  description = <<-EOT
    Days before a raw instrument export transitions to the archive storage
    class. Blueprint Section 7.4a runs its own retention sweep over the
    database records; this is the storage-side counterpart for the objects
    those records point at. Set to 0 to disable the lifecycle rule.
  EOT
  type        = number
  default     = 1825 # 5 years, matching the seeded RetentionPolicy default
}

variable "tags" {
  description = "Extra tags applied to every taggable resource."
  type        = map(string)
  default     = {}
}
