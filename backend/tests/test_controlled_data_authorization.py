"""
Who may change the data that decides whether a result passes.

Most write routes already take a role. Five did not, and fell through to
bare IsAuthenticated because `get_permissions` looked up `self.action` in a
map that only listed FSM transitions -- so segregation of duties was
enforced on state changes but not on the master data those states are
judged against. A staff account holding no roles at all could rewrite a
method's specification_limits from pH 6.5-8.5 to 0-14, which makes every
water sample pass, and returned 200.

Two of the five are closed here, the two with compliance weight:

  * TestMethod, because specification_limits and method_reference are what
    a result is measured against. ISO/IEC 17025 Section 7.2 controls methods
    the way it controls documented procedures.
  * Report, because creating one is the lab publishing a result to a
    customer.

Orders, samples and test requests are deliberately left open: registering
an order or a sample is plausibly front-desk work, and restricting it is a
question about how the lab actually operates rather than something to infer
from the code.

Reads stay open throughout. An analyst has to be able to see the method
they are running, and a report is evidence colleagues need to consult.
"""

import pytest

from apps.accounts.models import Role
from apps.reporting.models import Report
from apps.samples.models import Sample
from apps.testing.models import TestMethod
from tests.factories import (
    OrderFactory, RoleFactory, SampleFactory, StaffUserFactory, TestMethodFactory,
)

pytestmark = pytest.mark.django_db

LIMITS = {"pH": {"min": 6.5, "max": 8.5}}
WIDENED = {"pH": {"min": 0, "max": 14}}


def staff_with(*role_names):
    user = StaffUserFactory()
    for name in role_names:
        user.roles.add(RoleFactory(name=name))
    return user


def approved_sample():
    sample = SampleFactory(order=OrderFactory())
    Sample.objects.filter(pk=sample.pk).update(status=Sample.Status.APPROVED)
    sample.refresh_from_db()
    return sample


# --- Test methods ----------------------------------------------------------

def test_an_unprivileged_account_cannot_widen_specification_limits(login_as_staff):
    """The finding this file exists for, asserted on the field that matters."""
    method = TestMethodFactory(specification_limits=LIMITS)
    client = login_as_staff(staff_with())

    response = client.patch(
        f"/api/v1/test-methods/{method.pk}/",
        {"specification_limits": WIDENED},
        format="json",
    )

    assert response.status_code == 403
    method.refresh_from_db()
    assert method.specification_limits == LIMITS, "limits were changed despite the 403"


def test_an_unprivileged_account_cannot_rewrite_the_method_reference(login_as_staff):
    method = TestMethodFactory(method_reference="SOP-0001")
    client = login_as_staff(staff_with())

    response = client.patch(
        f"/api/v1/test-methods/{method.pk}/",
        {"method_reference": "SOMETHING-ELSE"},
        format="json",
    )

    assert response.status_code == 403
    method.refresh_from_db()
    assert method.method_reference == "SOP-0001"


def test_an_unprivileged_account_cannot_create_a_method(login_as_staff):
    client = login_as_staff(staff_with())
    before = TestMethod.objects.count()

    response = client.post(
        "/api/v1/test-methods/",
        {"name": "Unauthorised", "method_reference": "X-1"},
        format="json",
    )

    assert response.status_code == 403
    assert TestMethod.objects.count() == before


@pytest.mark.parametrize(
    "role", [Role.RoleName.QA_OFFICER, Role.RoleName.LAB_SUPERVISOR]
)
def test_the_controlling_roles_can_edit_a_method(login_as_staff, role):
    """
    The positive control. A rule that denied everyone would satisfy the
    tests above and leave the lab unable to maintain its own methods.
    """
    method = TestMethodFactory(specification_limits=LIMITS)
    client = login_as_staff(staff_with(role))

    response = client.patch(
        f"/api/v1/test-methods/{method.pk}/",
        {"specification_limits": WIDENED},
        format="json",
    )

    assert response.status_code == 200, response.data
    method.refresh_from_db()
    assert method.specification_limits == WIDENED


def test_any_staff_member_can_still_read_a_method(login_as_staff):
    """An analyst must be able to look up the method they are running."""
    method = TestMethodFactory()
    client = login_as_staff(staff_with())

    assert client.get("/api/v1/test-methods/").status_code == 200
    assert client.get(f"/api/v1/test-methods/{method.pk}/").status_code == 200


# --- Reports ---------------------------------------------------------------

def test_an_unprivileged_account_cannot_issue_a_report(login_as_staff):
    sample = approved_sample()
    client = login_as_staff(staff_with())

    response = client.post(
        "/api/v1/reports/",
        {"sample": sample.pk, "report_type": Report.ReportType.WATER_ENVIRONMENTAL_COA},
        format="json",
    )

    assert response.status_code == 403
    assert not Report.objects.filter(sample=sample).exists()


@pytest.mark.parametrize(
    "role", [Role.RoleName.APPROVER, Role.RoleName.LAB_SUPERVISOR]
)
def test_the_issuing_roles_can_create_a_report(login_as_staff, role):
    sample = approved_sample()
    client = login_as_staff(staff_with(role))

    response = client.post(
        "/api/v1/reports/",
        {"sample": sample.pk, "report_type": Report.ReportType.WATER_ENVIRONMENTAL_COA},
        format="json",
    )

    assert response.status_code == 201, response.data


def test_any_staff_member_can_still_read_reports(login_as_staff):
    client = login_as_staff(staff_with())

    assert client.get("/api/v1/reports/").status_code == 200


# --- What was left open, on purpose ---------------------------------------

@pytest.mark.parametrize("resource", ["orders", "samples", "test-requests"])
def test_intake_routes_remain_open_to_any_staff_member(login_as_staff, resource):
    """
    Pinned deliberately rather than left to drift. These three were found
    unguarded by the same sweep and left that way on purpose; if that
    changes it should be a decision, not a side effect. A 400 means the
    request reached validation, i.e. was not refused on authorisation.
    """
    client = login_as_staff(staff_with())

    response = client.post(f"/api/v1/{resource}/", {}, format="json")

    assert response.status_code == 400, (
        f"{resource} now refuses an unprivileged account with "
        f"{response.status_code} -- intended, or an accident?"
    )
