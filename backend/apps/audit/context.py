"""
Who is acting, for code that is nowhere near the request.

FR-E17-01 requires every create/update/delete on a regulated entity to
write an AuditLogEntry naming the actor, and AuditLogEntry.actor_type
covers three of them: staff, customer, system. django-simple-history cannot
express the latter two -- its history_user is a ForeignKey to StaffUser, so
apps/accounts/history.py correctly returns None for a customer or a
background task rather than raising. Correct for that column, and the
reason a customer self-enrolment and a system-issued credit note were both
recorded as having no actor at all.

The signal receivers that write AuditLogEntry run inside Model.save(), far
below any view, with no request in scope. A ContextVar carries the actor
down to them.

ContextVar rather than threading.local: it is what asgiref propagates
across the sync/async boundary, so this keeps working if any of these
views later become async, where a thread-local silently would not. Each
entry point sets it at the very start of its unit of work -- middleware per
request, task_prerun per task -- exactly as the RLS session variables are
set (apps/accounts/middleware.py, apps/common/rls.py), and for the same
reason: one place per entry point means a view or task added later cannot
forget.

The default is `system` with no actor_id, and that is a claim worth being
precise about: it means "not a person acting through the API" -- a beat
task, a management command, a shell session -- which is exactly what the
SYSTEM actor_type denotes. It is not a stand-in for "unknown". Every path
that does have a person sets the actor explicitly at its entry point, so a
row can only fall back to this default by running outside all of them.
"""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    actor_type: str
    actor_id: int | None = None


# The literal rather than AuditLogEntry.ActorType.SYSTEM: this module is
# imported from middleware, which is loaded before the app registry is
# ready, so it cannot import models at module scope. The receivers that
# write rows use the enum; tests assert the two agree.
_SYSTEM = Actor(actor_type="system", actor_id=None)

_current_actor: ContextVar[Actor] = ContextVar("audit_actor", default=_SYSTEM)


def set_actor(actor_type, actor_id=None):
    """Returns the token needed to restore the previous value."""
    return _current_actor.set(Actor(actor_type=actor_type, actor_id=actor_id))


def reset_actor(token):
    _current_actor.reset(token)


def get_actor():
    return _current_actor.get()
