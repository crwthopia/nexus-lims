"""
Row-Level Security for `enrollment` and `credit_note`, extending the
customer-visibility boundary from order/sample (apps/samples/migrations
0002, 0003) and report (apps/reporting/migrations/0003) to the two
remaining customer-scoped tables in this app.

Both were reachable from the Customer Portal (GET /my/enrollments/,
GET /my/credit-notes/) with nothing behind the viewset's `.filter()`. A
probe over all six customer-facing endpoints confirmed the asymmetry
directly: with the customer filter deleted from each viewset in turn,
orders, samples and reports still leaked nothing -- their policies held --
while enrollments and credit notes returned another customer's rows from
both the list and the detail route. One dropped `.filter()` is all that
separated those two tables from disclosure, which is precisely the gap the
policies elsewhere in this project exist to close.

Both policies compare `customer_id` directly; neither table needs a join,
unlike `sample` (which reaches its customer through `order`) or `report`
(through either parent). A credit note is scoped by its own `customer_id`
rather than through `source_enrollment`, so re-pointing an enrollment can
never silently hand a credit note to a different customer.

FORCE is set for the same reason as everywhere else: without it the table
owner -- the role the application connects as -- bypasses its own policies,
and ENABLE alone would be a silent no-op for every query the app makes.
"""

from django.db import migrations

ENABLE_RLS_SQL = """
ALTER TABLE enrollment ENABLE ROW LEVEL SECURITY;
ALTER TABLE enrollment FORCE ROW LEVEL SECURITY;
ALTER TABLE credit_note ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_note FORCE ROW LEVEL SECURITY;

CREATE POLICY staff_full_access_enrollment ON enrollment
    USING (current_setting('rls.is_staff', true) = 'true');

CREATE POLICY staff_full_access_credit_note ON credit_note
    USING (current_setting('rls.is_staff', true) = 'true');

CREATE POLICY customer_own_enrollments ON enrollment
    USING (customer_id = current_setting('rls.customer_id', true)::bigint);

CREATE POLICY customer_own_credit_notes ON credit_note
    USING (customer_id = current_setting('rls.customer_id', true)::bigint);
"""

DISABLE_RLS_SQL = """
DROP POLICY IF EXISTS customer_own_credit_notes ON credit_note;
DROP POLICY IF EXISTS customer_own_enrollments ON enrollment;
DROP POLICY IF EXISTS staff_full_access_credit_note ON credit_note;
DROP POLICY IF EXISTS staff_full_access_enrollment ON enrollment;
ALTER TABLE credit_note NO FORCE ROW LEVEL SECURITY;
ALTER TABLE credit_note DISABLE ROW LEVEL SECURITY;
ALTER TABLE enrollment NO FORCE ROW LEVEL SECURITY;
ALTER TABLE enrollment DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("training", "0001_initial"),
        ("samples", "0003_force_row_level_security"),
    ]

    operations = [
        migrations.RunSQL(sql=ENABLE_RLS_SQL, reverse_sql=DISABLE_RLS_SQL),
    ]
