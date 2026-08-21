"""
Malformed client input must be a 400, not a 500.

Django's ORM takes a lookup value to be already of the field's type:
`.filter(sample_id="abc")` raises ValueError rather than returning nothing.
Every `get_queryset` override in this codebase reads its own query params by
hand -- they exist because DRF silently ignores params it does not recognise
-- so each one was a place where a malformed URL became a server error.

The distinction is not cosmetic. A 500 says the server is broken when the
request was; it takes the blame for a client's typo, and it fills an error
tracker with alerts that read like an outage every time a crawler walks the
API. The same applies to the CharField ceilings a raw `request.data` read
skips straight past, which surface as `value too long for type character
varying(255)` -- a database column name quoted at someone who filled in a
form.

These tests walk the routes rather than asserting one case, because the bug
was a pattern repeated across eight apps, and the next `get_queryset` to be
added will repeat it again unless something is watching.
"""

import pytest

from apps.accounts.models import Role
from apps.samples.models import ChainOfCustodyEvent, Sample
from tests.factories import RoleFactory, SampleFactory, StaffUserFactory

pytestmark = pytest.mark.django_db

# Every (route, numeric filter param) pair that reads an id from the query
# string. Kept as data so adding a filter means adding a line here.
NUMERIC_FILTERS = [
    ("approval-actions", "sample"),
    ("calibration-records", "instrument"),
    ("chain-of-custody-events", "sample"),
    ("credit-notes", "customer_id"),
    ("enrollments", "session"),
    ("investigations", "related_sample"),
    ("investigations", "related_test_result"),
    ("reports", "sample"),
    ("review-actions", "sample"),
    ("test-requests", "sample"),
    ("training-sessions", "course"),
]


@pytest.fixture
def any_staff(login_as_staff):
    """Superuser plus every role: this is about input handling, not authorization."""
    user = StaffUserFactory(is_superuser=True)
    for role in Role.RoleName.values:
        user.roles.add(RoleFactory(name=role))
    return login_as_staff(user)


@pytest.mark.parametrize(("route", "param"), NUMERIC_FILTERS)
def test_a_non_numeric_filter_id_is_a_400(any_staff, route, param):
    response = any_staff.get(f"/api/v1/{route}/?{param}=abc")

    assert response.status_code == 400, (
        f"/{route}/?{param}=abc returned {response.status_code}; "
        f"a non-numeric id is a bad request, not a server error"
    )
    assert param in response.json()


@pytest.mark.parametrize(("route", "param"), NUMERIC_FILTERS)
def test_a_valid_filter_id_still_filters(any_staff, route, param):
    # The guard against 'fixing' the 500 by dropping the filter on the floor,
    # which would leave every one of these endpoints returning unfiltered
    # results and no test noticing.
    response = any_staff.get(f"/api/v1/{route}/?{param}=999999")

    assert response.status_code == 200
    assert response.json()["count"] == 0


@pytest.mark.parametrize(("route", "param"), NUMERIC_FILTERS)
def test_an_empty_filter_value_is_ignored_rather_than_rejected(any_staff, route, param):
    # "?sample=" is what an unset form field serialises to. It means "no
    # filter", not "filter on nothing".
    response = any_staff.get(f"/api/v1/{route}/?{param}=")

    assert response.status_code == 200


def test_a_zero_filter_id_filters_rather_than_matching_everything(any_staff):
    # int_param("0") is 0, which is falsy. A `if sample_id:` guard would skip
    # the filter and return the whole table -- the opposite of what was asked
    # for, and the reason every call site tests `is not None`.
    SampleFactory()

    response = any_staff.get("/api/v1/test-requests/?sample=0")

    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_an_over_length_custody_location_is_a_400(any_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)

    response = any_staff.post(
        f"/api/v1/samples/{sample.id}/receive/",
        {"location": "x" * 300},
        content_type="application/json",
    )

    # ChainOfCustodyEvent.to_location is CharField(max_length=255); Django
    # does not enforce that on save, so without the check Postgres does, as
    # a 500.
    assert response.status_code == 400
    assert "location" in response.json()
    assert not ChainOfCustodyEvent.objects.filter(sample=sample).exists()


def test_a_non_string_custody_location_is_a_400(any_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)

    response = any_staff.post(
        f"/api/v1/samples/{sample.id}/receive/",
        {"location": ["Bench 3", "Bench 4"]},
        content_type="application/json",
    )

    # Without the type check a CharField stringifies it to "['Bench 3',
    # 'Bench 4']" and stores that as the custody location -- a chain-of
    # -custody record that reads like a bug report.
    assert response.status_code == 400


def test_a_valid_custody_location_is_still_recorded(any_staff):
    sample = SampleFactory(status=Sample.Status.REGISTERED)

    response = any_staff.post(
        f"/api/v1/samples/{sample.id}/receive/",
        {"location": "Cold storage, bay 2"},
        content_type="application/json",
    )

    assert response.status_code == 200
    event = ChainOfCustodyEvent.objects.get(sample=sample)
    assert event.to_location == "Cold storage, bay 2"


def test_a_non_numeric_enrollment_on_credit_note_apply_is_a_400(any_staff):
    from tests.factories import CreditNoteFactory

    credit_note = CreditNoteFactory()

    response = any_staff.post(
        f"/api/v1/credit-notes/{credit_note.id}/apply/",
        {"enrollment": "abc"},
        content_type="application/json",
    )

    # This one is reachable by customers too: the same helper backs
    # POST /my/credit-notes/{id}/apply/.
    assert response.status_code == 400
    assert "enrollment" in response.json()
