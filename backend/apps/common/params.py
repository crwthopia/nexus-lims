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


def str_param(value, name, *, max_length):
    """
    A bounded string from client input, defaulting to "" when absent.

    `max_length` is the destination column's, so the check has to be kept
    in step with the model. That is a real cost, and still cheaper than the
    alternative: Django does not enforce max_length on save (only in form
    and serializer validation, neither of which runs on a raw
    request.data read), so without this the ceiling is enforced by
    Postgres, as a 500.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError({name: "Expected a string."})
    if len(value) > max_length:
        raise ValidationError({name: f"Must be at most {max_length} characters."})
    return value
