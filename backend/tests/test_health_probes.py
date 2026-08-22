"""
Liveness and readiness.

The distinction these two endpoints draw is the reason they are worth
testing. /healthz must never depend on Postgres or Redis: a load balancer
uses it to decide whether an instance stays in rotation, so if it checked
dependencies, one slow database would take every instance out at the same
moment and turn a partial degradation into a total outage. /readyz is where
dependency checking belongs, and it has to report *which* dependency failed
or it tells an operator nothing the 503 did not already.
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.django_db


def test_liveness_is_ok(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_does_not_touch_any_dependency(client):
    # The guard against someone "improving" /healthz into a deep check.
    # Every dependency check is made to explode; liveness must not call any
    # of them, so it must still answer 200.
    with patch("apps.common.health._check_database", side_effect=AssertionError("touched the database")), \
         patch("apps.common.health._check_redis", side_effect=AssertionError("touched redis")):
        response = client.get("/healthz")

    assert response.status_code == 200


def test_liveness_answers_when_the_database_is_actually_down(client):
    """
    The regression this exists for, and the one the unit tests above missed.

    Patching the view's own helpers proves the *view* does not query. It
    says nothing about the middleware stack in front of it, and
    RLSContextMiddleware opened a cursor on every request -- so in a real
    outage /healthz returned 500, not 200, and a load balancer would have
    pulled every instance during exactly the incident liveness is meant to
    survive. CI caught it by booting the container with no Postgres; this
    catches it without one.

    Patched at the module the middleware imports, so the whole request path
    is exercised rather than just the handler.
    """
    from django.db.utils import OperationalError

    broken = MagicMock()
    broken.cursor.side_effect = OperationalError("connection refused")

    with patch("apps.accounts.middleware.connection", broken):
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    broken.cursor.assert_not_called()


def test_readiness_reports_a_down_database_rather_than_500ing_in_middleware(client):
    # Same stack, the other probe: readiness must reach its own checks and
    # report a clean 503, not blow up in middleware first.
    from django.db.utils import OperationalError

    broken = MagicMock()
    broken.cursor.side_effect = OperationalError("connection refused")

    with patch("apps.accounts.middleware.connection", broken), \
         patch("apps.common.health._check_database", side_effect=OperationalError("connection refused")), \
         patch("apps.common.health._check_redis", return_value=None):
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"


def test_readiness_is_ok_when_everything_answers(client):
    with patch("apps.common.health._check_redis", return_value=None):
        response = client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


def test_readiness_names_the_dependency_that_failed(client):
    with patch("apps.common.health._check_redis", side_effect=ConnectionError("refused")):
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    # Database still ok, redis named: the entire point of the endpoint.
    assert body["checks"] == {"database": "ok", "redis": "unavailable"}


def test_readiness_reports_a_database_failure_rather_than_500ing(client):
    # A readiness probe that raises is useless: the caller cannot tell an
    # unreachable database from a crashed application.
    with patch("apps.common.health._check_database", side_effect=Exception("connection refused")), \
         patch("apps.common.health._check_redis", return_value=None):
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"


def test_readiness_leaks_nothing_about_the_failure(client):
    # Unauthenticated, because a load balancer cannot log in -- so the
    # exception text goes to the log and never to the response body.
    secret = "postgres://admin:hunter2@rds-internal.example:5432/prod"
    with patch("apps.common.health._check_redis", side_effect=Exception(secret)):
        response = client.get("/readyz")

    body = response.content.decode()
    assert "hunter2" not in body
    assert "rds-internal" not in body


def test_the_probes_need_no_authentication(client):
    # No session, no token, no CSRF. Asserted because a global permission
    # default would silently break both, and a load balancer would then
    # take the whole deployment out of rotation.
    assert client.get("/healthz").status_code == 200
    with patch("apps.common.health._check_redis", return_value=None):
        assert client.get("/readyz").status_code == 200
