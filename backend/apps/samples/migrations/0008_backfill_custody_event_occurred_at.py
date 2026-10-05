"""
Backfill ChainOfCustodyEvent.occurred_at from the row's write time.

0007 adds the column with `default=timezone.now`, which is the right
default for new rows and exactly the wrong value for old ones: it would
stamp every custody event ever recorded with the minute the migration ran,
collapsing years of timeline onto one instant.

`timestamp` is the only honest answer available for a historical row. It is
when the record was written, which for events created before this column
existed is also the closest thing to when they happened -- the two only
diverge once operators can backdate, and nobody could until now.

The historical table gets the same treatment, so a simple-history diff of
an old event does not show occurred_at leaping from a fabricated value.
"""

from django.db import migrations, models


def backfill(apps, schema_editor):
    for model_name in ("ChainOfCustodyEvent", "HistoricalChainOfCustodyEvent"):
        model = apps.get_model("samples", model_name)
        # A single UPDATE rather than a Python loop: this table grows one
        # row per custody handover for the life of the laboratory, and the
        # loop version is the kind of migration that times out in year three.
        model.objects.update(occurred_at=models.F("timestamp"))


def unbackfill(apps, schema_editor):
    """
    Deliberately a no-op rather than an error.

    Reversing 0007 drops the column outright, so there is nothing here to
    undo; raising would only make an otherwise-clean rollback fail.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0007_receipt_record_and_sample_identity"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
