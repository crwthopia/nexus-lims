"""
Holding times: when each analysis has to be finished by, and what that
deadline is counted from.

`holding_time` has been stored on both TestMethod and Sample since the
schema was written and used by nothing -- no due date, no ordering, no
alarm. It could not have been used before now, because until
Sample.received_at existed there was no anchor to count from. This module
is what turns those two stored durations into a control.

Three decisions are worth stating, because each could reasonably have gone
the other way and the wrong one is silently non-compliant:

**The clock starts at collection, not receipt.** APHA/EPA holding times are
specified from the time the sample was taken, not from the time it reached
the laboratory -- a bottle that spent two days in a courier's van has spent
two days of its holding time. Counting from receipt would hand every
analysis a deadline later than the real one, which is the exact direction
that produces a result the method does not support. `collection_datetime`
is nullable, so where it is absent we fall back to `received_at` and
*record that we did* (`due_at_basis`), because that deadline is optimistic
and anyone reading the worksheet needs to know it.

**The most restrictive duration wins.** Where both a method holding time
and a sample holding time are set they are not alternatives: the method's
comes from the analytical procedure, the sample's from its container and
preservation, and the item has to satisfy both. `min()` is the only answer
that does not quietly permit exceeding one of them.

**A retest does not restart the clock.** `due_at` is anchored to when the
sample was taken, and re-queueing a test does not un-take it. So nothing
here recomputes on `requeue_for_retest` or `resume_testing` -- a retest
that can no longer be run inside the holding time is a fact the worksheet
should show, not one to paper over by moving the deadline.
"""

from django.db import transaction

# Which statuses still have analytical work outstanding. A completed test
# has no deadline left to miss, and one parked under investigation is
# already being dealt with by a process that knows about it (7.10) -- so
# neither belongs in the sweep or in the overdue count.
OUTSTANDING_STATUSES = ("assigned", "in_progress", "retest_pending")


def effective_holding_time(sample, test_method):
    """
    The shorter of the method's holding time and the sample's, or None when
    neither is set.

    None is a legitimate answer, not a missing one: plenty of analyses --
    most of the Failure Analysis line -- have no holding time at all, and a
    fabricated default would put every one of them on a countdown nobody
    asked for.
    """
    candidates = [d for d in (getattr(test_method, "holding_time", None), sample.holding_time) if d is not None]
    return min(candidates) if candidates else None


def anchor_for(sample):
    """
    What the holding time counts from: `(datetime, basis)`.

    Returns `(None, "")` for a sample that has neither been collected at a
    recorded time nor received -- a pre-registration with nothing physical
    behind it yet, which has no deadline because it has no clock.
    """
    from apps.testing.models import TestRequest

    if sample.collection_datetime is not None:
        return sample.collection_datetime, TestRequest.DueBasis.COLLECTION
    if sample.received_at is not None:
        return sample.received_at, TestRequest.DueBasis.RECEIPT
    return None, ""


def due_at_for(test_request):
    """The `(due_at, basis)` this request should be carrying right now."""
    sample = test_request.sample
    duration = effective_holding_time(sample, test_request.test_method)
    if duration is None:
        return None, ""

    anchor, basis = anchor_for(sample)
    if anchor is None:
        return None, ""

    return anchor + duration, basis


def apply_to(test_request, *, save=True):
    """
    Recompute this request's deadline. Returns True if it changed.

    Idempotent, and called from every place that can move the inputs: a
    test request being created, a sample being received, a collection time
    being corrected. That is three call sites rather than one because the
    inputs genuinely arrive at three different moments -- a test request
    can be booked against a sample that has not turned up yet, and a sample
    can be received before anybody has said what to run on it.
    """
    due_at, basis = due_at_for(test_request)
    if (test_request.due_at, test_request.due_at_basis) == (due_at, basis):
        return False

    test_request.due_at = due_at
    test_request.due_at_basis = basis
    if save:
        test_request.save(update_fields=["due_at", "due_at_basis"])
    return True


@transaction.atomic
def apply_to_sample(sample):
    """
    Recompute every test request on `sample`. Returns how many changed.

    One query and a save per changed row rather than a bulk update: these
    are history-tracked rows (simple-history) and audited
    (apps/audit/signals.py), and a bulk update sends no signals -- so the
    deadline would move with nothing anywhere recording that it had. The
    same reasoning as apps/reporting/tasks.generate_report_pdf preferring
    save(update_fields=...) over QuerySet.update().
    """
    changed = 0
    for test_request in sample.test_requests.select_related("test_method", "sample"):
        # select_related("sample") so due_at_for's sample lookup does not
        # re-query per row; it is the same object either way.
        if apply_to(test_request):
            changed += 1
    return changed
