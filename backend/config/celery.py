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
from celery.signals import task_prerun

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
