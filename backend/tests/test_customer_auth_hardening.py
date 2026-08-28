"""
The customer auth surface, viewed adversarially.

These endpoints are the only part of the system reachable from the public
internet without credentials, and every finding below was live: confirmed
by probing the running API before it was fixed, not inferred from reading.

Each test isolates one property. That matters more than usual here,
because the fixes interact: once rate limiting exists, a careless test of
anything else gets a 429 and passes without exercising the thing it names.
The conftest fixture that clears the cache between tests is what keeps
these honest, and the throttle tests below spend the limit deliberately.
"""

import time

import pyotp
import pytest
from django.core import mail

from apps.accounts import customer_auth
from apps.accounts.models import CustomerUser
from tests.helpers import deliver_queued_notifications
from tests.factories import CUSTOMER_RAW_PASSWORD, CustomerUserFactory

pytestmark = pytest.mark.django_db


# --- Account enumeration --------------------------------------------------

def test_registration_does_not_reveal_whether_an_address_is_a_customer(api_client):
    """
    Registration used to answer "An account with this email already
    exists" to anyone who asked, which makes it an oracle for whether any
    address belongs to a customer of this laboratory -- personal data
    under RA 10173, disclosed to anyone who can type an email address.
    """
    existing = CustomerUserFactory(email="known@example.test")

    taken = api_client.post(
        "/api/v1/auth/customer/register",
        {"email": existing.email, "password": "Str0ngPassw0rd!1"},
        format="json",
    )
    fresh = api_client.post(
        "/api/v1/auth/customer/register",
        {"email": "unknown@example.test", "password": "Str0ngPassw0rd!1"},
        format="json",
    )

    assert taken.status_code == fresh.status_code == 202
    assert taken.json() == fresh.json()
    assert b"exists" not in taken.content


def test_the_real_owner_is_told_when_someone_registers_their_address(api_client):
    # The half of the design that makes the silence acceptable: whoever
    # actually owns the address still finds out, through a channel only
    # they can read.
    existing = CustomerUserFactory(email="owner@example.test")
    mail.outbox.clear()

    api_client.post(
        "/api/v1/auth/customer/register",
        {"email": existing.email, "password": "Str0ngPassw0rd!1"},
        format="json",
    )

    # The message is queued in the request and sent by a worker after commit
    # (apps/notifications/notify.py), so a test has to stand in for the
    # worker -- see tests/helpers.deliver_queued_notifications.
    deliver_queued_notifications()

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [existing.email]
    assert "tried to register" in mail.outbox[0].subject.lower()


def test_a_duplicate_registration_does_not_touch_the_existing_account(api_client):
    existing = CustomerUserFactory(email="untouched@example.test")
    original_hash = existing.password_hash

    api_client.post(
        "/api/v1/auth/customer/register",
        {"email": existing.email, "password": "Different!Passw0rd"},
        format="json",
    )

    existing.refresh_from_db()
    assert existing.password_hash == original_hash
    assert CustomerUser.objects.filter(email__iexact=existing.email).count() == 1


def test_login_takes_the_same_time_for_a_real_and_an_unknown_account(api_client):
    """
    The timing oracle, which is the one that made the identical error
    message pointless.

    Returning before check_password meant an unknown address answered in
    about 2ms where a known one took about 425ms: a 220x difference,
    measured on the running API. Password hashing is deliberately slow, so
    skipping it is loud.

    Asserted as a ratio with generous slack -- this runs on shared CI
    hardware and the point is orders of magnitude, not milliseconds.
    """
    known = CustomerUserFactory(email="timing@example.test")

    def median_seconds(email):
        samples = []
        for _ in range(5):
            started = time.perf_counter()
            api_client.post(
                "/api/v1/auth/customer/login",
                {"email": email, "password": "wrong-password"},
                format="json",
            )
            samples.append(time.perf_counter() - started)
        return sorted(samples)[len(samples) // 2]

    known_time = median_seconds(known.email)
    unknown_time = median_seconds("no-such-customer@example.test")

    assert unknown_time * 5 > known_time, (
        f"unknown address answered {known_time / unknown_time:.0f}x faster than a "
        f"known one, which tells an attacker which addresses are customers"
    )


# --- TOTP ------------------------------------------------------------------

def enrolled_customer():
    customer = CustomerUserFactory(is_email_verified=True)
    secret = pyotp.random_base32()
    customer.mfa_secret = secret
    customer.mfa_enabled = True
    customer.save()
    return customer, secret


def test_a_totp_code_cannot_be_used_twice(api_client):
    """
    RFC 6238 6: a one-time password is accepted once. Without this, a code
    seen over a shoulder or on a shared screen stayed usable for the whole
    validity window -- and that window is deliberately wide, to tolerate
    clock skew, which is what makes it useful to an attacker.
    """
    customer, secret = enrolled_customer()
    code = pyotp.TOTP(secret).now()

    first = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": CUSTOMER_RAW_PASSWORD, "mfa_code": code},
        format="json",
    )
    assert first.status_code == 200
    api_client.post("/api/v1/auth/customer/logout")

    replay = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": CUSTOMER_RAW_PASSWORD, "mfa_code": code},
        format="json",
    )

    assert replay.status_code == 400
    assert replay.json()["code"] == "InvalidMFACodeError"


