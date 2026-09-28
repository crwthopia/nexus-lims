"""
Row-Level Security for `label_print_event`, extending the customer-
visibility boundary from `sample` (migrations 0002, 0003) and
`sample_receipt` (0010) to the record of what was printed onto a container.

Written before any customer-facing endpoint reads it, for the reason
migration 0005 sets out: a policy written before the endpoint cannot be
forgotten when the endpoint arrives, and this codebase has already paid for
the alternative once.

Whether a customer should ever see this is genuinely arguable -- who
printed a sticker is lab-internal housekeeping in a way a condition-on-
receipt record is not. The policy exists anyway, because the cost of
being wrong runs one way: a table left outside the boundary is one dropped
`.filter()` away from disclosure, and the cost of a policy nothing reads is
nothing at all.

The join runs through whichever parent the event hangs off, mirroring the
three-target shape of the row itself: a container label reaches the
customer through its sample, a job order sheet directly through its order,
and a worksheet label through its test request's sample.
"""

from django.db import migrations

ENABLE_RLS_SQL = """
ALTER TABLE label_print_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE label_print_event FORCE ROW LEVEL SECURITY;

CREATE POLICY staff_full_access_label_print_event ON label_print_event
    USING (current_setting('rls.is_staff', true) = 'true');

CREATE POLICY customer_own_label_print_events ON label_print_event
    USING (
        sample_id IN (
            SELECT id FROM sample
            WHERE order_id IN (
                SELECT id FROM "order"
                WHERE customer_id = current_setting('rls.customer_id', true)::bigint
            )
        )
        OR order_id IN (
            SELECT id FROM "order"
            WHERE customer_id = current_setting('rls.customer_id', true)::bigint
        )
        OR test_request_id IN (
            SELECT tr.id FROM test_request tr
            JOIN sample s ON s.id = tr.sample_id
            WHERE s.order_id IN (
                SELECT id FROM "order"
                WHERE customer_id = current_setting('rls.customer_id', true)::bigint
            )
        )
    );
"""

DISABLE_RLS_SQL = """
DROP POLICY IF EXISTS customer_own_label_print_events ON label_print_event;
DROP POLICY IF EXISTS staff_full_access_label_print_event ON label_print_event;
ALTER TABLE label_print_event NO FORCE ROW LEVEL SECURITY;
ALTER TABLE label_print_event DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0012_label_print_event"),
        # test_request is joined by the third branch of the policy.
        ("testing", "0004_backfill_holding_time_deadlines"),
    ]

    operations = [
        migrations.RunSQL(sql=ENABLE_RLS_SQL, reverse_sql=DISABLE_RLS_SQL),
    ]
