#!/bin/sh
#
# Role-aware, because HEALTHCHECK is baked into the image and this image
# runs as web, worker or beat. An HTTP probe against a Celery worker would
# fail forever -- a worker listens on no port.
#
# Every check here is a liveness check: "is this process still working?"
# and never "are its dependencies up?". A healthcheck that fails on a Redis
# blip restarts the container, which fixes nothing and loses whatever the
# worker had in flight. See apps/common/health.py for the same argument
# about the web tier's two endpoints.

set -eu

ROLE="${NEXUSLIMS_ROLE:-web}"

case "$ROLE" in
    web)
        exec curl -fsS "http://localhost:${PORT:-8000}/healthz"
        ;;

    worker)
        # `inspect ping` asks this worker over the broker and waits for its
        # own reply, so it proves the process is consuming, not merely that
        # the PID exists. -d targets this node specifically; without it a
        # reply from any worker on the broker would satisfy the check, and
        # a wedged worker in a pool would look healthy.
        exec celery -A config inspect ping \
            -d "celery@$(hostname)" \
            --timeout "${CELERY_PING_TIMEOUT:-10}"
        ;;

    beat)
        # Beat answers no ping: it is a scheduler with no queue of its own.
        # The only local signal it is alive is that it is still writing its
        # schedule file. A stat is a weak check, and deliberately so -- the
        # alternative is asserting a task ran, which belongs in monitoring
        # rather than in a container healthcheck that restarts things.
        SCHEDULE="${CELERY_BEAT_SCHEDULE_FILE:-/app/beat/celerybeat-schedule}"
        for candidate in "$SCHEDULE" "$SCHEDULE.db" "$SCHEDULE.dat"; do
            if [ -f "$candidate" ]; then
                exit 0
            fi
        done
        echo "beat schedule file not found at $SCHEDULE" >&2
        exit 1
        ;;

    *)
        # An unrecognised role is a configuration error, and reporting
        # healthy would hide it.
        echo "no healthcheck defined for role '$ROLE'" >&2
        exit 1
        ;;
esac
