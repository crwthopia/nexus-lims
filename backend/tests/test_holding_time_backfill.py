"""
The holding-time backfill (apps/testing/migrations/0004).

A data migration is the one kind of code that runs exactly once, against
data nobody looked at first, and then never again -- so a bug in it is only
ever observed as wrong numbers months later, by which point the migration
has been applied everywhere and cannot simply be fixed and re-run.

0004 exists because without it the holding-time control would only ever
cover work received after the deploy: every analysis already in the
building would sit outside the sweep forever, which is the failure mode
where a feature looks finished and quietly protects nothing.

This calls the migration's own `backfill` function against rows shaped like
the ones it will meet, rather than migrating a test database backwards and
forwards -- pytest-django has already run every migration to build the
schema, and re-running this one over ORM-created rows exercises the same
code on the same shapes without a second database. It passes the real app
registry, which is what the migration sees anyway on the last migration in
the chain.

The rule under test is deliberately duplicated between the migration and
apps/testing/holding_times.py (see the migration's docstring for why), so
these assertions are also what stops the two drifting apart unnoticed.
"""

import datetime
from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.samples.models import Sample
from apps.testing.models import TestRequest
from tests.factories import SampleFactory, TestMethodFactory, TestRequestFactory
from tests.helpers import reload

pytestmark = pytest.mark.django_db

HOURS_24 = datetime.timedelta(hours=24)
HOURS_48 = datetime.timedelta(hours=48)

backfill = import_module("apps.testing.migrations.0004_backfill_holding_time_deadlines").backfill


def _run_backfill():
    """Migration functions take (apps, schema_editor); only the first is used here."""
    backfill(django_apps, None)


def _undated(sample, holding_time):
    """A request as it looks before the backfill: no deadline, whatever its sample says."""
    test_request = TestRequestFactory(sample=sample, test_method=TestMethodFactory(holding_time=holding_time))
    TestRequest.objects.filter(pk=test_request.pk).update(due_at=None, due_at_basis="")
    return test_request


def test_it_dates_work_already_in_the_building():
    collected = timezone.now() - datetime.timedelta(hours=10)
    sample = SampleFactory(
        status=Sample.Status.IN_TESTING,
        collection_datetime=collected,
        received_at=timezone.now() - datetime.timedelta(hours=8),
    )
    test_request = _undated(sample, HOURS_24)

    _run_backfill()

    test_request = reload(test_request)
    assert test_request.due_at == collected + HOURS_24
    assert test_request.due_at_basis == "collection"


def test_it_falls_back_to_receipt_and_records_that_it_did():
    received = timezone.now() - datetime.timedelta(hours=8)
    sample = SampleFactory(
        status=Sample.Status.IN_TESTING, collection_datetime=None, received_at=received,
    )
    test_request = _undated(sample, HOURS_24)

    _run_backfill()

    test_request = reload(test_request)
    assert test_request.due_at == received + HOURS_24
    assert test_request.due_at_basis == "receipt"


def test_it_applies_the_shorter_of_the_two_durations():
    """The same rule as the live code -- this is what catches the two drifting apart."""
    collected = timezone.now()
    sample = SampleFactory(
        status=Sample.Status.IN_TESTING, collection_datetime=collected, holding_time=HOURS_24,
    )
    test_request = _undated(sample, HOURS_48)

    _run_backfill()

    assert reload(test_request).due_at == collected + HOURS_24


def test_it_leaves_a_request_with_no_holding_time_alone():
    sample = SampleFactory(status=Sample.Status.IN_TESTING, collection_datetime=timezone.now())
    test_request = _undated(sample, None)

    _run_backfill()

    assert reload(test_request).due_at is None
    assert reload(test_request).due_at_basis == ""


def test_it_leaves_a_sample_with_no_clock_alone():
    sample = SampleFactory(
        status=Sample.Status.PRE_REGISTERED, collection_datetime=None, received_at=None,
    )
    test_request = _undated(sample, HOURS_24)

    _run_backfill()

    assert reload(test_request).due_at is None


def test_it_is_safe_to_run_twice():
    """
    Not a property the migration framework needs, but one a data migration
    should have anyway: these get re-run by hand during incident recovery.
    """
    collected = timezone.now()
    sample = SampleFactory(status=Sample.Status.IN_TESTING, collection_datetime=collected)
    test_request = _undated(sample, HOURS_24)

    _run_backfill()
    _run_backfill()

    assert reload(test_request).due_at == collected + HOURS_24
