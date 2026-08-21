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

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("nasat_lims")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
