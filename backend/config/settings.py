"""
Django settings for NexusLIMS.

This settings module targets PostgreSQL on Alibaba Cloud ApsaraDB RDS (Manila
region, ap-southeast-6) per Blueprint Section 2.2, with Redis-backed Celery
per Blueprint Section 2.1 item 4. Values are read from environment variables
so this file is safe to commit; secrets are provided at deploy time via
Alibaba Cloud KMS-backed environment injection (Blueprint Section 7.6).
"""

import os
import sys
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
    "django_fsm",  # django-fsm-2 (the maintained fork) keeps the original module name
    "simple_history",
    "django_auth_adfs",  # ships templates/django_auth_adfs/login_failed.html; needs APP_DIRS discovery
    # NexusLIMS apps, one per ASTM function-map domain (Blueprint Section 10)
    # apps.common holds no models -- it is here so Django discovers its
    # management commands (deploy_migrate), which it only does for apps in
    # this list.
    "apps.common",
    "apps.accounts",
    "apps.samples",
    "apps.testing",
    "apps.review",
    "apps.reporting",
    "apps.documents",
    "apps.equipment",
    "apps.investigations",
    "apps.notifications",
    "apps.training",
    "apps.billing",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Directly after SecurityMiddleware, per WhiteNoise's documented
    # ordering: it has to see the request before anything that might
    # short-circuit it, but after the redirects SecurityMiddleware issues.
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
# collectstatic target inside the image. Only the Django admin and DRF's
# browsable API have static files here -- both SPAs are built and served
# separately -- but without these the admin renders unstyled in production,
# which looks like a broken deployment and is usually diagnosed as one.
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
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
    # Deliberately after the two sweeps above rather than alongside them: the
    # digest reports what is still open, and a failure recorded by the 02:00
    # retention sweep should appear in the same morning's digest rather than
    # waiting a day.
    "open-failure-digest-daily": {
        "task": "apps.notifications.tasks.send_open_failure_digest",
        "schedule": crontab(hour=6, minute=0),
    },
    "calibration-due-sweep-daily": {
        "task": "apps.notifications.tasks.sweep_calibration_due",
        "schedule": crontab(hour=6, minute=30),
    },
    # Hourly rather than daily: this is the recovery path for a notification
    # that was written but never handed to a worker because the broker was
    # down, and a customer waiting on a verification email should not wait
    # until tomorrow for it.
    "retry-stalled-notifications-hourly": {
        "task": "apps.notifications.tasks.retry_stalled_notifications",
        "schedule": crontab(minute=15),
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

# How far ahead the nightly calibration sweep (apps/notifications/tasks.py)
# starts chasing. 14 days by default: long enough that a custodian can book
# an external calibration house, short enough that the message still reads as
# urgent when it arrives. Instruments already past due are always included.
CALIBRATION_DUE_WARNING_DAYS = int(os.environ.get("CALIBRATION_DUE_WARNING_DAYS", "14"))

# Base URL of the React Staff Console (frontend/), used to build the links in
# staff notifications. Empty in dev, which yields a bare path -- the message
# still names the record, and a half-built link is worse than none.
STAFF_CONSOLE_BASE_URL = os.environ.get("STAFF_CONSOLE_BASE_URL", "")

# How long a notification may sit unsent before retry_stalled_notifications
# picks it up. Long enough that an ordinary queue backlog is not mistaken for
# a stall, short enough that a broker blip does not strand a customer waiting
# on a verification link.
NOTIFICATION_STALL_MINUTES = int(os.environ.get("NOTIFICATION_STALL_MINUTES", "15"))

# Base URL of the React Customer Portal (customer-portal/, Blueprint Section
# 5.2), used to build the clickable verification link; the console email
# includes the raw token either way so this doesn't block testing the flow.
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
# (5174) than CUSTOMER_PORTAL_BASE_URL's 5173, since both dev servers
# commonly run at once.
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
    # Without this, a delete refused by on_delete=PROTECT escapes as an
    # unhandled ProtectedError and the client gets a 500 for what is really
    # a 409. See apps/common/exception_handler.py.
    "EXCEPTION_HANDLER": "apps.common.exception_handler.protected_aware_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # Rates for the unauthenticated customer auth surface (see
    # apps/common/throttling.py). Applied per view rather than globally:
    # a global anon throttle would also cover the public training
    # catalogue, where browsing is not an attack.
    #
    # The login and register scopes are doubled up, per IP and per targeted
    # account, because per-IP alone is blind to a distributed attempt on
    # one victim.
    "DEFAULT_THROTTLE_RATES": {
        "customer_login_ip": os.environ.get("THROTTLE_LOGIN_IP", "20/min"),
        "customer_login_account": os.environ.get("THROTTLE_LOGIN_ACCOUNT", "10/min"),
        "customer_register_ip": os.environ.get("THROTTLE_REGISTER_IP", "10/hour"),
        "customer_register_account": os.environ.get("THROTTLE_REGISTER_ACCOUNT", "3/hour"),
        "customer_verify_email": os.environ.get("THROTTLE_VERIFY_EMAIL", "30/hour"),
        # Six digits, ~90s window: this is the difference between MFA and
        # decoration.
        "customer_mfa_confirm": os.environ.get("THROTTLE_MFA_CONFIRM", "10/hour"),
    },
    # Behind Alibaba's SLB every request arrives from the load balancer, so
    # REMOTE_ADDR is the balancer for all of them and a per-IP throttle
    # would rate-limit the entire customer base as one client. This tells
    # DRF how many proxies to step back through X-Forwarded-For to find the
    # real client. It must match the deployment: too high and a client can
    # spoof its own address by prepending headers, too low and everyone
    # shares one bucket.
    "NUM_PROXIES": int(os.environ["NUM_PROXIES"]) if os.environ.get("NUM_PROXIES") else None,
}

