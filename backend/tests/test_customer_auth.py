"""
Customer self-service auth (Blueprint Section 2.1 item 7, Section 6 Auth
(customer) resource group): register -> verify -> login, and TOTP MFA
enrollment/login. Uses the real customer_auth module to generate the
verification token and TOTP codes rather than parsing them out of the
console-backend email, since that plumbing isn't under test here.
"""

import time

import pyotp
import pytest

from apps.accounts import customer_auth
from apps.accounts.models import CustomerUser
from tests.factories import CUSTOMER_RAW_PASSWORD, CustomerUserFactory

pytestmark = pytest.mark.django_db


def test_register_verify_login_round_trip(api_client):
    response = api_client.post(
        "/api/v1/auth/customer/register",
        {"email": "newcustomer@example.test", "password": "Str0ngPassw0rd!1"},
        format="json",
    )
    # 202 with a neutral body, not 201 with the created account: the
    # response must read the same whether or not the address was already
    # registered, or it answers "is this person a customer here?" for
    # anyone who asks. See test_customer_auth_hardening.py.
    assert response.status_code == 202
    customer = CustomerUser.objects.get(email="newcustomer@example.test")
    assert not customer.is_email_verified

    login_before_verify = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": "Str0ngPassw0rd!1"},
        format="json",
    )
    assert login_before_verify.status_code == 400
    assert login_before_verify.data["code"] == "EmailNotVerifiedError"

    token = customer_auth.generate_email_verification_token(customer)
    verify_response = api_client.post("/api/v1/auth/customer/verify-email", {"token": token}, format="json")
    assert verify_response.status_code == 200
    customer.refresh_from_db()
    assert customer.is_email_verified

    login_response = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": "Str0ngPassw0rd!1"},
        format="json",
    )
    assert login_response.status_code == 200

    me_response = api_client.get("/api/v1/auth/customer/me")
    assert me_response.status_code == 200
    assert me_response.data["email"] == customer.email


def test_login_rejects_wrong_password_without_revealing_which_field(api_client):
    customer = CustomerUserFactory()

    response = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": "wrong-password"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "InvalidCredentialsError"
    assert response.data["detail"] == "Invalid email or password."


def test_login_unknown_email_gives_same_generic_error(api_client):
    response = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": "nobody@example.test", "password": "whatever"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "InvalidCredentialsError"


def test_mfa_enrollment_and_login_flow(login_as_customer, api_client):
    customer = CustomerUserFactory()
    login_as_customer(customer)

    enable_response = api_client.post("/api/v1/auth/customer/mfa/enable")
    assert enable_response.status_code == 200
    secret = enable_response.data["secret"]

    valid_code = pyotp.TOTP(secret).now()
    confirm_response = api_client.post("/api/v1/auth/customer/mfa/confirm", {"code": valid_code}, format="json")
    assert confirm_response.status_code == 200
    customer.refresh_from_db()
    assert customer.mfa_enabled

    api_client.post("/api/v1/auth/customer/logout")

    login_without_code = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": CUSTOMER_RAW_PASSWORD},
        format="json",
    )
    assert login_without_code.status_code == 400
    assert login_without_code.data["code"] == "MFARequiredError"

    # A code from the *next* time step, not TOTP.now().
    #
    # Confirming enrolment consumes the code it was confirmed with, so that
    # an attacker who saw it cannot immediately replay it into a login. In
    # the same 30-second window TOTP.now() returns that very code, so this
    # would be rejected as a replay -- correctly. A real customer hits this
    # only if they log in again within thirty seconds of enrolling.
    next_step_code = pyotp.TOTP(secret).at(time.time() + 30)
    login_with_code = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": CUSTOMER_RAW_PASSWORD, "mfa_code": next_step_code},
        format="json",
    )
    assert login_with_code.status_code == 200
