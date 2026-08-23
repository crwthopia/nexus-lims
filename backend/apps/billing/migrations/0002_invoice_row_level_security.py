"""
Row-Level Security for `invoice`, completing the customer-visibility
boundary across every table the Customer Portal can reach.

`invoice` was the sharpest case found while probing the six customer-facing
endpoints. Deleting the customer filter from CustomerInvoiceViewSet
produced two different outcomes from the same viewset, depending only on
which parent the invoice hung off:

  * an order-backed invoice did not leak, but 500'd -- the row escaped the
    queryset and the serializer then raised Order.DoesNotExist, because
    `order`'s policy hid the parent it needed to render. Protected, but by
    accident, and loudly.
  * an enrollment-backed invoice returned 200 with another customer's
    financial record, because `enrollment` had no policy behind it.

That split was a coincidence of which tables happened to get policies
first, not a design. This makes it deliberate for both.

The policy mirrors the viewset's own Q(order__customer) | Q(enrollment__customer)
because an Invoice reaches its customer through either parent -- the
check constraint invoice_target_required guarantees at least one is
non-null, so no row can be invisible to its own owner by having neither.
The subqueries read `order` and `enrollment`, which carry policies of their
own; that nests correctly and is the same shape the `report` policy has
used since apps/reporting/migrations/0003.

Note the constraint permits *both* parents to be set at once, so an invoice
linking one customer's order to another's enrollment is visible to both
customers under this policy, exactly as it already was through the
viewset. That needs data no code path creates today; tightening it is a
constraint change, not a policy one, and is left alone here rather than
silently narrowing what staff can record.

`payment` is deliberately not covered: it has no customer-facing route, so
its exposure is a staff-permissions question rather than a tenancy one.
"""

from django.db import migrations

ENABLE_RLS_SQL = """
ALTER TABLE invoice ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice FORCE ROW LEVEL SECURITY;

CREATE POLICY staff_full_access_invoice ON invoice
    USING (current_setting('rls.is_staff', true) = 'true');

CREATE POLICY customer_own_invoices ON invoice
    USING (
        order_id IN (
            SELECT id FROM "order"
            WHERE customer_id = current_setting('rls.customer_id', true)::bigint
        )
        OR enrollment_id IN (
            SELECT id FROM enrollment
            WHERE customer_id = current_setting('rls.customer_id', true)::bigint
        )
    );
"""

DISABLE_RLS_SQL = """
DROP POLICY IF EXISTS customer_own_invoices ON invoice;
DROP POLICY IF EXISTS staff_full_access_invoice ON invoice;
ALTER TABLE invoice NO FORCE ROW LEVEL SECURITY;
ALTER TABLE invoice DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0001_initial"),
        ("training", "0002_training_row_level_security"),
    ]

    operations = [
        migrations.RunSQL(sql=ENABLE_RLS_SQL, reverse_sql=DISABLE_RLS_SQL),
    ]
