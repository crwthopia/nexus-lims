output "oss_bucket_name" {
  description = "Value for OSS_BUCKET_NAME."
  value       = alicloud_oss_bucket.main.bucket
}

output "oss_endpoint" {
  description = "Value for OSS_ENDPOINT. The S3-compatible endpoint, which is what apps/audit/oss.py's boto3 client expects -- not the native OSS endpoint."
  value       = "https://s3.${var.region}.aliyuncs.com"
}

output "postgres_host" {
  description = "Value for POSTGRES_HOST (VPC-internal; there is no public endpoint)."
  value       = alicloud_db_instance.postgres.connection_string
}

output "postgres_db" {
  description = "Value for POSTGRES_DB."
  value       = alicloud_db_database.main.name
}

output "postgres_user" {
  description = "Value for POSTGRES_USER."
  value       = alicloud_db_account.app.account_name
}

output "postgres_password" {
  description = "Value for POSTGRES_PASSWORD."
  value       = random_password.postgres.result
  sensitive   = true
}

output "celery_broker_url" {
  description = "Value for CELERY_BROKER_URL (db 0)."
  value       = "redis://:${random_password.redis.result}@${alicloud_kvstore_instance.redis.connection_domain}:6379/0"
  sensitive   = true
}

output "celery_result_backend" {
  description = "Value for CELERY_RESULT_BACKEND (db 1, matching backend/.env.example)."
  value       = "redis://:${random_password.redis.result}@${alicloud_kvstore_instance.redis.connection_domain}:6379/1"
  sensitive   = true
}

output "vpc_id" {
  description = "VPC the application compute must join to reach the database and Redis."
  value       = alicloud_vpc.main.id
}

output "app_vswitch_id" {
  description = "vSwitch for application compute. Anything outside it is blocked from RDS and Redis by security_ips."
  value       = alicloud_vswitch.app.id
}

output "app_security_group_id" {
  description = "Security group for application compute."
  value       = alicloud_security_group.app.id
}
