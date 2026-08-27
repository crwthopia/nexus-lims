"""
Liveness and readiness probes.

Two endpoints, not one, and the distinction is the whole point.

`/healthz` answers "is this process alive?" and checks nothing else. A load
balancer uses it to decide whether to keep an instance in rotation, so it
must not depend on Postgres or Redis: if it did, one slow database would
make every instance report unhealthy at the same moment, and a partial
degradation would become a total outage. That is the classic way a health
check causes the incident it was added to prevent.

`/readyz` answers "can this process actually serve traffic?" and does check
both, so a deployment can wait for its dependencies before real requests
arrive, and so an operator has one URL that distinguishes "the app is
broken" from "the database is unreachable".

Neither requires authentication -- a load balancer cannot authenticate --
so neither reveals anything beyond which dependency is down. No versions,
no hostnames, no connection strings.
"""

import logging

from django.conf import settings
from django.db import connection
from django.http import JsonResponse

from apps.audit.failures import record_failure

logger = logging.getLogger(__name__)

# Resolved as plain strings rather than by importing SystemFailure: this
# module is imported by config/urls.py at startup and the probes must not
# depend on the model layer being importable. The values are the
# SystemFailure.Component / ImmediateAction members, and
# tests/test_system_failures.py pins them to the enums so a rename cannot
# leave a string here pointing at nothing.
_COMPONENTS = {"database": "database", "redis": "task_broker"}
_REMOVED_FROM_ROTATION = "removed_from_rotation"


def healthz(_request):
    """Liveness. If Python is running this, the answer is yes."""
    return JsonResponse({"status": "ok"})


def _check_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()


def _check_redis():
    # Imported here rather than at module scope so that /healthz keeps
    # working even if the redis package is somehow unimportable: the
    # liveness probe must have no dependency that this one could break.
    import redis

    client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2)
    try:
        client.ping()
    finally:
        client.close()


def readyz(_request):
    """Readiness. 200 only if every dependency answered."""
    # The pairs are built here rather than at module scope on purpose: a
    # module-level dict captures the function objects at import time, so a
    # test patching apps.common.health._check_redis would rebind the module
    # attribute while this loop went on calling the original. The test
    # passes, having verified nothing. Resolving the names inside the
    # function makes the lookup late-bound, and the patch real.
    checks = (("database", _check_database), ("redis", _check_redis))

    results = {}
    healthy = True

    for name, check in checks:
        try:
            check()
            results[name] = "ok"
        except Exception as exc:
            # Logged in full for the operator; the response says only which
            # dependency failed, since this endpoint is unauthenticated.
            logger.warning("Readiness check %r failed: %s", name, exc, exc_info=True)
            # And recorded, per ISO/IEC 17025:2017 7.11.3(e). A load balancer
            # probes this every few seconds, so an outage would be thousands
            # of rows without the deduplication in apps/audit/failures.py --
            # which is why the summary names the dependency and the
            # exception type only, and the message goes in the detail.
            #
            # When `name` is "database" this is the one failure the register
            # cannot record, because the register is in the database.
            # record_failure falls back to the log and returns None; the
            # probe still answers 503, which is what an operator is watching
            # in that case anyway. See the failures module docstring.
            record_failure(
                _COMPONENTS[name],
                f"readiness check {name!r} failed with {type(exc).__name__}",
                detail=str(exc),
                immediate_action=_REMOVED_FROM_ROTATION,
            )
            results[name] = "unavailable"
            healthy = False

    return JsonResponse(
        {"status": "ok" if healthy else "degraded", "checks": results},
        status=200 if healthy else 503,
    )
