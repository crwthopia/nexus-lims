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
    """FR-S1 customer self-registration. Sends (via EMAIL_BACKEND) a verification email."""
    validate_password(password)  # reuses AUTH_PASSWORD_VALIDATORS (config/settings.py)
    customer = CustomerUser.objects.create(
        email=email.strip().lower(),
        password_hash=make_password(password),
        organization_name=organization_name,
        prc_license_number=prc_license_number,
    )
    send_verification_email(customer)
    return customer


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
    try:
        customer = CustomerUser.objects.get(email__iexact=email)
    except CustomerUser.DoesNotExist as exc:
        raise InvalidCredentialsError("Invalid email or password.") from exc

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
    Step 1 of FR-S1 MFA enrollment: generate and store a TOTP secret
    (unconfirmed -- mfa_enabled stays False until confirm_mfa succeeds), and
    return the provisioning URI for a QR code / manual authenticator entry.
    """
    secret = pyotp.random_base32()
    customer.mfa_secret = secret
    customer.save(update_fields=["mfa_secret", "updated_at"])
    provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(name=customer.email, issuer_name="NexusLIMS")
    return secret, provisioning_uri


def confirm_mfa(customer, code):
    """Step 2 of FR-S1 MFA enrollment: prove the customer's authenticator app is set up correctly."""
    if not customer.mfa_secret or not verify_mfa_code(customer, code):
        raise InvalidMFACodeError("Invalid MFA code.")
    customer.mfa_enabled = True
    customer.save(update_fields=["mfa_enabled", "updated_at"])
    return customer


def verify_mfa_code(customer, code):
    if not customer.mfa_secret:
        return False
    return pyotp.totp.TOTP(customer.mfa_secret).verify(code, valid_window=1)
