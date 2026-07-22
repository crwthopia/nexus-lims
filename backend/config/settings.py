"""
Django settings for NASAT LIMS.

This settings module targets PostgreSQL on Alibaba Cloud ApsaraDB RDS (Manila
region, ap-southeast-6) per Blueprint Section 2.2, with Redis-backed Celery
per Blueprint Section 2.1 item 4. Values are read from environment variables
so this file is safe to commit; secrets are provided at deploy time via
Alibaba Cloud KMS-backed environment injection (Blueprint Section 7.6).
"""

import os
from pathlib import Path

from celery.schedules import crontab
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# .env is documented in the README/.env.example as the local-dev config path
# but nothing previously loaded it; os.environ.get() calls below silently
# fell back to their defaults regardless of what was in .env.
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# CSRF (Blueprint Section 2.1 item 1: React Staff Console). Django's
# CsrfViewMiddleware checks the Origin header against request.get_host() on
# every unsafe request since Django 4.0, falling back to this list when they
# don't match -- which they never will here, since the SPA (frontend/, Vite
# dev server on 5174) and Django (8000) are different origins even though
# Vite's dev proxy (vite.config.ts) makes /api/* requests *look* same-origin
# to the browser's fetch() call; the Origin header it sends still reflects
# the page's real origin. Confirmed empirically: without this, every
# state-changing request from the SPA (e.g. a Sample FSM action) failed with
# "CSRF Failed: Origin checking failed" even though the session/CSRF cookies
# themselves were flowing correctly.
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:5173,http://localhost:5174"
).split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # Third-party (locked-in tech stack, Blueprint Section 2.1 / repo instructions)
    "rest_framework",
    "django_fsm",
    "simple_history",
    "django_auth_adfs",  # ships templates/django_auth_adfs/login_failed.html; needs APP_DIRS discovery
    # NASAT LIMS apps, one per ASTM function-map domain (Blueprint Section 10)
    "apps.accounts",
    "apps.samples",
    "apps.testing",
    "apps.review",
    "apps.reporting",
    "apps.documents",
    "apps.equipment",
    "apps.investigations",
    "apps.training",
    "apps.billing",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    # RLS session-variable middleware (Blueprint Section 2.1 item 3b). Must
    # come after AuthenticationMiddleware, which populates request.user.
    "apps.accounts.middleware.RLSContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database: PostgreSQL only. RLS policies (Blueprint Section 2.1 item 3b, 5)
