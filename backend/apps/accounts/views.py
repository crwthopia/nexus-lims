"""
Read-only support endpoints for identity resources (Blueprint Section 6:
Auth resource group). Staff/customer registration and Entra ID callback
handling are not yet wired (README "Known gaps") — these viewsets expose
the already-migrated Role/StaffUser/CustomerUser/ESignature data so the
core C-1 to C-6 endpoints (samples/testing/review/reporting) have something
to reference (e.g. "who is this StaffUser") while auth is built out.
"""

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseRedirect
from django.views import View
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import CustomerUser, ESignature, Role, StaffUser
from apps.accounts.serializers import (
    CustomerUserSerializer,
    ESignatureSerializer,
    RoleSerializer,
    StaffUserSerializer,
)


class RoleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated]


class StaffUserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StaffUser.objects.all()
    serializer_class = StaffUserSerializer
    permission_classes = [IsAuthenticated]


class CustomerUserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Staff-facing read access only. Customer self-service (view/edit own
    profile) belongs behind the customer auth backend, not this router
    (Blueprint Section 2.1 item 7: segregated identity domains).
    """

    queryset = CustomerUser.objects.all()
    serializer_class = CustomerUserSerializer
    permission_classes = [IsAuthenticated]


class ESignatureViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ESignature.objects.all()
    serializer_class = ESignatureSerializer
    permission_classes = [IsAuthenticated]


class StaffMeView(APIView):
    """
    GET /auth/staff/me — the staff-side counterpart to CustomerMeView
    (apps/accounts/customer_views.py). Needed by the React Staff Console
    (Blueprint Section 2.1 item 1): StaffUserViewSet is a paginated listing
    of every staff user, not scoped to the caller, so there was previously
    no way for a client to ask "who am I / what roles do I hold" — which
    the console needs on every page load to render role-gated actions
    (e.g. SampleViewSet._ROLE_MAP) without guessing from a list response.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(StaffUserSerializer(request.user).data)


class StaffLogoutView(APIView):
    """
    POST /auth/staff/logout — clears the Django session only (not the Entra
    ID / Microsoft SSO session). Kept deliberately separate from
    /oauth2/logout (django_auth_adfs.views.OAuth2LogoutView), which also
    ends the browser's Microsoft session and requires a registered
    post-logout redirect URI this version of django-auth-adfs doesn't
    support configuring -- signing back in there would land on a bare
    Microsoft page with no way back to the Staff Console. This endpoint
    gives the SPA a same-origin, JSON logout it can call from a button
    without leaving the page; /oauth2/logout is still reachable directly
    for a full SSO sign-out if NASAT wants one later.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffLoginCompleteView(View):
    """
    GET /staff/login-complete/ — the "next" target django-auth-adfs's
    OAuth2CallbackView redirects to once Entra ID SSO finishes (see
    apps/accounts/urls.py and config/settings.py STAFF_CONSOLE_BASE_URL for
    why this indirection exists: the callback's own redirect can't cross
    from the Django dev server's port to the Vite dev server's port
    directly). Not a DRF view -- there's nothing to authenticate or
    serialize, just a real HTTP redirect the browser follows as a fresh
    top-level navigation, carrying the now-set session cookie to the SPA's
    origin (cookies are host-scoped, not port-scoped, so this works even
    though the two dev servers run on different ports).
    """

    def get(self, request):
        return HttpResponseRedirect(settings.STAFF_CONSOLE_BASE_URL)
