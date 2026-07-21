"""
Shared django-simple-history get_user hook (Blueprint Section 7.2).

simple_history's default get_user implementation
(simple_history.models._default_get_user) returns request.user unconditionally
whenever request.user.is_authenticated is truthy, then hands that object
straight to HistoricalRecords' history_user FK -- which is hard-typed to
AUTH_USER_MODEL (StaffUser). That's fine for staff-authenticated requests,
but a customer-authenticated request has request.user set to a CustomerUser
instance (apps/accounts/authentication.py, CustomerSessionAuthentication),
and CustomerUser.is_authenticated is also True (it has to be, to satisfy
DRF's permission contract) -- so without this override, any write to a
HistoricalRecords-tracked model made during a customer session raises
ValueError: "HistoricalX.history_user" must be a "StaffUser" instance,
straight out of Django's own ForeignKey descriptor.

Every `history = HistoricalRecords()` declaration across the app models
should use `HistoricalRecords(get_user=get_history_user)` instead.
"""


def get_history_user(request=None, instance=None, **kwargs):
    if request is None:
        return None

    from apps.accounts.models import StaffUser

    user = getattr(request, "user", None)
    return user if isinstance(user, StaffUser) else None
