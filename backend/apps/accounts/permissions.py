"""
Role-based permission helper (Blueprint Section 7.1 RBAC, FR-C3-02).

StaffUser.role membership alone is checked here; the finer-grained
per-test-method competency check (instrument_certifications) is applied
separately at the point of TestResult entry (apps/testing/serializers.py).
"""

from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomerUser


class HasRole(BasePermission):
    """
    Grants access if the authenticated StaffUser holds at least one of
    `required_roles` (apps.accounts.models.Role.RoleName values), or is a
    superuser (System Administrator escape hatch, consistent with FR-E17-02's
    admin-only audit log access being a superuser-level concern).

    CustomerUser is a separate, unrelated model (Blueprint Section 2.1 item 7)
    and never satisfies HasRole; customer-facing endpoints should use a
    different permission class once the customer auth backend is wired.
    """

    required_roles: tuple[str, ...] = ()

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        roles = getattr(view, "required_roles", None) or self.required_roles
        if not roles:
            return True
        return user.roles.filter(name__in=roles).exists()


def roles_required(*role_names):
    """Factory returning a HasRole subclass fixed to the given role names."""
    return type("HasRole_" + "_".join(role_names), (HasRole,), {"required_roles": role_names})


class IsCustomerAuthenticated(BasePermission):
    """
    Companion to HasRole for the other identity domain (Blueprint Section
    2.1 item 7): grants access only when request.user was populated by
    CustomerSessionAuthentication (apps/accounts/authentication.py), i.e. is
    a CustomerUser instance. Never true for a StaffUser/AnonymousUser
    request, exactly as HasRole is never true for a CustomerUser request --
    the two permission classes are deliberately disjoint, not layered.
    """

    def has_permission(self, request, view):
        return isinstance(request.user, CustomerUser)
