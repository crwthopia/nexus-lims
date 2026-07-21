"""
Row-level security (Blueprint Section 2.1 item 3b) at two layers:

1. Through the real API (/my/orders/, /my/samples/) -- proves the whole
   request path (RLSContextMiddleware reading the session, the Postgres
   policies, and the view's own get_queryset scoping) works end to end.
2. Directly against the database connection, bypassing the ORM's own
   get_queryset() filtering entirely -- proves the *database* enforces the
   boundary regardless of application code, per README's "defense in depth"
   claim and the documented FORCE ROW LEVEL SECURITY fix
   (apps/samples/migrations/0003_force_row_level_security.py) that closed a
   real gap where ENABLE ROW LEVEL SECURITY alone was a silent no-op against
   the app's own (table-owning) connection role.
"""

import pytest
from django.db import connection

from tests.factories import CustomerUserFactory, OrderFactory, SampleFactory, StaffUserFactory

pytestmark = pytest.mark.django_db


def test_customer_sees_only_their_own_orders_and_samples_via_api(login_as_customer):
    customer_a = CustomerUserFactory()
    customer_b = CustomerUserFactory()
    order_a = OrderFactory(customer=customer_a)
    SampleFactory(order=order_a)
    order_b = OrderFactory(customer=customer_b)
    SampleFactory(order=order_b)

    client = login_as_customer(customer_a)

    orders_response = client.get("/api/v1/my/orders/")
    assert orders_response.status_code == 200
    order_ids = {o["id"] for o in orders_response.data["results"]}
    assert order_ids == {order_a.id}

    samples_response = client.get("/api/v1/my/samples/")
    assert samples_response.status_code == 200
    sample_order_ids = {s["order"] for s in samples_response.data["results"]}
    assert sample_order_ids == {order_a.id}


def test_staff_sees_all_orders_regardless_of_customer(login_as_staff):
    order_a = OrderFactory(customer=CustomerUserFactory())
    order_b = OrderFactory(customer=CustomerUserFactory())
    staff = StaffUserFactory()

    client = login_as_staff(staff)
    response = client.get("/api/v1/orders/")

    assert response.status_code == 200
    order_ids = {o["id"] for o in response.data["results"]}
    assert {order_a.id, order_b.id} <= order_ids


def test_rls_policy_enforced_at_database_level_directly():
    """
    Bypasses the Django ORM's own customer-scoping filter entirely: sets the
    RLS session variables by hand (exactly as RLSContextMiddleware does) and
    runs a raw SELECT against "order", proving the database itself -- not
    just app code -- restricts visibility.
    """
    customer_a = CustomerUserFactory()
    customer_b = CustomerUserFactory()
    order_a = OrderFactory(customer=customer_a)
    OrderFactory(customer=customer_b)

    with connection.cursor() as cursor:
        # Customer A's context: only their own order should be visible.
        cursor.execute(
            "SELECT set_config('rls.is_staff', 'false', false), set_config('rls.customer_id', %s, false)",
            [str(customer_a.id)],
        )
        cursor.execute('SELECT id FROM "order"')
        visible_ids = {row[0] for row in cursor.fetchall()}
        assert visible_ids == {order_a.id}

        # No RLS context at all (matches an unauthenticated/default-deny connection state).
        cursor.execute(
            "SELECT set_config('rls.is_staff', 'false', false), set_config('rls.customer_id', '0', false)"
        )
        cursor.execute('SELECT id FROM "order"')
        assert cursor.fetchall() == []

        # Staff bypass: rls.is_staff='true' sees everything regardless of customer_id.
        cursor.execute(
            "SELECT set_config('rls.is_staff', 'true', false), set_config('rls.customer_id', '0', false)"
        )
        cursor.execute('SELECT id FROM "order"')
        visible_ids = {row[0] for row in cursor.fetchall()}
        assert len(visible_ids) >= 2
