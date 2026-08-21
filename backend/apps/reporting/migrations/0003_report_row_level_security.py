"""
Row-Level Security for `report`, extending the customer-visibility boundary
established for order/sample (apps/samples/migrations/0002, 0003) to the
documents those samples produce.

Added when the Customer Portal gained a reports route. Until then `report`
was staff-only, so the ORM filter in a viewset was the whole story. It isn't
any more: a customer-facing list endpoint filtered only in Python is one
dropped `.filter()` away from returning every customer's report metadata,
and the project's own answer to that everywhere else is a database policy
that holds regardless of what the application layer does
(tests/test_row_level_security.py asserts exactly this, against the raw
connection rather than through the ORM).

The policy reaches the customer through whichever parent the report hangs
off -- a COA joins `sample`, a training certificate joins `order` -- which
is why it is two subqueries rather than one column comparison. The check
constraint report_target_required guarantees at least one is non-null, so a
row can never be invisible to its own owner by having neither.

FORCE is set for the same reason as on order/sample: without it the table
owner (the role the application connects as) bypasses its own policies, and
enabling RLS would be a silent no-op for every query the app makes.
"""

from django.db import migrations

ENABLE_RLS_SQL = """
ALTER TABLE report ENABLE ROW LEVEL SECURITY;
ALTER TABLE report FORCE ROW LEVEL SECURITY;

CREATE POLICY staff_full_access_report ON report
    USING (current_setting('rls.is_staff', true) = 'true');

CREATE POLICY customer_own_reports ON report
    USING (
        sample_id IN (
            SELECT s.id FROM sample s
            JOIN "order" o ON o.id = s.order_id
            WHERE o.customer_id = current_setting('rls.customer_id', true)::bigint
        )
        OR order_id IN (
            SELECT id FROM "order"
            WHERE customer_id = current_setting('rls.customer_id', true)::bigint
        )
    );
"""

DISABLE_RLS_SQL = """
DROP POLICY IF EXISTS customer_own_reports ON report;
DROP POLICY IF EXISTS staff_full_access_report ON report;
ALTER TABLE report NO FORCE ROW LEVEL SECURITY;
ALTER TABLE report DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("reporting", "0002_historicalreport_failure_reason_and_more"),
        ("samples", "0003_force_row_level_security"),
    ]

    operations = [
        migrations.RunSQL(sql=ENABLE_RLS_SQL, reverse_sql=DISABLE_RLS_SQL),
    ]
