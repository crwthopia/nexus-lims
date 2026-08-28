"""
Celery application (Blueprint Section 2.1 item 4: Redis-backed async task
layer). What uses it today:

  - the two scheduled beat tasks, Blueprint Section 7.4a (retention sweep)
    and Section 3.6/4.3 (training capacity check), wired in
    config/settings.CELERY_BEAT_SCHEDULE;
  - report PDF generation (apps/reporting/tasks.py), dispatched per request
    rather than on a schedule.

Instrument file-parsing is named in the Blueprint alongside these but is
deliberately *not* a Celery consumer: an analyst uploading an export is
waiting on the answer, so it runs inside the request. See the Instrument
raw-data ingestion section of the root README.
"""

import os

from celery import Celery
from celery.signals import task_failure, task_prerun

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("nasat_lims")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@task_prerun.connect
def _set_rls_context(**kwargs):
    """
    The worker-side counterpart to RLSContextMiddleware.

    A worker connection has no RLS session variables unless something sets
    them, and the policies fail closed, so without this every RLS-protected
    table reads as empty inside a task -- see apps/common/rls.py for the
    full account. Wired as a signal rather than a decorator so a task added
    later cannot forget it.

    Set on every task rather than once per connection: Celery reuses
    connections across tasks, and re-setting is a single cheap statement
    against being wrong about a connection's history.
    """
    from apps.audit.context import set_actor
    from apps.common.rls import apply_system_rls_context

    apply_system_rls_context()
    # The audit counterpart, set here for the same reason: a task writing to
    # a regulated entity is the lab acting on its own behalf, and
    # apps/audit/signals.py needs something to name in the row. Not reset
    # afterwards -- a worker process has no caller to restore the previous
    # actor for, and the next task overwrites it before doing any work.
    set_actor("system", None)


# Which subsystem a failing task belongs to. Anything not named here is a
# scheduled task, which is what the two beat entries are; the mapping exists
# so the failure register reads as subsystems rather than as dotted paths.
_TASK_COMPONENTS = {
    "apps.reporting.tasks.generate_report_pdf": ("report_generation", "marked_failed"),
    "apps.audit.tasks.run_retention_sweep": ("retention_sweep", "none"),
    # The send task marks the NotificationRecord failed before re-raising, so
    # the row says what happened as well as the register.
    #
    # This is the loop worth being explicit about: an email failure becomes a
    # SystemFailure, and a new SystemFailure normally sends an email. It does
    # not recurse, because apps/notifications/tasks.notify_system_failure
    # refuses to send for the EMAIL component at all -- see the comment there.
    "apps.notifications.tasks.send_notification": ("email", "marked_failed"),
}


@task_failure.connect
def _record_task_failure(sender=None, task_id=None, exception=None, einfo=None, **kwargs):
    """
    Every Celery task failure lands in the SystemFailure register
    (ISO/IEC 17025:2017 7.11.3(e)).

    Wired as a signal for the same reason _set_rls_context above is: a task
    added later cannot forget it. It also means the call sites that already
    handle their own failures do not have to record as well -- they mark
    their row and re-raise, and re-raising is what brings them here. Doing
    both would put two rows in the register for one failure.

    The summary deliberately carries the task name and the exception type
    and nothing else: those are stable across occurrences, so one broken
    template is one row that counts up rather than a row per report. The
    task id, arguments and traceback go in the detail, where varying is
    fine. See apps/audit/failures.fingerprint_for.
    """
    from apps.audit.failures import record_failure
    from apps.audit.models import SystemFailure

    task_name = getattr(sender, "name", None) or "unknown task"
    component, immediate_action = _TASK_COMPONENTS.get(
        task_name, (SystemFailure.Component.SCHEDULED_TASK, SystemFailure.ImmediateAction.NONE),
    )

    record_failure(
        component,
        f"{task_name} raised {type(exception).__name__}",
        detail=f"task_id={task_id}\n{einfo}" if einfo else f"task_id={task_id}\n{exception}",
        severity=SystemFailure.Severity.FAILED,
        immediate_action=immediate_action,
    )
