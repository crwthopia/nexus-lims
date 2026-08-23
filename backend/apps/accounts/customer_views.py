"""
Customer auth endpoints (Blueprint Section 6: Auth (customer) resource
group). Kept separate from views.py (staff-facing read-only resources) since
these are action-style APIViews, not ModelViewSets, and mixing the two
resource shapes in one router/file would blur the "two segregated identity
domains" line the rest of this app is built around.
"""

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import customer_auth
from apps.common import throttling
from apps.accounts.authentication import CustomerSessionAuthentication
from apps.accounts.permissions import IsCustomerAuthenticated
from apps.accounts.serializers import (
    CustomerLoginSerializer,
    CustomerMFACodeSerializer,
    CustomerRegisterSerializer,
    CustomerUserSerializer,
    CustomerVerifyEmailSerializer,
)


class CustomerRegisterView(APIView):
    """POST /auth/customer/register — FR-S1. Sends a verification email (console backend in dev)."""

    authentication_classes = []
    permission_classes = [AllowAny]

    throttle_classes = [throttling.RegisterIPThrottle, throttling.RegisterAccountThrottle]

    def post(self, request):
        serializer = CustomerRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Return value deliberately ignored: it is None when the address was
        # already registered, and this response must not vary either way.
        # Returning the created user for one case and an error for the other
        # is what made registration an enumeration oracle -- the body cannot
        # describe an account without answering the question. The real owner
        # is told by email instead; see register_customer.
        customer_auth.register_customer(**serializer.validated_data)

        return Response(
            {"detail": "Check your email to continue."},
            status=status.HTTP_202_ACCEPTED,
        )


class CustomerVerifyEmailView(APIView):
    """POST /auth/customer/verify-email — consumes the token from the emailed link."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [throttling.VerifyEmailThrottle]

    def post(self, request):
        serializer = CustomerVerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            customer = customer_auth.verify_email_token(serializer.validated_data["token"])
        except customer_auth.CustomerAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CustomerUserSerializer(customer).data)


@method_decorator(ensure_csrf_cookie, name="post")
class CustomerLoginView(APIView):
    """
    POST /auth/customer/login — email+password, plus mfa_code if the account
    has MFA enabled (Blueprint Section 7.1). On success, stores
    customer_user_id in the session (apps/accounts/authentication.py reads
    it back on every subsequent request) -- entirely separate from Django's
    own `_auth_user_id` staff session key.

    ensure_csrf_cookie: nothing else in the customer-facing API renders a
    Django template, so without this a customer session would never receive
    a csrftoken cookie at all -- every authenticated POST after login (MFA
    enable/confirm, logout) would hard-fail CSRF checks with no way to
    recover client-side. A real customer-portal frontend hitting this JSON
    API directly runs into the exact same problem DRF's browsable API
    solves for the staff side by rendering an HTML login form.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [throttling.LoginIPThrottle, throttling.LoginAccountThrottle]

    def post(self, request):
        serializer = CustomerLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            customer = customer_auth.authenticate_customer(**serializer.validated_data)
        except customer_auth.CustomerAuthError as exc:
            error_code = type(exc).__name__
            return Response({"detail": str(exc), "code": error_code}, status=status.HTTP_400_BAD_REQUEST)

        request.session.cycle_key()  # prevent session fixation across the anonymous -> authenticated boundary
        request.session["customer_user_id"] = customer.id
        return Response(CustomerUserSerializer(customer).data)


class CustomerLogoutView(APIView):
    authentication_classes = [CustomerSessionAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def post(self, request):
        request.session.pop("customer_user_id", None)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerMeView(APIView):
    authentication_classes = [CustomerSessionAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get(self, request):
        return Response(CustomerUserSerializer(request.user).data)


class CustomerMFAEnableView(APIView):
    """POST /auth/customer/mfa/enable — step 1: generate secret, return provisioning URI."""

    authentication_classes = [CustomerSessionAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def post(self, request):
        secret, provisioning_uri = customer_auth.generate_mfa_secret(request.user)
        return Response({"secret": secret, "provisioning_uri": provisioning_uri})


class CustomerMFAConfirmView(APIView):
    """POST /auth/customer/mfa/confirm — step 2: prove the authenticator app works, activates MFA."""

    authentication_classes = [CustomerSessionAuthentication]
    permission_classes = [IsCustomerAuthenticated]
    # The tightest limit on the surface: a TOTP code is six digits, so
    # unthrottled this is a million guesses against a window that stays
    # open for about ninety seconds.
    throttle_classes = [throttling.MFAConfirmThrottle]

    def post(self, request):
        serializer = CustomerMFACodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            customer_auth.confirm_mfa(request.user, serializer.validated_data["code"])
        except customer_auth.CustomerAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CustomerUserSerializer(request.user).data)
