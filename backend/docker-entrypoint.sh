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
# A command passed to `docker run` wins over the role, so
# `docker run <image> python manage.py shell` runs the shell rather than
# starting a web server.

set -eu

# An explicit command wins over the role, and is checked before anything
# else so it runs against no assumptions at all.
#
# ENTRYPOINT makes every `docker run <image> <cmd>` arrive here as "$@". A
# role-first entrypoint therefore swallows the command and starts gunicorn
# instead -- which is exactly what happened to CI's
# `docker run <image> python manage.py check --deploy`: the default role
# ran deploy_migrate against a database that step deliberately does not
# provide, and the check never executed. `docker run <image> python
# manage.py shell` was broken the same way.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

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
        # An unrecognised role with no command to fall back on. Reaching
        # here means NEXUSLIMS_ROLE was set to something this script does
        # not know, which is a configuration error worth failing on rather
        # than quietly starting nothing.
        echo "entrypoint: unknown NEXUSLIMS_ROLE '$ROLE'" >&2
        exit 1
        ;;
esac