# are applied via raw SQL migrations, not represented in Django model state.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "nasat_lims"),
        "USER": os.environ.get("POSTGRES_USER", "nasat_lims"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Celery (Redis broker, Blueprint Section 2.1 item 4 / ApsaraDB for Redis in prod)
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Beat schedule: the two automations the Blueprint specifies as Celery beat
# tasks (Section 7.4a retention sweep, Section 3.6/4.3 training capacity
# check). Both run once daily; retention windows are measured in years so
# there's no benefit to a tighter interval, and the capacity check only
# needs to catch a session crossing its cancellation_threshold_days boundary
# sometime today, not to the minute.
CELERY_BEAT_SCHEDULE = {
    "retention-sweep-daily": {
        "task": "apps.audit.tasks.run_retention_sweep",
        "schedule": crontab(hour=2, minute=0),
    },
    "training-capacity-check-daily": {
        "task": "apps.training.tasks.check_session_capacity",
        "schedule": crontab(hour=3, minute=0),
    },
}

# Object storage (Alibaba Cloud OSS, S3-API-compatible, Blueprint Section 2.2).
# apps/audit/oss.py talks to this via boto3 rather than Alibaba's own `oss2`
# SDK, specifically *because* OSS documents an S3-compatible API mode: the
# same client code works against a real Alibaba OSS bucket in production
# (OSS_ENDPOINT pointed at oss-ap-southeast-6.aliyuncs.com) and against a
# locally-run MinIO instance for dev/testing (OSS_ENDPOINT pointed at
# localhost:9000) -- oss2 uses Alibaba's own request-signing scheme and
# can't be pointed at a non-Alibaba S3-compatible server at all, which would
# make this whole integration untestable without a real Alibaba Cloud
# account. OSS_ACCESS_KEY_ID/OSS_ACCESS_KEY_SECRET have no default: unlike
# the other OSS_* settings, a blank credential shouldn't silently resolve to
# something that looks configured.
OSS_BUCKET_NAME = os.environ.get("OSS_BUCKET_NAME", "nasat-lims-dev")
OSS_ENDPOINT = os.environ.get("OSS_ENDPOINT", "https://oss-ap-southeast-6.aliyuncs.com")
OSS_ACCESS_KEY_ID = os.environ.get("OSS_ACCESS_KEY_ID")
OSS_ACCESS_KEY_SECRET = os.environ.get("OSS_ACCESS_KEY_SECRET")
OSS_REGION = os.environ.get("OSS_REGION", "ap-southeast-6")
# The storage class archive_object() (apps/audit/oss.py) requests for
# "archive to cold storage" (Blueprint Section 7.4a). Deliberately NOT
# hardcoded: confirmed empirically against a local MinIO instance that
# AWS-S3-style enum values are inconsistently accepted across S3-compatible
# backends -- STANDARD_IA and GLACIER both raise InvalidStorageClass against
# MinIO's default config, which only recognizes STANDARD/REDUCED_REDUNDANCY
# out of the box. REDUCED_REDUNDANCY is the default here because it's the
# one non-STANDARD class that actually works locally without extra MinIO
# configuration; override to whatever Alibaba OSS's S3-compatible surface
# actually expects (likely "IA" or "Archive" per Alibaba's own storage
# class names) once real Alibaba Cloud credentials are available to verify
# against -- this has not been confirmed against a live Alibaba account.
OSS_ARCHIVE_STORAGE_CLASS = os.environ.get("OSS_ARCHIVE_STORAGE_CLASS", "REDUCED_REDUNDANCY")
OSS_PRESIGNED_URL_EXPIRY_SECONDS = int(os.environ.get("OSS_PRESIGNED_URL_EXPIRY_SECONDS", "900"))  # 15 min, Section 5.2

AUTH_USER_MODEL = "accounts.StaffUser"

# Entra ID (Azure AD) staff SSO (Blueprint Section 2.1 item 7). Required
# settings (AUDIENCE, CLIENT_ID, RELYING_PARTY_ID, TENANT_ID) are validated
# by django_auth_adfs at first *use* -- authenticate() and, more subtly,
# importing django_auth_adfs.urls (below) both trigger it -- so a missing
# .env value here surfaces as ImproperlyConfigured at server startup, not as
# a silent no-op.
#
# StaffUser.USERNAME_FIELD is "email", but Azure AD's "email" claim is
# optional and can be absent for some accounts; USERNAME_CLAIM is set to
# "upn" (User Principal Name) instead, which Azure AD always includes and
# treats as the account's stable unique identifier. This is
# django-auth-adfs's own documented recommendation for Azure AD, not a
# NASAT-specific shortcut -- UPN commonly matches the user's email but isn't
# guaranteed to.
#
# CLAIM_MAPPING is set explicitly rather than left to the TENANT_ID-triggered
# default, for two reasons: (1) that default maps "first_name"/"last_name",
# fields StaffUser doesn't have (it extends AbstractBaseUser + PermissionsMixin,
# not AbstractUser) -- update_user_attributes() would raise
# ImproperlyConfigured the moment a real claim is processed; (2) that default
# also maps "email", which django_auth_adfs.config.Settings explicitly
# forbids when USERNAME_FIELD is "email" (a hard ImproperlyConfigured check
# at settings-load time), since USERNAME_CLAIM already owns that job.
# "oid" (Entra's object ID claim) is always present and maps to entra_oid,
# StaffUser's own stable identifier (Blueprint Section 3.1).
#
# AUDIENCE and RELYING_PARTY_ID both default to CLIENT_ID: correct for the
# default v1.0 token endpoint (VERSION is left unset) against an App
# Registration that hasn't customized "Expose an API" with its own
# Application ID URI, which is the case here.
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",  # local password auth (createsuperuser / local-dev accounts)
    "django_auth_adfs.backend.AdfsAuthCodeBackend",  # Entra ID SSO
]

