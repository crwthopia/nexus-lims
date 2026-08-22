#!/bin/sh
#
# One image, several process roles. Which one this container is comes from
# $NEXUSLIMS_ROLE, so a deployment starts the same artifact three ways
# rather than building three images that could drift apart.
#
#   web     gunicorn, the API and admin                       (default)
#   worker  Celery worker: report PDFs, and the beat tasks
#   beat    Celery beat: schedules the retention sweep and the
#           training capacity check
#   migrate apply migrations and exit; for a platform with a
#           release/one-shot task
#
# Anything else is passed through and exec'd as given, so
# `docker run <image> python manage.py shell` still works.

set -eu

ROLE="${NEXUSLIMS_ROLE:-web}"

# Migrations run before web and worker start, under an advisory lock, so
# starting N replicas at once is safe -- see the deploy_migrate command for
# why that lock is there. Skippable for a deployment that runs migrations
# as its own release step and would rather this not touch the database.
#
# beat is deliberately excluded: it holds no schema of its own, and having
# the scheduler race the web tier to migrate buys nothing.
if [ "${NEXUSLIMS_MIGRATE_ON_START:-true}" = "true" ]; then
    case "$ROLE" in
        web|worker)
            echo "entrypoint: applying migrations before starting $ROLE"
            python manage.py deploy_migrate
            ;;
    esac
fi

case "$ROLE" in
    web)
        echo "entrypoint: starting gunicorn"
        exec gunicorn config.wsgi:application \
            --bind "0.0.0.0:${PORT:-8000}" \
            --workers "${GUNICORN_WORKERS:-3}" \
            --timeout "${GUNICORN_TIMEOUT:-60}" \
            --access-logfile - \
            --error-logfile -
        ;;

    worker)
        # --without-gossip/--without-mingle: both are worker-to-worker
        # chatter that buys nothing with a small fixed pool and costs a
        # slow, noisy startup. -Ofair stops a worker prefetching a queue of
        # tasks it will not get to, which matters here because report
        # rendering is slow and unevenly sized.
        echo "entrypoint: starting celery worker"
        exec celery -A config worker \
            --loglevel "${CELERY_LOG_LEVEL:-INFO}" \
            --concurrency "${CELERY_CONCURRENCY:-2}" \
            --without-gossip --without-mingle -Ofair
        ;;

    beat)
        # Exactly one replica. Beat is a scheduler, not a worker: two of
        # them both fire every entry, so the retention sweep would run
        # twice a night against the audit ledger. The schedule file records
        # when each entry last ran, and it is kept on a path that can be
        # mounted -- on ephemeral storage a restart makes beat re-evaluate
        # from scratch, which for a daily crontab entry means it may fire
        # again the same day.
        echo "entrypoint: starting celery beat (this must be a single replica)"
        exec celery -A config beat \
            --loglevel "${CELERY_LOG_LEVEL:-INFO}" \
            --schedule "${CELERY_BEAT_SCHEDULE_FILE:-/app/beat/celerybeat-schedule}"
        ;;

    migrate)
        echo "entrypoint: applying migrations and exiting"
        exec python manage.py deploy_migrate
        ;;

    *)
        exec "$@"
        ;;
esac
