"""
Coercion of client-supplied ids and strings, failing as a 400 rather than
a 500.

Django's ORM takes a lookup value to be already of the field's type:
`.filter(sample_id="abc")` raises ValueError, not DoesNotExist. Passing a
raw query-string value straight into a filter therefore turns a malformed
URL into a server error -- which is both the wrong answer (the client's
request was bad, the server is fine) and a monitoring problem, since a
crawler walking the API fills the error tracker with alerts that read like
an outage.

The same applies to a CharField's max_length: unvalidated text reaches
Postgres and comes back as `value too long for type character
varying(255)`, a 500 quoting a database column at someone who filled in a
form field.

These are deliberately small and explicit rather than a filter backend.
Every call site here already reads its own parameters by hand -- see the
`get_queryset` overrides across the app, which exist because DRF silently
ignores query params it does not recognise -- so the fix that fits is one
that wraps the read, not one that replaces the pattern.
"""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError


def int_param(value, name):
    """
    An integer id from client input, or None when absent.

    Raises DRF's ValidationError (a 400) for anything non-numeric, keyed by
    the parameter name so the response says which one was wrong.
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError({name: f"Expected a numeric id, got {value!r}."}) from None


def str_param(value, name, *, max_length=None):
    """
    A bounded string from client input, defaulting to "" when absent.

    `max_length` is the destination column's, so the check has to be kept
    in step with the model. That is a real cost, and still cheaper than the
    alternative: Django does not enforce max_length on save (only in form
    and serializer validation, neither of which runs on a raw
    request.data read), so without this the ceiling is enforced by
    Postgres, as a 500.

    Omit it for a TextField, which has no ceiling to enforce. The type
    check still earns its place there: a CharField or TextField handed a
    list stringifies it rather than failing, so `["a", "b"]` is stored as
    the literal text `['a', 'b']` -- a custody location or a reviewer's
    comment that reads like a bug report, written into a regulated record
    that is meant to be evidence.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError({name: "Expected a string."})
    if max_length is not None and len(value) > max_length:
        raise ValidationError({name: f"Must be at most {max_length} characters."})
    return value


def body_dict(request):
    """
    `request.data` as a mapping, or a 400.

    JSON's top level may legally be an array, a string, or null, and DRF
    hands whatever it parsed straight through without opinion. Every
    hand-rolled action in this codebase then treats `request.data` as a
    dict -- `.get(...)` on it, or `{**request.data}` -- so a body of
    `[1, 2]` raises AttributeError or TypeError. That is a 500 on an input
    the client is entitled to send and the parser is entitled to accept.

    Serializer-backed writes need no such guard: DRF answers a non-dict
    body with "Invalid data. Expected a dictionary", a 400, before any of
    this code runs. It is only the actions that read the body by hand that
    are exposed -- the same trade the hand-rolled query-param reads make
    above, and the same fix.

    An absent body is a mapping (`{}`) and passes: most of these actions
    take an optional field, and a bare POST is the ordinary way to call
    them.
    """
    data = request.data
    if not isinstance(data, Mapping):
        raise ValidationError(
            {"detail": "Expected a JSON object at the top level of the request body."}
        )
    return data


def bool_param(value, name, *, default=None):
    """
    A boolean from a JSON body, or `default` when absent.

    Strict about the type rather than falling back to Python truthiness,
    because truthiness gets this exactly backwards on the wire: the string
    `"false"` -- which is what a form-encoded POST sends, and what a
    hand-written client sends when it forgets to serialise JSON -- is
    truthy. On a receipt checklist that turns "the seal was broken" into
    "the seal was intact", silently, in a regulated record.
    """
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValidationError({name: "Expected true or false."})
    return value


def decimal_param(value, name):
    """
    A Decimal from client input, or None when absent.

    Accepts a JSON number or a numeric string; refuses anything else. Note
    that a float arriving over JSON is converted via `str()` first, so
    `0.1` stores as Decimal("0.1") rather than the binary-float expansion
    Decimal(0.1) would give -- a distinction that matters on a column
    holding a measured temperature.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValidationError({name: f"Expected a number, got {value!r}."})
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValidationError({name: f"Expected a number, got {value!r}."}) from None


def datetime_param(value, name, *, not_future=False):
    """
    An aware datetime from an ISO-8601 string, or None when absent.

    Naive input is interpreted in the current timezone rather than
    rejected: a receiving clerk typing `2026-09-10T17:40` means the wall
    clock in front of them, and `USE_TZ` is on, so storing that naive would
    raise a RuntimeWarning and land as UTC -- eight hours out in Manila.

    `not_future` is the guard that matters for anything ALCOA calls
    *contemporaneous*: an operator-supplied event time may be backdated to
    when the courier actually arrived, but a receipt cannot be recorded as
    having happened after now.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValidationError({name: "Expected an ISO-8601 datetime string."})
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValidationError({name: f"Expected an ISO-8601 datetime, got {value!r}."})
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    if not_future and parsed > timezone.now():
        raise ValidationError({name: "Cannot be in the future."})
    return parsed
