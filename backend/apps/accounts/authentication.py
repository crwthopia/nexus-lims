"""
Customer session authentication (Blueprint Section 2.1 item 7).

Deliberately not DRF's own SessionAuthentication: that class authenticates
off request.user, which Django's AuthenticationMiddleware populates solely
from the `_auth_user_id` session key tied to AUTH_USER_MODEL (StaffUser).
CustomerUser identity lives under a separate `customer_user_id` session key
(set by CustomerLoginView, apps/accounts/customer_views.py) that Django's
own auth pipeline never touches, so a StaffUser session and a CustomerUser
session can coexist in the same browser without either one being able to
authenticate as the other -- there is no code path from one identity domain
into the other's session key.

Subclasses SessionAuthentication only to reuse its enforce_csrf() helper,
which is otherwise a private-ish implementation detail worth not
reinventing; authenticate() itself is fully overridden.
"""

from rest_framework.authentication import SessionAuthentication

from apps.accounts.models import CustomerUser


class CustomerSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        customer_id = request.session.get("customer_user_id")
        if not customer_id:
            return None

        try:
            customer = CustomerUser.objects.get(pk=customer_id)
        except CustomerUser.DoesNotExist:
            return None

        self.enforce_csrf(request)
        return (customer, None)
