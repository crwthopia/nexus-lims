from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.accounts.customer_views import (
    CustomerLoginView,
    CustomerLogoutView,
    CustomerMeView,
    CustomerMFAConfirmView,
    CustomerMFAEnableView,
    CustomerRegisterView,
    CustomerVerifyEmailView,
)
from apps.accounts.views import CustomerUserViewSet, ESignatureViewSet, RoleViewSet, StaffUserViewSet

router = SimpleRouter()
router.register("roles", RoleViewSet, basename="role")
router.register("staff-users", StaffUserViewSet, basename="staffuser")
router.register("customer-users", CustomerUserViewSet, basename="customeruser")
router.register("e-signatures", ESignatureViewSet, basename="esignature")

# Blueprint Section 6: Auth (customer) resource group.
customer_auth_urlpatterns = [
    path("auth/customer/register", CustomerRegisterView.as_view(), name="customer-register"),
    path("auth/customer/verify-email", CustomerVerifyEmailView.as_view(), name="customer-verify-email"),
    path("auth/customer/login", CustomerLoginView.as_view(), name="customer-login"),
    path("auth/customer/logout", CustomerLogoutView.as_view(), name="customer-logout"),
    path("auth/customer/me", CustomerMeView.as_view(), name="customer-me"),
    path("auth/customer/mfa/enable", CustomerMFAEnableView.as_view(), name="customer-mfa-enable"),
    path("auth/customer/mfa/confirm", CustomerMFAConfirmView.as_view(), name="customer-mfa-confirm"),
]

urlpatterns = router.urls + customer_auth_urlpatterns
