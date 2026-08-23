"""
Customer authentication business logic (Blueprint Section 2.1 item 7,
Section 7.1, Section 6 Auth (customer) resource group).

CustomerUser is a plain model, not AUTH_USER_MODEL -- Django's built-in
auth machinery (authenticate(), login(), password validators keyed to
AbstractBaseUser, the default password-reset token generator) doesn't apply
to it directly, by design (Blueprint Section 2.1 item 7: two segregated
identity domains, no shared user table). This module reimplements the
pieces that machinery would normally provide, scoped to CustomerUser:
password hashing (reusing Django's own hasher registry via make_password/
check_password, so this is not home-grown crypto), a signed/timestamped
email-verification token (django.core.signing, since there's no
password+last_login to hash into a token the way Django's default generator
does), and TOTP-based MFA (pyotp, RFC 6238).
"""

import time

import pyotp
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.mail import send_mail

from apps.accounts.models import CustomerUser

EMAIL_VERIFICATION_SALT = "apps.accounts.customer_auth.email_verification"


class CustomerAuthError(Exception):
    """Base class for customer-auth failures the view layer turns into 400s."""


class InvalidCredentialsError(CustomerAuthError):
    pass


class EmailNotVerifiedError(CustomerAuthError):
    pass


class MFARequiredError(CustomerAuthError):
    pass


class InvalidMFACodeError(CustomerAuthError):
    pass


class InvalidVerificationTokenError(CustomerAuthError):
    pass


def register_customer(*, email, password, organization_name=None, prc_license_number=None):
    """
    FR-S1 customer self-registration. Sends (via EMAIL_BACKEND) a
    verification email.

    Returns None when the address already belongs to an account, and the
    view answers identically either way. Telling an anonymous caller "an
    account with this email already exists" turns registration into an
    oracle for whether any address is a customer of this laboratory --
    which is personal data under RA 10173, and is disclosed to anyone who
    can type an email address.

    The existing account is told instead. That is the half of this design
    that matters: a real owner who has forgotten they registered still
    finds out, through the channel only they can read.
    """
    validate_password(password)  # reuses AUTH_PASSWORD_VALIDATORS (config/settings.py)

    existing = CustomerUser.objects.filter(email__iexact=email.strip().lower()).first()
    if existing is not None:
        send_duplicate_registration_email(existing)
        return None

    customer = CustomerUser.objects.create(
        email=email.strip().lower(),
        password_hash=make_password(password),
        organization_name=organization_name,
        prc_license_number=prc_license_number,
    )
    send_verification_email(customer)
    return customer