def test_a_later_code_is_still_accepted_after_one_is_consumed(api_client):
    # The guard against "fixing" replay by rejecting everything: consuming
    # one code must not lock the account out of the next one.
    customer, secret = enrolled_customer()

    api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": CUSTOMER_RAW_PASSWORD, "mfa_code": pyotp.TOTP(secret).now()},
        format="json",
    )
    api_client.post("/api/v1/auth/customer/logout")

    later = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": CUSTOMER_RAW_PASSWORD,
         "mfa_code": pyotp.TOTP(secret).at(time.time() + 30)},
        format="json",
    )

    assert later.status_code == 200


def test_an_earlier_code_cannot_be_used_after_a_later_one(api_client):
    # Replay protection has to be monotonic, not just "not the same code":
    # the validity window covers a step either side of now, so an older
    # code is still cryptographically valid and must be refused on age.
    customer, secret = enrolled_customer()
    old_code = pyotp.TOTP(secret).at(time.time() - 30)
    current_code = pyotp.TOTP(secret).now()

    api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": CUSTOMER_RAW_PASSWORD, "mfa_code": current_code},
        format="json",
    )
    api_client.post("/api/v1/auth/customer/logout")

    stale = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": CUSTOMER_RAW_PASSWORD, "mfa_code": old_code},
        format="json",
    )

    assert stale.status_code == 400


# --- MFA re-enrolment ------------------------------------------------------

def test_starting_a_new_enrolment_does_not_break_the_working_one(login_as_customer, api_client):
    """
    An availability bug rather than a disclosure one, and a total lockout.

    /mfa/enable wrote the new secret straight to mfa_secret while
    mfa_enabled stayed True, so merely *opening* the enrolment screen while
    MFA was on replaced the secret the customer's authenticator held. Every
    code they could produce was then rejected, and nothing let them back in.
    """
    customer, secret = enrolled_customer()
    login_as_customer(customer, mfa_code=pyotp.TOTP(secret).now())

    api_client.post("/api/v1/auth/customer/mfa/enable")

    customer.refresh_from_db()
    assert customer.mfa_secret == secret, "the working secret was replaced before confirmation"
    assert customer.mfa_enabled is True
    assert customer.pending_mfa_secret is not None

    api_client.post("/api/v1/auth/customer/logout")
    # A later time step: the login above consumed the current one, which is
    # replay prevention doing its job rather than a failure of this test.
    still_works = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": CUSTOMER_RAW_PASSWORD,
         "mfa_code": pyotp.TOTP(secret).at(time.time() + 30)},
        format="json",
    )
    assert still_works.status_code == 200


def test_confirming_a_new_enrolment_swaps_the_secret(login_as_customer, api_client):
    customer, old_secret = enrolled_customer()
    login_as_customer(customer, mfa_code=pyotp.TOTP(old_secret).now())

    enable = api_client.post("/api/v1/auth/customer/mfa/enable")
    new_secret = enable.json()["secret"]

    confirm = api_client.post(
        "/api/v1/auth/customer/mfa/confirm",
        {"code": pyotp.TOTP(new_secret).now()},
        format="json",
    )

    assert confirm.status_code == 200
    customer.refresh_from_db()
    assert customer.mfa_secret == new_secret
    assert customer.mfa_secret != old_secret
    assert customer.pending_mfa_secret is None


