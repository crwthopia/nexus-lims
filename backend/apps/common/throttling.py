"""
Rate limits for the unauthenticated customer auth surface.

These endpoints are the only part of the system reachable from the public
internet without credentials, and every one of them was unthrottled: an
attacker could guess passwords, brute-force a six-digit TOTP code, or send
unlimited mail from the lab's domain at whatever rate the network allowed.

Two axes, because either alone is porous:

  * per IP, which stops one host hammering the whole surface;
  * per account, which stops a distributed attempt on one victim -- the
    case per-IP limits are blind to, since each source stays under its own
    quota while the target is hit at their combined rate.

A six-digit TOTP is the sharpest example. Unlimited guesses against a
90-second window is not meaningfully harder than no second factor at all;
with these limits it is.
"""

import hashlib

from rest_framework.throttling import SimpleRateThrottle


class _EmailScopedThrottle(SimpleRateThrottle):
    """
    Throttles by the account being *targeted*, not by who is asking.

    The email is hashed into the cache key rather than stored raw: these
    keys live in Redis alongside the rest of the cache, and a key named for
    a customer's address turns the throttle store into a list of the lab's
    customers, which is exactly the personal data RA 10173 covers.
    """

    def get_cache_key(self, request, view):
        email = (request.data or {}).get("email") if hasattr(request, "data") else None
        if not isinstance(email, str) or not email:
            # Nothing to scope to. The per-IP throttle still applies, and a
            # request with no email fails validation moments later anyway.
            return None
        digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
        return f"throttle_{self.scope}_{digest}"


class LoginIPThrottle(SimpleRateThrottle):
    scope = "customer_login_ip"

    def get_cache_key(self, request, view):
        return self.get_ident(request)


class LoginAccountThrottle(_EmailScopedThrottle):
    scope = "customer_login_account"


class RegisterIPThrottle(SimpleRateThrottle):
    scope = "customer_register_ip"

    def get_cache_key(self, request, view):
        return self.get_ident(request)


class RegisterAccountThrottle(_EmailScopedThrottle):
    """
    Also a mail-flood limit. Registration sends to the address in the
    request, so without this an attacker can make the lab's mail server
    send unlimited mail to anyone they choose -- which is how a sending
    domain's reputation is destroyed by a third party.
    """

    scope = "customer_register_account"


class VerifyEmailThrottle(SimpleRateThrottle):
    scope = "customer_verify_email"

    def get_cache_key(self, request, view):
        return self.get_ident(request)


class MFAConfirmThrottle(SimpleRateThrottle):
    """
    The tightest of these. A TOTP code is six digits, so an unthrottled
    endpoint is a million guesses against a window that stays open for
    about ninety seconds.
    """

    scope = "customer_mfa_confirm"

    def get_cache_key(self, request, view):
        # Authenticated, so scope to the account rather than the address:
        # this is the enrolment confirmation, and the session already names
        # whose enrolment it is.
        if request.user and getattr(request.user, "pk", None):
            return f"throttle_{self.scope}_{request.user.pk}"
        return self.get_ident(request)
