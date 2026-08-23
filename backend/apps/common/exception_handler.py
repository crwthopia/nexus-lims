"""
Turn a refused delete into a 409 instead of a 500.

Deleting a row another row points at raises django.db.models.deletion.
ProtectedError, which DRF does not know about -- so it escaped as an
unhandled exception and the client got a 500. Three routes did this:
DELETE on test-methods, training-sessions and training-courses, each
reachable by a fully authorised member of staff doing something entirely
reasonable (retiring a method that has been used, cancelling a course
somebody enrolled in).

A 500 is the wrong answer twice over. It says "this server is broken" for
what is really "no, and here is why", and it puts a traceback in the log
for an outcome the schema deliberately arranged -- on_delete=PROTECT is the
database being asked to refuse exactly this.

409 rather than 400: the request was well-formed and the caller had every
right to make it. What stopped it is the current state of other rows, which
is what 409 Conflict describes, and it matches the 409 the report download
endpoint already returns for a report that exists but is not ready yet.

The referencing objects are named in the response. A bare refusal leaves
the caller guessing which of a dozen relationships blocked them, and the
information is not sensitive: anyone who can attempt the delete can already
list what points at it.
"""

from django.db.models.deletion import ProtectedError, RestrictedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def _describe(objects, limit=5):
    """A short, stable description of what is blocking the delete."""
    listed = [str(obj) for obj in list(objects)[:limit]]
    remaining = len(objects) - len(listed)
    if remaining > 0:
        listed.append(f"and {remaining} more")
    return listed


def protected_aware_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    # RestrictedError subclasses ProtectedError's sibling, not ProtectedError
    # itself, so both are named rather than relying on one catching the other.
    if isinstance(exc, (ProtectedError, RestrictedError)):
        blockers = exc.protected_objects if isinstance(exc, ProtectedError) else exc.restricted_objects
        return Response(
            {
                "detail": (
                    "Cannot delete this record because other records still "
                    "reference it."
                ),
                "referenced_by": _describe(blockers),
            },
            status=status.HTTP_409_CONFLICT,
        )

    return None