def test_the_confirming_code_cannot_be_replayed_into_a_login(login_as_customer, api_client):
    # Otherwise an attacker who sees the enrolment code gets a free login
    # with it.
    customer = CustomerUserFactory(is_email_verified=True)
    login_as_customer(customer)

    secret = api_client.post("/api/v1/auth/customer/mfa/enable").json()["secret"]
    code = pyotp.TOTP(secret).now()
    api_client.post("/api/v1/auth/customer/mfa/confirm", {"code": code}, format="json")
    api_client.post("/api/v1/auth/customer/logout")

    replay = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": CUSTOMER_RAW_PASSWORD, "mfa_code": code},
        format="json",
    )

    assert replay.status_code == 400


# --- Verification tokens ---------------------------------------------------

def test_a_verification_token_is_single_use(api_client):
    # The token travels by email and stays valid for hours. Accepting it
    # again after it has done its job leaves a live credential sitting in a
    # mailbox for no benefit.
    customer = CustomerUserFactory(is_email_verified=False)
    token = customer_auth.generate_email_verification_token(customer)

    first = api_client.post("/api/v1/auth/customer/verify-email", {"token": token}, format="json")
    second = api_client.post("/api/v1/auth/customer/verify-email", {"token": token}, format="json")

    assert first.status_code == 200
    assert second.status_code == 400
    assert "already been used" in second.json()["detail"]


# --- Rate limiting ---------------------------------------------------------
#
# These spend the limit on purpose. Everything above depends on the cache
# being cleared between tests, or the first throttled request would make
# the rest pass without testing anything.

def test_password_guessing_is_throttled(api_client):
    customer = CustomerUserFactory(is_email_verified=True)

    statuses = [
        api_client.post(
            "/api/v1/auth/customer/login",
            {"email": customer.email, "password": f"guess-{n}"},
            format="json",
        ).status_code
        for n in range(30)
    ]

    assert 429 in statuses, "unlimited password guesses against a known account"


def test_one_account_cannot_be_brute_forced_from_many_addresses(api_client):
    """
    Per-IP limits are blind to a distributed attempt: each source stays
    under its own quota while the target absorbs their combined rate. The
    account-scoped throttle is what closes that, so it is worth proving it
    is the thing responding rather than the IP limit.
    """
    customer = CustomerUserFactory(is_email_verified=True)

    statuses = []
    for n in range(30):
        # A different apparent client each time.
        statuses.append(
            api_client.post(
                "/api/v1/auth/customer/login",
                {"email": customer.email, "password": f"guess-{n}"},
                format="json",
                REMOTE_ADDR=f"203.0.113.{n % 254 + 1}",
            ).status_code
        )

    assert 429 in statuses, "one account could be brute-forced from rotating addresses"


def test_totp_guessing_is_throttled(login_as_customer, api_client):
    # Six digits. Unthrottled, this is a million guesses against a window
    # that stays open for about ninety seconds, which is not meaningfully
    # harder than no second factor at all.
    customer = CustomerUserFactory(is_email_verified=True)
    login_as_customer(customer)
    api_client.post("/api/v1/auth/customer/mfa/enable")

    statuses = [
        api_client.post(
            "/api/v1/auth/customer/mfa/confirm", {"code": f"{n:06d}"}, format="json"
        ).status_code
        for n in range(20)
    ]

    assert 429 in statuses, "unlimited TOTP guesses"


def test_registration_cannot_be_used_to_flood_an_address(api_client):
    # Registration sends mail to whatever address is in the request, so an
    # unthrottled endpoint lets anyone make the lab's mail server bombard
    # a third party -- which is how a sending domain's reputation is
    # destroyed by someone else.
    statuses = [
        api_client.post(
            "/api/v1/auth/customer/register",
            {"email": "target@example.test", "password": "Str0ngPassw0rd!1"},
            format="json",
        ).status_code
        for _ in range(10)
    ]

    assert 429 in statuses


def test_throttling_does_not_block_an_ordinary_login(api_client):
    # The guard against setting the limits so tight that real customers
    # trip them. One wrong password then a correct one has to work.
    customer = CustomerUserFactory(is_email_verified=True)

    api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": "fat-fingered"},
        format="json",
    )
    good = api_client.post(
        "/api/v1/auth/customer/login",
        {"email": customer.email, "password": CUSTOMER_RAW_PASSWORD},
        format="json",
    )

    assert good.status_code == 200
