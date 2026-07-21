"""
Celery application (Blueprint Section 2.1 item 4: Redis-backed async task
layer). Used today for the two scheduled beat tasks described in Blueprint
Section 7.4a (retention sweep) and Section 3.6/4.3 (training capacity
check) -- report generation and instrument file-parsing are also named in
the Blueprint as future Celery consumers but aren't built yet (no WeasyPrint
template pipeline or instrument ingestion exists in this codebase).
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("nasat_lims")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
