"""
Row-Level Security for `order_item`, extending the customer-visibility
boundary from `order` (migrations 0002, 0003) to the lines hanging off it.

An order line carries what a customer was charged, so it belongs inside the
same boundary as the order itself. Nothing in the portal reads it today --
the only viewset over it is staff-only -- and that is precisely why the
policy goes in now rather than later: apps/training/migrations/0002 exists
because two tables were reachable from the portal with nothing behind the
viewset's own `.filter()`, and one dropped filter was all that separated
them from disclosure. A policy written before the endpoint cannot be
forgotten when the endpoint arrives.

The policy joins through `order` rather than denormalising customer_id onto
the line, so re-pointing an order can never leave its lines visible to the
customer it used to belong to.

FORCE, as everywhere else here: without it the table owner -- the role the
application connects as -- bypasses its own policies, and ENABLE alone is a
silent no-op for every query the app makes.
"""

from django.db import migrations

ENABLE_RLS_SQL = """
ALTER TABLE order_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_item FORCE ROW LEVEL SECURITY;

CREATE POLICY staff_full_access_order_item ON order_item
    USING (current_setting('rls.is_staff', true) = 'true');

CREATE POLICY customer_own_order_items ON order_item
    USING (
        order_id IN (
            SELECT id FROM "order"
            WHERE customer_id = current_setting('rls.customer_id', true)::bigint
        )
    );
"""

DISABLE_RLS_SQL = """
DROP POLICY IF EXISTS customer_own_order_items ON order_item;
DROP POLICY IF EXISTS staff_full_access_order_item ON order_item;
ALTER TABLE order_item NO FORCE ROW LEVEL SECURITY;
ALTER TABLE order_item DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0004_historicalorderitem_orderitem_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=ENABLE_RLS_SQL, reverse_sql=DISABLE_RLS_SQL),
    ]
