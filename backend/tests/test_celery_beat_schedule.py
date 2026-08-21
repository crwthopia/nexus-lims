"""
CELERY_BEAT_SCHEDULE wiring (Blueprint Section 7.4a, Section 3.6/4.3).

The task *logic* behind both scheduled entries is tested directly elsewhere
(test_audit_retention.py, test_training.py). What is tested here is the
string that connects the schedule to that logic, because getting it wrong
fails in the quietest way this system has:

beat dispatches by dotted name. A renamed module, a moved function, or a
typo produces a message no worker has a handler for. Beat keeps running,
the worker logs an unroutable task and moves on, every test still passes,
and no screen changes. You find out that the retention sweep has not run
for months during an audit, when records that should have been locked or
archived weren't.
"""

import pytest
from celery.schedules import crontab
from django.conf import settings

from config.celery import app as celery_app


@pytest.fixture(scope="module")
def registered_tasks():
    """
    Celery's autodiscovery is lazy -- app.autodiscover_tasks() registers a
    finder, and nothing is imported until the worker starts. Forcing the
    import here is what makes app.tasks a true picture of what a running
    worker would answer to.
    """
    celery_app.loader.import_default_modules()
    return set(celery_app.tasks)


def test_every_scheduled_entry_points_at_a_registered_task(registered_tasks):
    unresolved = {
        name: entry["task"]
        for name, entry in settings.CELERY_BEAT_SCHEDULE.items()
        if entry["task"] not in registered_tasks
    }

    assert not unresolved, (
        f"beat entries reference tasks no worker would answer to: {unresolved}. "
        f"A dispatch to one of these is silently dropped."
    )


def test_the_schedule_covers_both_blueprint_automations(registered_tasks):
    # Named explicitly rather than counted, so deleting an entry is a test
    # failure rather than a silently smaller schedule.
    scheduled = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}

    assert "apps.audit.tasks.run_retention_sweep" in scheduled
    assert "apps.training.tasks.check_session_capacity" in scheduled


def test_both_entries_run_daily_at_the_documented_hours():
    # The README tells operators these run at 02:00 and 03:00; this is what
    # keeps that claim true.
    schedule = settings.CELERY_BEAT_SCHEDULE

    retention = schedule["retention-sweep-daily"]["schedule"]
    capacity = schedule["training-capacity-check-daily"]["schedule"]

    assert isinstance(retention, crontab)
    assert isinstance(capacity, crontab)
    assert retention.hour == {2}
    assert capacity.hour == {3}
    # Staggered deliberately: both sweep large tables, and overlapping them
    # would double the load for no benefit.
    assert retention.hour != capacity.hour


def test_the_report_generation_task_is_registered(registered_tasks):
    # Dispatched by apps/reporting/tasks.enqueue_generation via .delay().
    # It carries an explicit name=, so a rename of the module would leave
    # the decorator's name pointing at nothing.
    assert "apps.reporting.tasks.generate_report_pdf" in registered_tasks