# Throttle counters live in the cache. Django's default is per-process
# local memory, which with several gunicorn workers means each worker
# counts separately and the effective limit is multiplied by the worker
# count -- and resets whenever a worker restarts. Redis is already here for
# Celery, so the throttles use it and every worker shares one counter.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("DJANGO_CACHE_URL", CELERY_BROKER_URL),
    }
}


# --- Production hardening -------------------------------------------------
#
# Every setting here is what `manage.py check --deploy` asks for, and every
# one is gated on DEBUG being off so local development over plain HTTP still
# works. Turning them on unconditionally would make the dev server unusable:
# a secure-only session cookie is never sent over http://localhost, so
# nobody could log in.
#
# The proxy header comes first because the rest depend on it. Behind
# Alibaba's SLB the application sees plain HTTP, so request.is_secure() is
# False and SECURE_SSL_REDIRECT would bounce every request into an infinite
# loop. SECURE_PROXY_SSL_HEADER tells Django to trust the load balancer's
# X-Forwarded-Proto instead -- which is only safe because the app is not
# directly reachable; anything that can set that header could otherwise
# claim any request was HTTPS.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "true").lower() == "true"
    # The probes must answer over plain HTTP. A load balancer health check
    # does not follow redirects, so without this exemption every probe gets
    # a 301, every instance is marked unhealthy, and the deployment never
    # comes up -- an outage caused entirely by the hardening above.
    # Matched against the path with the leading slash stripped.
    SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^readyz$"]

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # The customer portal is a separate origin, so Lax rather than Strict:
    # Strict would drop the session cookie on the Entra ID SSO redirect back
    # from Microsoft, and staff could never complete a login.
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True

    # One year, with subdomains and preload. HSTS is close to irreversible
    # -- a browser that has seen this header refuses plain HTTP for the
    # duration, so a misconfigured certificate cannot be worked around by
    # falling back. Deliberately overridable for a first deploy, where a
    # short max-age is the sane way in.
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

    # A regulated system must not run on the checked-in development key:
    # the session cookies, password-reset tokens and the signed email
    # verification tokens in apps/accounts/customer_auth.py are all only as
    # trustworthy as this value. Failing at startup is the point -- a
    # deployment that silently used the public default would issue
    # forgeable tokens.
    if SECRET_KEY == "dev-insecure-key-change-me":
        raise RuntimeError(
            "DJANGO_SECRET_KEY is unset and DEBUG is off. Refusing to start with "
            "the development key: every session cookie and signed token would be "
            "forgeable by anyone who has read this repository."
        )


# --- Logging --------------------------------------------------------------
#
# Django's default logging configuration sends almost nothing to stdout when
# DEBUG is off, which in a container means an operator sees silence during
# an incident. Everything here writes to stdout, because a container's log
# stream is the log: no files to rotate, no volume to mount.
#
# This is the operational log and it is a different thing from the audit
# ledger in apps/audit/. The ledger is the regulated record of what happened
# to a sample; this is for diagnosing why a request failed. Neither
# substitutes for the other, and PII should not be written here.
LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        # Unhandled exceptions in a view. Django logs these at ERROR with a
        # traceback; without an explicit handler they are swallowed once
        # DEBUG is off, and a 500 leaves no trace anywhere.
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        # Every SQL statement, at DEBUG. Off by default: it is the fastest
        # way to fill a log with the contents of the database, PII included.
        "django.db.backends": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        # WeasyPrint narrates every stylesheet it parses at INFO, so a root
        # level of INFO turns one COA render into a dozen lines of "Step 2 -
        # Fetching and parsing CSS". Its warnings are worth seeing (an
        # unresolvable image or font is a visibly broken report); its
        # progress is not.
        "weasyprint": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "fontTools": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}
