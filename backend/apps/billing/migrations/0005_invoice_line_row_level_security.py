"""
Row-Level Security for `invoice_line`, extending the boundary already
around `invoice` (migration 0002) to the breakdown beneath it.

This one *is* customer-facing: a customer reading their invoice should see
what they are being charged for, and the portal serialises the lines with
the invoice. That nesting is scoped by the parent invoice today, but the
scoping is a viewset detail, and a viewset detail is exactly the kind of
thing that gets refactored. The policy repeats the invoice's own join --
through `order` or through `enrollment`, whichever the invoice references
-- so a line is visible on the same terms as the invoice it belongs to and
on no others.
"""

from django.db import migrations

ENABLE_RLS_SQL = """
ALTER TABLE invoice_line ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_line FORCE ROW LEVEL SECURITY;

CREATE POLICY staff_full_access_invoice_line ON invoice_line
    USING (current_setting('rls.is_staff', true) = 'true');

CREATE POLICY customer_own_invoice_lines ON invoice_line
    USING (
        invoice_id IN (
            SELECT id FROM invoice
            WHERE order_id IN (
                    SELECT id FROM "order"
                    WHERE customer_id = current_setting('rls.customer_id', true)::bigint
                )
               OR enrollment_id IN (
                    SELECT id FROM enrollment
                    WHERE customer_id = current_setting('rls.customer_id', true)::bigint
                )
        )
    );
"""

DISABLE_RLS_SQL = """
DROP POLICY IF EXISTS customer_own_invoice_lines ON invoice_line;
DROP POLICY IF EXISTS staff_full_access_invoice_line ON invoice_line;
ALTER TABLE invoice_line NO FORCE ROW LEVEL SECURITY;
ALTER TABLE invoice_line DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0004_historicalinvoiceline_order_item_invoiceline_invoice_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=ENABLE_RLS_SQL, reverse_sql=DISABLE_RLS_SQL),
    ]
