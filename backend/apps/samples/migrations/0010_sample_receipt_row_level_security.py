"""
Row-Level Security for `sample_receipt`, extending the customer-visibility
boundary from `sample` (migrations 0002, 0003) to the arrival record
hanging off it.

Written before any customer-facing endpoint reads this table, for the
reason migration 0005 sets out at length: a policy written before the
endpoint cannot be forgotten when the endpoint arrives, and the alternative
has already cost this codebase once.

It will arrive, too. Condition on receipt is not lab-internal trivia -- it
is what ISO/IEC 17025:2017 7.4.3 obliges the laboratory to disclose when a
deviation may have affected results, and the disclaimer it drives is
printed on the customer's own COA. A portal that shows a customer why their
result carries a caveat is a natural next step, and this is the policy it
will need.

The policy joins through `sample` to `order` rather than denormalising
customer_id, matching the two-subquery shape already used for `sample`
itself: re-pointing a sample can never leave its receipt visible to the
customer it used to belong to.

FORCE, as everywhere else here: without it the table owner -- the role the
application connects as -- bypasses its own policies, and ENABLE alone is a
silent no-op for every query the app makes.
"""

from django.db import migrations

ENABLE_RLS_SQL = """
ALTER TABLE sample_receipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE sample_receipt FORCE ROW LEVEL SECURITY;

CREATE POLICY staff_full_access_sample_receipt ON sample_receipt
    USING (current_setting('rls.is_staff', true) = 'true');

CREATE POLICY customer_own_sample_receipts ON sample_receipt
    USING (
        sample_id IN (
            SELECT id FROM sample
            WHERE order_id IN (
                SELECT id FROM "order"
                WHERE customer_id = current_setting('rls.customer_id', true)::bigint
            )
        )
    );
"""

DISABLE_RLS_SQL = """
DROP POLICY IF EXISTS customer_own_sample_receipts ON sample_receipt;
DROP POLICY IF EXISTS staff_full_access_sample_receipt ON sample_receipt;
ALTER TABLE sample_receipt NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sample_receipt DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0009_sample_code_immutable"),
    ]

    operations = [
        migrations.RunSQL(sql=ENABLE_RLS_SQL, reverse_sql=DISABLE_RLS_SQL),
    ]
