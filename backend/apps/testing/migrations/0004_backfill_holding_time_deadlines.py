"""
Backfill TestRequest.due_at for work already in the building.

0003 adds the column as null, which is correct for a request whose sample
has no clock yet and wrong for the several hundred that already do: without
this, every analysis booked in before today would sit outside the
holding-time sweep forever, and the control would only ever cover work
received after the deploy. That is the failure mode where a feature looks
finished and quietly protects nothing.

The computation is duplicated here rather than imported from
apps/testing/holding_times.py, deliberately and against the usual instinct.
A migration is a statement about what the schema did on the day it ran, and
an imported helper is free to change afterwards -- at which point re-running
this migration on a fresh database would produce different data from the
one it produced in production. The rule it encodes (most restrictive
duration, anchored at collection where known and receipt otherwise) is
eight lines; the coupling is not worth saving them.

Requests whose sample has neither a collection time nor a receipt time, and
those whose method and sample both have no holding time, are left null.
That is the same answer the live code gives them, not a gap.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    TestRequest = apps.get_model("testing", "TestRequest")

    updated = []
    for test_request in TestRequest.objects.select_related("sample", "test_method").iterator():
        sample = test_request.sample

        durations = [
            d for d in (test_request.test_method.holding_time, sample.holding_time) if d is not None
        ]
        if not durations:
            continue

        if sample.collection_datetime is not None:
            anchor, basis = sample.collection_datetime, "collection"
        elif sample.received_at is not None:
            anchor, basis = sample.received_at, "receipt"
        else:
            continue

        test_request.due_at = anchor + min(durations)
        test_request.due_at_basis = basis
        updated.append(test_request)

    # bulk_update rather than a save() each: this is a backfill of a column
    # that did not exist a moment ago, so there is no prior value for
    # simple-history to record a change *from*, and nothing is served by
    # writing one history row per request for it. The live recomputation
    # path (holding_times.apply_to_sample) takes the opposite choice, for
    # the opposite reason -- there, the deadline moving is the event.
    TestRequest.objects.bulk_update(updated, ["due_at", "due_at_basis"], batch_size=500)


def unbackfill(apps, schema_editor):
    """No-op: reversing 0003 drops both columns, so there is nothing to undo."""


class Migration(migrations.Migration):
    dependencies = [
        ("testing", "0003_holding_time_deadlines"),
        # received_at is one of the two anchors this reads.
        ("samples", "0007_receipt_record_and_sample_identity"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
