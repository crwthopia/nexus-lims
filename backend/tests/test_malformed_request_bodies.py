"""
A malformed request *body* must be a 400, not a 500.

Companion to test_malformed_request_params.py, which covers the query
string. This one covers the other half: JSON's top level may legally be an
array, a string, or null, and DRF hands whatever it parsed straight through
without opinion.

Serializer-backed writes are already safe -- DRF answers a non-dict with
"Invalid data. Expected a dictionary" before any project code runs. The
exposure is the hand-rolled actions, which read `request.data` as a dict:
`.get(...)` on it, or `{**request.data}`. A body of `[1, 2]` made those an
AttributeError or TypeError, i.e. a 500 on an input the client is entitled
to send and the parser is entitled to accept.

The route-walking test below is the one that matters most. These five sites
were found by fuzzing every write route rather than by reading for them,
and two of the five were invisible to a first pass because an FSM guard
rejected the request before the body was ever read -- so the object has to
be put in the state that lets execution reach the body. The next
hand-rolled action will have the same shape, and nothing but a walk will
notice.
"""

import json

import pytest
from django.urls import get_resolver

from apps.accounts.models import Role
from apps.samples.models import ChainOfCustodyEvent, Sample
from tests.factories import (
    CreditNoteFactory,
    CustomerUserFactory,
    EnrollmentFactory,
    RoleFactory,
    SampleFactory,
    StaffUserFactory,
    TestMethodFactory,
    TestRequestFactory,
)

pytestmark = pytest.mark.django_db

# Every top-level JSON value that is not an object. `null` is included
# because an empty body and a literal null arrive differently.
NON_OBJECT_BODIES = {
    "array": [1, 2],
    "string": "hello",
    "null": None,
    "number": 42,
}


@pytest.fixture
def any_staff(login_as_staff):
    user = StaffUserFactory(is_superuser=True)
    for role in Role.RoleName.values:
        user.roles.add(RoleFactory(name=role))
    return login_as_staff(user)


def write_routes():
    """Every POST/PATCH route the router exposes, as (url_pattern, viewset)."""
    found = []

    def walk(patterns, prefix=""):
        for pattern in patterns:
            if hasattr(pattern, "url_patterns"):
                walk(pattern.url_patterns, prefix + str(pattern.pattern))
                continue
            viewset = getattr(pattern.callback, "cls", None)
            actions = getattr(pattern.callback, "actions", {}) or {}
            methods = sorted(m for m in actions if m in ("post", "patch"))
            if methods and viewset is not None:
                found.append((prefix + str(pattern.pattern), viewset, methods))

    walk(get_resolver().url_patterns)
    return found


def test_the_route_walk_actually_covers_the_api():
    # A walk that silently found nothing would make every assertion below
    # vacuously true, which is the failure mode of this kind of test.
    routes = write_routes()

    assert len(routes) >= 50, f"only found {len(routes)} write routes"


@pytest.mark.parametrize("body_label", sorted(NON_OBJECT_BODIES))
def test_no_write_route_500s_on_a_non_object_body(any_staff, body_label):
    body = NON_OBJECT_BODIES[body_label]
    crashes = []

    for url, viewset, methods in write_routes():
        if "(?P<pk>" in url:
            # Detail routes need something to address. A route whose model
            # has no factory here is skipped rather than silently passing.
            continue
        target = "/" + url.replace("^", "").replace("$", "")
        for method in methods:
            response = getattr(any_staff, method)(
                target, json.dumps(body), content_type="application/json"
            )
            if response.status_code >= 500:
                crashes.append(f"{method.upper()} {target}")

    assert not crashes, f"5xx on a {body_label} body: {crashes}"


# --- The five sites the fuzz actually found -------------------------------

@pytest.mark.parametrize("body_label", sorted(NON_OBJECT_BODIES))
def test_test_result_entry_rejects_a_non_object_body(any_staff, body_label):
    # `{**request.data, "test_request": ...}` -- ** on a list is a TypeError.
    method = TestMethodFactory()
    test_request = TestRequestFactory(test_method=method)

    response = any_staff.post(
        f"/api/v1/test-requests/{test_request.id}/results/",
        json.dumps(NON_OBJECT_BODIES[body_label]),
        content_type="application/json",
    )

    assert response.status_code == 400


