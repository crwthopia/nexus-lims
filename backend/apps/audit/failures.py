"""
Recording system failures, per ISO/IEC 17025:2017 7.11.3(e).

The clause asks a laboratory information management system to "include
recording system failures and the appropriate immediate and corrective
actions". Everything here detected failures already; all of them went to
`logger` and stopped there. In a container the log stream *is* the log --
no file, no volume -- so a restart takes it, and "show me last quarter's
system failures" had no answer.

Two rules shape this module, and both are the difference between a failure
register and a second outage:

**Recording a failure must never cause one.** Every entry point swallows
everything and falls back to the logger. A recorder that raises turns a
degraded dependency into a 500, and turns a Celery task that failed once
into one that fails twice with the second traceback hiding the first.

**The recorder writes what the system did, not what someone should do.**
`immediate_action` is a fact about the moment of failure and is passed in by
the call site that knows it. `corrective_action` is left empty for a person,
and an open row with an empty corrective action is the point: it is
outstanding work that is visible rather than a silence.

What this cannot record, stated plainly: **a failure of Postgres itself.**
The register lives in the database, so when the database is the thing that
is down there is nowhere to write. The fallback is the log stream and the
`/readyz` probe, which is what an operator is watching in that scenario
anyway. A DB-backed failure register has this hole by construction; the
alternative -- shipping failures somewhere else entirely -- is a monitoring
system, not a compliance record, and NASAT should have both.
"""

import hashlib
import logging

from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)

_MAX_SUMMARY = 255
_MAX_DETAIL = 10_000


def fingerprint_for(component, summary):
    """
    Identity for deduplication: the component and the summary, nothing else.

    Which means the *summary* decides how coarsely failures coalesce, so a
    call site should keep the varying parts out of it -- "generate_report_pdf
    raised WeasyPrintError", not "report 412 failed". The report id belongs
    in `detail`. Get that backwards and one bad template produces a row per
    report instead of one row saying a template is broken.
    """
    return hashlib.sha256(f"{component}\x00{summary}".encode()).hexdigest()


def record_failure(component, summary, *, detail="", severity=None, immediate_action=None):
    """
    Record a system failure, coalescing into an already-open identical one.

    Returns the SystemFailure, or None if recording itself failed -- callers
    are not expected to check. Nothing here re-raises: see the module
    docstring.
    """
    # Imported inside the function so that importing this module cannot pull
    # in the app registry. apps/common/health.py imports it, and the
    # liveness/readiness probes must have the fewest import-time
    # dependencies of anything in the process.
    from apps.audit.models import SystemFailure

    severity = severity or SystemFailure.Severity.FAILED
    immediate_action = immediate_action or SystemFailure.ImmediateAction.NONE
    summary = (summary or "unspecified failure")[:_MAX_SUMMARY]
    detail = (detail or "")[:_MAX_DETAIL]

    try:
        now = timezone.now()
        fingerprint = fingerprint_for(component, summary)

        # Only open rows are candidates. Once a failure has been
        # acknowledged or closed, a recurrence gets its own row: a failure
        # coming back after somebody signed off a corrective action is the
        # most important thing this table can say, and folding it into the
        # closed row would say the opposite.
        #
        # QuerySet.update() rather than save(): it sends no signals, so a
        # counter moving during an outage writes no history rows. The
        # deliberate use of the caveat documented in apps/audit/signals.py --
        # see the SystemFailure docstring.
        coalesced = SystemFailure.objects.filter(
            fingerprint=fingerprint, status=SystemFailure.Status.OPEN,
        ).update(
            occurrences=models.F("occurrences") + 1,
            last_seen_at=now,
            severity=severity,
            immediate_action=immediate_action,
            detail=detail,
        )
        if coalesced:
            logger.warning(
                "system failure (recurring, %s): %s -- %s", component, summary, detail[:200],
            )
            return SystemFailure.objects.filter(
                fingerprint=fingerprint, status=SystemFailure.Status.OPEN,
            ).first()

        failure = SystemFailure.objects.create(
            fingerprint=fingerprint,
            component=component,
            severity=severity,
            summary=summary,
            detail=detail,
            immediate_action=immediate_action,
            last_seen_at=now,
        )
        logger.error("system failure (%s): %s -- %s", component, summary, detail[:200])
        return failure
    except Exception:
        # The whole point of the module docstring's first rule. If the
        # database is unreachable this is the expected path, not a surprise.
        logger.exception(
            "could not record system failure (%s): %s -- the failure itself was: %s",
            component, summary, detail[:200],
        )
        return None


def record_request_exception(sender=None, request=None, **kwargs):
    """
    Receiver for django.core.signals.got_request_exception: an unhandled
    exception during request handling is a system failure (7.11.3(e)).

    Connected in apps/audit/apps.py. Django sends this only for exceptions it
    could not turn into a response -- a 500, not a 400 or a refused delete
    (apps/common/exception_handler.py turns those into 409s before they ever
    reach here), so the register stays a record of the system breaking rather
    than of clients being told no.

    Deduplicates on the URL *route* rather than the path. `/api/v1/samples/
    412/` and `/api/v1/samples/998/` are one broken endpoint, and fingerprints
    built from paths would file them as two failures -- worse, an endpoint
    failing for every row would fill the register with one row per row.
    """
    import sys

    from apps.audit.models import SystemFailure

    exc_type, exc_value, _ = sys.exc_info()
    match = getattr(request, "resolver_match", None)
    route = getattr(match, "route", None) or "unresolved"
    method = getattr(request, "method", "?")

    record_failure(
        SystemFailure.Component.API_REQUEST,
        f"{method} {route} raised {exc_type.__name__ if exc_type else 'unknown'}",
        detail=f"{exc_value}",
        severity=SystemFailure.Severity.FAILED,
        immediate_action=SystemFailure.ImmediateAction.REQUEST_REJECTED,
    )