AUTH_ADFS = {
    "AUDIENCE": os.environ.get("AZURE_AD_CLIENT_ID"),
    "CLIENT_ID": os.environ.get("AZURE_AD_CLIENT_ID"),
    "CLIENT_SECRET": os.environ.get("AZURE_AD_CLIENT_SECRET"),
    "RELYING_PARTY_ID": os.environ.get("AZURE_AD_CLIENT_ID"),
    "TENANT_ID": os.environ.get("AZURE_AD_TENANT_ID"),
    "USERNAME_CLAIM": "upn",
    "CLAIM_MAPPING": {
        "display_name": "name",
        "entra_oid": "oid",
    },
}

# django_auth_adfs.views.OAuth2CallbackView redirects here after a
# successful SSO login when /oauth2/login wasn't given a "next" target
# (LOGIN_URL similarly matters if any view ever uses @login_required).
# Django's own default, /accounts/profile/, doesn't exist in this project --
# left unset, a successful Entra ID login would land on a 404.
LOGIN_URL = "/oauth2/login"
LOGIN_REDIRECT_URL = "/admin/"

# Customer auth (Blueprint Section 2.1 item 7 / Section 7.1): email
# verification and MFA-enrollment messages. Console backend for local dev
# only -- prints the message (and, critically, the verification/MFA links
# customers would otherwise only get by email) to the runserver log instead
# of actually sending anything. Swap for a real SMTP/Alibaba Cloud DirectMail
# backend before this goes anywhere near production.
EMAIL_BACKEND = os.environ.get("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "no-reply@nasatlabs.test")

# Base URL the customer portal (not yet built, Blueprint Section 5.2) would
# use to build the clickable verification link; the console email includes
# the raw token either way so this doesn't block testing the flow.
CUSTOMER_PORTAL_BASE_URL = os.environ.get("CUSTOMER_PORTAL_BASE_URL", "http://localhost:5173")

# Base URL of the React Staff Console (frontend/, Blueprint Section 2.1 item
# 1). Used only by StaffLoginCompleteView (apps/accounts/views.py) to bounce
# the browser back to the SPA once Entra ID SSO finishes: django-auth-adfs's
# own post-login redirect (the "next"/state param, see OAuth2CallbackView)
# only allows redirecting within the *same host:port* it was reached on
# (url_has_allowed_host_and_scheme checks against request.get_host()), so it
# can't send the browser from the Django dev server's port straight back to
# the Vite dev server's port on its own -- this setting is the one place
# that cross-port hop is expressed. Deliberately a different default port
# (5174) than CUSTOMER_PORTAL_BASE_URL's 5173, since both dev servers may
# run at once once the customer portal exists too.
STAFF_CONSOLE_BASE_URL = os.environ.get("STAFF_CONSOLE_BASE_URL", "http://localhost:5174")

# Email verification token expiry (django.core.signing.TimestampSigner,
# apps/accounts/customer_auth.py) -- CustomerUser isn't AUTH_USER_MODEL so
# Django's built-in password-reset-style token generator (which hashes in
# the user's password/last_login) doesn't apply here; a signed, timestamped
# token is used instead.
CUSTOMER_EMAIL_VERIFICATION_MAX_AGE_SECONDS = 60 * 60 * 24  # 24 hours

# DRF (Blueprint Section 6 API layer). SessionAuthentication covers the
# browsable API / admin-cookie login path (local dev, and staff who reach
# the API via a browser session established through the /oauth2/ flow
# below). AdfsAccessTokenAuthentication covers a client presenting an Entra
# ID access token directly via `Authorization: Bearer <token>` (the React
# staff console's eventual access pattern, Blueprint Section 2.1 item 1).
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "django_auth_adfs.rest_framework.AdfsAccessTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}