def send_duplicate_registration_email(customer):
    """
    Sent when someone tries to register an address that already has an
    account. Deliberately says nothing an attacker could not already
    guess, and gives the real owner a reason to act if it was not them.
    """
    send_mail(
        subject="Someone tried to register your NexusLIMS account",
        message=(
            "Somebody just tried to create a NexusLIMS account with this email "
            "address, which already has one.\n\n"
            "If that was you, log in instead -- there is nothing to do here. If it "
            "was not, your account is unaffected and no action is required, but "
            "consider changing your password if you reuse it elsewhere.\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[customer.email],
    )


def send_verification_email(customer):
    token = generate_email_verification_token(customer)
    verify_url = f"{settings.CUSTOMER_PORTAL_BASE_URL}/verify-email?token={token}"
    send_mail(
        subject="Verify your NexusLIMS account",
        message=(
            f"Welcome to NexusLIMS. Verify your email to activate your account:\n\n"
            f"{verify_url}\n\n"
            f"(Raw token, valid {settings.CUSTOMER_EMAIL_VERIFICATION_MAX_AGE_SECONDS // 3600}h: {token})"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[customer.email],
    )


def generate_email_verification_token(customer):
    return signing.dumps({"customer_id": customer.id, "email": customer.email}, salt=EMAIL_VERIFICATION_SALT)


def verify_email_token(token):
    try:
        payload = signing.loads(
            token, salt=EMAIL_VERIFICATION_SALT, max_age=settings.CUSTOMER_EMAIL_VERIFICATION_MAX_AGE_SECONDS
        )
    except signing.BadSignature as exc:
        raise InvalidVerificationTokenError("Verification link is invalid or has expired.") from exc

    try:
        customer = CustomerUser.objects.get(pk=payload["customer_id"], email=payload["email"])
    except CustomerUser.DoesNotExist as exc:
        raise InvalidVerificationTokenError("Verification link no longer matches an account.") from exc

    if customer.is_email_verified:
        # Single use. The token is a bearer credential that travels by
        # email and is valid for hours, so accepting it again long after it
        # did its job leaves a live credential lying in a mailbox for no
        # benefit -- verification is not a thing that needs doing twice.
        raise InvalidVerificationTokenError("This verification link has already been used.")

    customer.is_email_verified = True
    customer.save(update_fields=["is_email_verified", "updated_at"])
    return customer


def authenticate_customer(*, email, password, mfa_code=None):
    """
    FR-S1 customer login. Raises InvalidCredentialsError (bad email/password,
    deliberately not distinguishing which, to avoid user enumeration),
    EmailNotVerifiedError, MFARequiredError (mfa_enabled but no code given),
    or InvalidMFACodeError. Returns the CustomerUser on success.
    """
    customer = CustomerUser.objects.filter(email__iexact=email).first()

    if customer is None:
        # Hash anyway, against a throwaway. Returning before check_password
        # made an unknown address answer in about 2ms where a known one took
        # about 425ms -- a 220x difference, measured, which is not a subtle
        # side channel but a reliable oracle for whether any address is a
        # customer here. The identical error message below was doing nothing
        # while the response time gave the answer away.
        make_password(password)
        raise InvalidCredentialsError("Invalid email or password.")

    if not check_password(password, customer.password_hash):
        raise InvalidCredentialsError("Invalid email or password.")

    if not customer.is_email_verified:
        raise EmailNotVerifiedError("Please verify your email before logging in.")

    if customer.mfa_enabled:
        if not mfa_code:
            raise MFARequiredError("MFA code required.")
        if not verify_mfa_code(customer, mfa_code):
            raise InvalidMFACodeError("Invalid MFA code.")

    return customer


def generate_mfa_secret(customer):
    """
    Step 1 of FR-S1 MFA enrollment: generate a TOTP secret and return the
    provisioning URI for a QR code or manual authenticator entry.

    The new secret goes to `pending_mfa_secret` and the working one is left
    alone until confirm_mfa succeeds. Writing straight to `mfa_secret` --
    which is what this did -- locked a customer out of their own account
    the moment they opened the enrolment screen while MFA was already on:
    their authenticator still held the old secret, the server had replaced
    it, and `mfa_enabled` stayed True, so every code they could produce was
    rejected and there was no way back in.
    """
    secret = pyotp.random_base32()
    customer.pending_mfa_secret = secret
    customer.save(update_fields=["pending_mfa_secret", "updated_at"])
    provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(name=customer.email, issuer_name="NexusLIMS")
    return secret, provisioning_uri


def confirm_mfa(customer, code):
    """
    Step 2 of FR-S1 MFA enrollment: prove the authenticator app is set up.

    Only here does the pending secret become the real one, so a
    half-finished enrolment leaves a working account working.
    """
    pending = customer.pending_mfa_secret
    if not pending or not _code_matches(pending, code):
        raise InvalidMFACodeError("Invalid MFA code.")

    customer.mfa_secret = pending
    customer.pending_mfa_secret = None
    customer.mfa_enabled = True
    # The confirming code counts as used, or it could immediately be
    # replayed against the login it just enabled.
    customer.mfa_last_used_timestep = _timestep_of(pending, code)
    customer.save(update_fields=[
        "mfa_secret", "pending_mfa_secret", "mfa_enabled",
        "mfa_last_used_timestep", "updated_at",
    ])
    return customer


# One step either side of now, per RFC 6238's clock-skew allowance. It is
# also what makes replay worth preventing: a code stays acceptable for
# about ninety seconds.
_TOTP_VALID_WINDOW = 1


def _code_matches(secret, code):
    return pyotp.totp.TOTP(secret).verify(code, valid_window=_TOTP_VALID_WINDOW)


def _timestep_of(secret, code):
    """
    Which time step a valid code belongs to.

    Recorded rather than the code itself: the step is what identifies the
    one-time password, and storing the digits would put a live credential
    in the database next to the secret that generates them.
    """
    totp = pyotp.totp.TOTP(secret)
    now = int(time.time())
    for offset in range(-_TOTP_VALID_WINDOW, _TOTP_VALID_WINDOW + 1):
        at = now + offset * totp.interval
        if totp.at(at) == code:
            return at // totp.interval
    return now // totp.interval


def verify_mfa_code(customer, code):
    """
    True only for a code that is valid *and* has not been used before.

    RFC 6238 6: a one-time password must be accepted once. Without the
    timestep check a code observed over a shoulder, read from a screen
    share, or captured anywhere in transit stayed usable for the whole
    validity window -- and the window is deliberately wide enough to
    tolerate clock skew, which is exactly what makes that useful to an
    attacker.
    """
    if not customer.mfa_secret:
        return False
    if not _code_matches(customer.mfa_secret, code):
        return False

    step = _timestep_of(customer.mfa_secret, code)
    if customer.mfa_last_used_timestep is not None and step <= customer.mfa_last_used_timestep:
        return False

    customer.mfa_last_used_timestep = step
    customer.save(update_fields=["mfa_last_used_timestep", "updated_at"])
    return True
