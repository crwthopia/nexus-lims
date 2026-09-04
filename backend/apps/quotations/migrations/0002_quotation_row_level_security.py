"""
Row-Level Security for `quotation` and `quotation_item`.

A quotation is a price offered to one named customer, which makes it the
most disclosure-sensitive row in the commercial chain: what one customer
was quoted is exactly what another must not see. The portal reads both
tables from the day they exist, so unlike `order_item` these policies are
not written ahead of an endpoint -- they are written alongside one.

`quotation` scopes on its own customer_id. `quotation_item` joins through
its quotation rather than denormalising the customer onto the line, so
re-pointing a quotation can never leave its lines visible to the customer
it used to belong to -- the same reasoning as order_item joining through
`order` (apps/samples/migrations/0005).

FORCE, as everywhere: without it the table owner -- the role the
application connects as -- bypasses its own policies, and ENABLE alone is a
silent no-op for every query the app makes.
"""

from django.db import migrations

ENABLE_RLS_SQL = """
ALTER TABLE quotation ENABLE ROW LEVEL SECURITY;
ALTER TABLE quotation FORCE ROW LEVEL SECURITY;
ALTER TABLE quotation_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE quotation_item FORCE ROW LEVEL SECURITY;

CREATE POLICY staff_full_access_quotation ON quotation
    USING (current_setting('rls.is_staff', true) = 'true');

CREATE POLICY staff_full_access_quotation_item ON quotation_item
    USING (current_setting('rls.is_staff', true) = 'true');

CREATE POLICY customer_own_quotations ON quotation
    USING (customer_id = current_setting('rls.customer_id', true)::bigint);

CREATE POLICY customer_own_quotation_items ON quotation_item
    USING (
        quotation_id IN (
            SELECT id FROM quotation
            WHERE customer_id = current_setting('rls.customer_id', true)::bigint
        )
    );
"""

DISABLE_RLS_SQL = """
DROP POLICY IF EXISTS customer_own_quotation_items ON quotation_item;
DROP POLICY IF EXISTS customer_own_quotations ON quotation;
DROP POLICY IF EXISTS staff_full_access_quotation_item ON quotation_item;
DROP POLICY IF EXISTS staff_full_access_quotation ON quotation;
ALTER TABLE quotation_item NO FORCE ROW LEVEL SECURITY;
ALTER TABLE quotation_item DISABLE ROW LEVEL SECURITY;
ALTER TABLE quotation NO FORCE ROW LEVEL SECURITY;
ALTER TABLE quotation DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("quotations", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=ENABLE_RLS_SQL, reverse_sql=DISABLE_RLS_SQL),
    ]
