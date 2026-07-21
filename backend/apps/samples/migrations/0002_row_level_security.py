"""
Row-Level Security policies for customer-visibility boundaries (Blueprint
Section 2.1 item 3b, Section 2.1 item 5): RLS enforces at the database
level, beneath the Django ORM's own query scoping, that a CustomerUser can
only ever see their own Order/Sample rows.

This depends on the django-rls RLSContextMiddleware (Section 2.1 item 3b)
issuing `SELECT set_config('rls.customer_id', %s, true)` on every
authenticated customer request, which these policies reference via
current_setting('rls.customer_id', true). Staff users bypass RLS entirely
via a separate policy that checks a session flag set only by staff-authenticated
requests (Entra ID), never by customer-authenticated requests.

NASAT's Phase 1 has only one tenant (Section 2.3), so no tenant_id policy is
included yet; the schema is multi-tenant-ready (a future migration would add
a tenant_id column and corresponding policy without touching these customer
policies) but only NASAT's own tenant record exists for now.
"""

from django.db import migrations

ENABLE_RLS_SQL = """
ALTER TABLE "order" ENABLE ROW LEVEL SECURITY;
ALTER TABLE sample ENABLE ROW LEVEL SECURITY;

-- Staff bypass: requests authenticated via Entra ID set rls.is_staff = 'true'
-- in RLSContextMiddleware; such connections see all rows.
CREATE POLICY staff_full_access_order ON "order"
    USING (current_setting('rls.is_staff', true) = 'true');

CREATE POLICY staff_full_access_sample ON sample
    USING (current_setting('rls.is_staff', true) = 'true');

-- Customer scoping: a customer-authenticated connection may only see rows
-- belonging to their own customer_id, set into rls.customer_id by the same
-- middleware for customer-portal requests.
CREATE POLICY customer_own_orders ON "order"
    USING (customer_id = current_setting('rls.customer_id', true)::bigint);

CREATE POLICY customer_own_samples ON sample
    USING (
        order_id IN (
            SELECT id FROM "order"
            WHERE customer_id = current_setting('rls.customer_id', true)::bigint
        )
    );
"""

DISABLE_RLS_SQL = """
DROP POLICY IF EXISTS customer_own_samples ON sample;
DROP POLICY IF EXISTS customer_own_orders ON "order";
DROP POLICY IF EXISTS staff_full_access_sample ON sample;
DROP POLICY IF EXISTS staff_full_access_order ON "order";
ALTER TABLE sample DISABLE ROW LEVEL SECURITY;
ALTER TABLE "order" DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("samples", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=ENABLE_RLS_SQL, reverse_sql=DISABLE_RLS_SQL),
    ]
