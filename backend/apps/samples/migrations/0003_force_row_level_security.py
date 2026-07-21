"""
FORCE ROW LEVEL SECURITY on order/sample (closes a gap in
0002_row_level_security.py, Blueprint Section 2.1 item 3b).

PostgreSQL does not apply RLS policies to a table's owning role unless
FORCE ROW LEVEL SECURITY is set (superusers always bypass RLS regardless).
Django's app connection (the `nasat_lims` role) is also the role that ran
`migrate` and therefore owns `order`/`sample`, so without this migration
ENABLE ROW LEVEL SECURITY alone was a silent no-op for every query the
Django app itself makes -- the policies existed but never actually
restricted anything for the app's own connection.
"""

from django.db import migrations

FORCE_RLS_SQL = """
ALTER TABLE "order" FORCE ROW LEVEL SECURITY;
ALTER TABLE sample FORCE ROW LEVEL SECURITY;
"""

UNFORCE_RLS_SQL = """
ALTER TABLE sample NO FORCE ROW LEVEL SECURITY;
ALTER TABLE "order" NO FORCE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("samples", "0002_row_level_security"),
    ]

    operations = [
        migrations.RunSQL(sql=FORCE_RLS_SQL, reverse_sql=UNFORCE_RLS_SQL),
    ]