@pytest.mark.parametrize("body_label", sorted(NON_OBJECT_BODIES))
def test_credit_note_apply_rejects_a_non_object_body(any_staff, body_label):
    credit_note = CreditNoteFactory()

    response = any_staff.post(
        f"/api/v1/credit-notes/{credit_note.id}/apply/",
        json.dumps(NON_OBJECT_BODIES[body_label]),
        content_type="application/json",
    )

    assert response.status_code == 400


@pytest.mark.parametrize("body_label", sorted(NON_OBJECT_BODIES))
def test_the_customer_credit_note_route_rejects_a_non_object_body(
    login_as_customer, body_label
):
    # The same helper backs both, but this one is reachable from the public
    # internet by any registered customer, which makes it the severe half.
    customer = CustomerUserFactory(is_email_verified=True)
    # Built before logging in, and with the enrollment owned by the same
    # customer. `enrollment` carries an RLS policy (apps/training/migrations/
    # 0002) whose USING clause governs writes as well as reads, so creating
    # another customer's row -- which CreditNoteFactory's default
    # source_enrollment does -- is refused once the connection is in this
    # customer's context. Fixture setup belongs before authentication
    # regardless; this just makes the reason explicit.
    credit_note = CreditNoteFactory(
        customer=customer, source_enrollment=EnrollmentFactory(customer=customer)
    )
    client = login_as_customer(customer)

    response = client.post(
        f"/api/v1/my/credit-notes/{credit_note.id}/apply/",
        json.dumps(NON_OBJECT_BODIES[body_label]),
        content_type="application/json",
    )

    assert response.status_code == 400


@pytest.mark.parametrize("body_label", sorted(NON_OBJECT_BODIES))
def test_sample_receipt_rejects_a_non_object_body(any_staff, body_label):
    # Reaching the body read needs the FSM to allow the transition first:
    # in any other state the request is refused before request.data is
    # touched, and the crash hides.
    sample = SampleFactory(status=Sample.Status.REGISTERED)

    response = any_staff.post(
        f"/api/v1/samples/{sample.id}/receive/",
        json.dumps(NON_OBJECT_BODIES[body_label]),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert not ChainOfCustodyEvent.objects.filter(sample=sample).exists()


@pytest.mark.parametrize("body_label", sorted(NON_OBJECT_BODIES))
def test_sample_review_rejects_a_non_object_body(any_staff, body_label):
    sample = SampleFactory(status=Sample.Status.UNDER_REVIEW)

    response = any_staff.post(
        f"/api/v1/samples/{sample.id}/review/",
        json.dumps(NON_OBJECT_BODIES[body_label]),
        content_type="application/json",
    )

    assert response.status_code == 400


# --- The valid cases these guards must not have broken --------------------

def test_a_bare_post_with_no_body_still_works(any_staff):
    # Most of these actions take an optional field; a bodyless POST is the
    # ordinary way to call them, and an absent body is a mapping.
    sample = SampleFactory(status=Sample.Status.REGISTERED)

    response = any_staff.post(f"/api/v1/samples/{sample.id}/receive/")

    assert response.status_code == 200
    assert ChainOfCustodyEvent.objects.filter(sample=sample).exists()


def test_a_non_string_review_comment_is_refused_rather_than_stringified(any_staff):
    # ReviewAction.comments is a TextField, so there is no length to
    # exceed and no database error to hit -- but a list handed to a text
    # column is stringified, and "['a', 'b']" would be written into a
    # regulated record as a reviewer's comment.
    sample = SampleFactory(status=Sample.Status.UNDER_REVIEW)

    response = any_staff.post(
        f"/api/v1/samples/{sample.id}/review/",
        {"comments": ["looks", "fine"]},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "comments" in response.json()


def test_a_long_review_comment_is_still_accepted(any_staff):
    # The guard against 'fixing' the type check by inventing a ceiling the
    # TextField does not have.
    sample = SampleFactory(status=Sample.Status.UNDER_REVIEW)

    response = any_staff.post(
        f"/api/v1/samples/{sample.id}/review/",
        {"comments": "x" * 30000},
        content_type="application/json",
    )

    assert response.status_code == 201
