"""
Object storage client (Blueprint Section 2.2: Alibaba Cloud OSS,
S3-API-compatible). Uses boto3 rather than Alibaba's own `oss2` SDK
specifically because OSS's S3-compatible mode lets identical client code
run against a real Alibaba OSS bucket in production (OSS_ENDPOINT pointed
at oss-ap-southeast-6.aliyuncs.com) and a locally-run MinIO instance in dev
(OSS_ENDPOINT pointed at localhost:9000) -- oss2 uses Alibaba's own
request-signing scheme and can't target a non-Alibaba S3-compatible server
at all, which would make this whole integration untestable without a real
Alibaba Cloud account.

Storage class: configurable via settings.OSS_ARCHIVE_STORAGE_CLASS rather
than hardcoded, because S3-compatible backends disagree on which values
they accept. Confirmed empirically against a local MinIO instance: the
AWS-standard "STANDARD_IA" and "GLACIER" enum values both raise
InvalidStorageClass -- MinIO's default config only recognizes
STANDARD/REDUCED_REDUNDANCY. Alibaba OSS's own native storage classes are
named IA/Archive/ColdArchive; whether its S3-compatible surface accepts
those names, the AWS enum names, or something else entirely has not been
confirmed against a real Alibaba Cloud account (none available in this
environment) -- verify and set OSS_ARCHIVE_STORAGE_CLASS accordingly before
relying on this in production.
"""

import logging

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


class OSSNotConfiguredError(Exception):
    """Raised when OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET aren't set."""


def get_client():
    if not settings.OSS_ACCESS_KEY_ID or not settings.OSS_ACCESS_KEY_SECRET:
        raise OSSNotConfiguredError(
            "OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET are not set (see .env.example)."
        )
    return boto3.client(
        "s3",
        endpoint_url=settings.OSS_ENDPOINT,
        aws_access_key_id=settings.OSS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OSS_ACCESS_KEY_SECRET,
        region_name=settings.OSS_REGION,
    )


def ensure_bucket(bucket=None):
    """Dev/test convenience: creates the bucket if it doesn't exist yet. Real Alibaba OSS buckets are provisioned via IaC (Blueprint Section 2.2 infra/)."""
    bucket = bucket or settings.OSS_BUCKET_NAME
    client = get_client()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)
        logger.info("oss: created bucket %s", bucket)


def archive_object(key, bucket=None):
    """
    Transitions an existing object to the Infrequent Access storage tier via
    an in-place copy with a new StorageClass (Blueprint Section 7.4a
    archive_to_cold_storage). Returns True if the object was found and
    archived, or if no object exists at that key (nothing to do is a
    legitimate terminal state, not a failure -- dev/test data commonly has
    an object key on record with nothing actually uploaded behind it).
    Raises on a genuine, unexpected OSS error, distinct from "not found",
    so the caller can decide not to mark the record processed and let a
    future sweep retry it.
    """
    bucket = bucket or settings.OSS_BUCKET_NAME
    client = get_client()

    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey"):
            logger.warning("oss: object %s/%s not found, nothing to archive", bucket, key)
            return True
        raise

    storage_class = settings.OSS_ARCHIVE_STORAGE_CLASS
    client.copy_object(
        Bucket=bucket,
        Key=key,
        CopySource={"Bucket": bucket, "Key": key},
        StorageClass=storage_class,
        MetadataDirective="COPY",
    )
    logger.info("oss: archived %s/%s to %s storage class", bucket, key, storage_class)
    return True
