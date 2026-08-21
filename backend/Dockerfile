# syntax=docker/dockerfile:1

# ---- build ----------------------------------------------------------------
# Wheels are built in a stage that carries a compiler, so the runtime image
# does not have to. psycopg2-binary ships wheels, but weasyprint's
# dependency chain does not always, and a compiler in a production image is
# both weight and attack surface.
FROM python:3.11-slim-bookworm AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ---- runtime --------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

# PYTHONUNBUFFERED so log lines reach the container's stream as they happen
# rather than sitting in a buffer -- without it, the last minutes before a
# crash are the ones you lose.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings

# WeasyPrint links against these at import time, not at render time, so
# without them the process fails on startup rather than on the first PDF.
# libpq5 is psycopg2's runtime half.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf-2.0-0 libcairo2 \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root. A container that runs as root gives an application-level RCE
# root inside the container, and this one accepts file uploads and renders
# HTML to PDF -- two of the more common paths to exactly that.
RUN useradd --create-home --uid 10001 nexus

WORKDIR /app

COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels

COPY --chown=nexus:nexus . .

# Baked into the image so the running container serves them without a
# writable volume. Needs a SECRET_KEY because settings.py refuses to import
# without one when DEBUG is off -- this build-time value never leaves the
# layer and is never the runtime key.
RUN DJANGO_SECRET_KEY=build-time-only-not-a-runtime-secret \
    AZURE_AD_TENANT_ID=00000000-0000-0000-0000-000000000000 \
    AZURE_AD_CLIENT_ID=00000000-0000-0000-0000-000000000000 \
    AZURE_AD_CLIENT_SECRET=build-time-only \
    python manage.py collectstatic --noinput \
    && chown -R nexus:nexus /app/staticfiles

USER nexus

EXPOSE 8000

# Liveness only. The deep check is /readyz, and pointing a container
# healthcheck at it would restart the app whenever Postgres hiccuped.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# gunicorn, not runserver. Workers are sync rather than async because the
# work is database-bound Django with a blocking psycopg2 driver; the
# request that actually takes time (instrument file ingestion) is
# deliberately synchronous, so the timeout is generous.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
