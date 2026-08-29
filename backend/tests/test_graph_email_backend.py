"""
The Microsoft Graph email backend, and the retry classification that depends
on it.

Every test here mocks `requests`. That is a deliberate limit and worth naming:
these prove the request this backend builds, the response handling, and the
transient/permanent split -- not that Graph accepts any of it. Only
`send_test_email` against a real tenant proves that, for the same reason the
SMTP path needed it: DNS, admin consent, the Exchange application access
policy and the mailbox itself exist only in a deployment.

The one thing these tests do assert about a real deployment is negative, and
it matters most: that a client secret never reaches an exception message or a
log line. Failure reasons are written to NotificationRecord.failure_reason and
rendered in the Staff Console.
"""

import base64
import json
from unittest import mock

import pytest
import requests
from django.core.mail import EmailMessage, EmailMultiAlternatives

from apps.notifications.graph import (
    MAX_INLINE_ATTACHMENT_BYTES,
    GraphConfigurationError,
    GraphEmailBackend,
    GraphMessageError,
    GraphSendError,
    _TOKENS,
)
from apps.notifications.tasks import is_transient

SENDER = "lims-notifications@nasatlabs.example"
SECRET = "the-client-secret-that-must-never-be-echoed"

GRAPH_SETTINGS = {
    "GRAPH_MAIL_TENANT_ID": "11111111-1111-1111-1111-111111111111",
    "GRAPH_MAIL_CLIENT_ID": "22222222-2222-2222-2222-222222222222",
    "GRAPH_MAIL_CLIENT_SECRET": SECRET,
    "GRAPH_MAIL_SENDER": SENDER,
    "GRAPH_MAIL_TIMEOUT": 10,
    "GRAPH_MAIL_SAVE_TO_SENT_ITEMS": True,
    "DEFAULT_FROM_EMAIL": SENDER,
}


@pytest.fixture(autouse=True)
def _empty_token_cache():
    """
    The cache is module-level and shared, which is the point of it -- but a
    token left behind by one test would hide a missing token request in the
    next.
    """
    _TOKENS.invalidate()
    yield
    _TOKENS.invalidate()


def _response(status_code, payload=None, headers=None):
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    response.headers = headers or {}
    response.json.return_value = payload if payload is not None else {}
    return response


def _token_response(expires_in=3600):
    return _response(200, {"access_token": "a-bearer-token", "expires_in": expires_in})


@pytest.fixture
def post():
    """
    Patches requests.post for both calls the backend makes.

    Default behaviour: the token request succeeds, and so does the send. A
    test that wants a failure overrides `side_effect`.
    """
    with mock.patch("apps.notifications.graph.requests.post") as patched:
        patched.side_effect = lambda url, **kwargs: (
            _token_response() if "oauth2" in url else _response(202)
        )
        yield patched


def _backend(**overrides):
    with mock.patch.multiple("django.conf.settings", **{**GRAPH_SETTINGS, **overrides}):
        return GraphEmailBackend()


def _message(**overrides):
    fields = {
        "subject": "Sample NAS-2026-0001 is in testing",
        "body": "Your sample has entered testing.",
        "from_email": SENDER,
        "to": ["customer@example.org"],
    }
    fields.update(overrides)
    return EmailMessage(**fields)


def _send_call(post_mock):
    """The sendMail call, ignoring the token call that precedes it."""
    return next(c for c in post_mock.call_args_list if "sendMail" in c.args[0])


def _sent_message(post_mock):
    return _send_call(post_mock).kwargs["json"]["message"]


# --- The request it builds -------------------------------------------------

def test_a_send_posts_to_the_shared_mailbox(post):
    assert _backend().send_messages([_message()]) == 1

    assert _send_call(post).args[0] == (
        f"https://graph.microsoft.com/v1.0/users/{SENDER}/sendMail"
    )


def test_the_message_carries_subject_body_and_recipient(post):
    _backend().send_messages([_message()])

    message = _sent_message(post)
    assert message["subject"] == "Sample NAS-2026-0001 is in testing"
    assert message["body"] == {
        "contentType": "Text",
        "content": "Your sample has entered testing.",
    }
    assert message["toRecipients"] == [{"emailAddress": {"address": "customer@example.org"}}]


def test_the_send_is_authenticated_with_a_bearer_token(post):
    _backend().send_messages([_message()])

    assert _send_call(post).kwargs["headers"]["Authorization"] == "Bearer a-bearer-token"


def test_cc_bcc_and_reply_to_are_carried_through(post):
    _backend().send_messages([
        _message(cc=["qa@nasatlabs.example"], bcc=["archive@nasatlabs.example"],
                 reply_to=["lab@nasatlabs.example"])
    ])

    message = _sent_message(post)
    assert message["ccRecipients"] == [{"emailAddress": {"address": "qa@nasatlabs.example"}}]
    assert message["bccRecipients"] == [
        {"emailAddress": {"address": "archive@nasatlabs.example"}}
    ]
    assert message["replyTo"] == [{"emailAddress": {"address": "lab@nasatlabs.example"}}]


def test_a_display_name_survives(post):
    _backend().send_messages([_message(from_email=f"NexusLIMS <{SENDER}>")])

    assert _sent_message(post)["from"] == {
        "emailAddress": {"address": SENDER, "name": "NexusLIMS"}
    }


def test_an_html_alternative_wins_over_the_plain_text(post):
    """
    Graph takes one body. Sending the plain part while an HTML one exists
    would quietly discard the version that was actually designed.
    """
    message = EmailMultiAlternatives(
        subject="Report ready", body="plain", from_email=SENDER, to=["c@example.org"]
    )
    message.attach_alternative("<p>rich</p>", "text/html")

    _backend().send_messages([message])

    assert _sent_message(post)["body"] == {"contentType": "HTML", "content": "<p>rich</p>"}


def test_sent_items_can_be_turned_off(post):
    _backend(GRAPH_MAIL_SAVE_TO_SENT_ITEMS=False).send_messages([_message()])

    assert _send_call(post).kwargs["json"]["saveToSentItems"] is False


# --- Attachments -----------------------------------------------------------

def test_a_small_attachment_is_base64_encoded_inline(post):
    message = _message()
    message.attach("results.csv", b"analyte,value\\nPb,0.01\\n", "text/csv")

    _backend().send_messages([message])

    attachment = _sent_message(post)["attachments"][0]
    assert attachment["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert attachment["name"] == "results.csv"
    assert attachment["contentType"] == "text/csv"
    assert base64.b64decode(attachment["contentBytes"]) == b"analyte,value\\nPb,0.01\\n"


def test_an_oversized_attachment_raises_rather_than_sending_without_it(post):
    """
    The failure this prevents is a report notification that arrives looking
    complete and is missing the report.
    """
    message = _message()
    message.attach("huge.pdf", b"x" * (MAX_INLINE_ATTACHMENT_BYTES + 1), "application/pdf")

    with pytest.raises(GraphMessageError, match="over the"):
        _backend().send_messages([message])


# --- Refusing to send as the wrong address ---------------------------------

def test_sending_as_a_different_address_is_refused(post):
    """
    Graph rewrites the From to the mailbox in the URL, so this would arrive
    looking like it came from somewhere it did not -- and the customer's
    reply would go there.
    """
    with pytest.raises(GraphMessageError, match="silently rewritten"):
        _backend().send_messages([_message(from_email="someone-else@nasatlabs.example")])


def test_a_message_with_no_recipients_is_refused(post):
    with pytest.raises(GraphMessageError, match="no recipients"):
        _backend().send_messages([_message(to=[])])


# --- The token cache -------------------------------------------------------

def test_the_token_is_fetched_once_and_reused(post):
    backend = _backend()
    backend.send_messages([_message()])
    backend.send_messages([_message()])

    token_calls = [c for c in post.call_args_list if "oauth2" in c.args[0]]
    assert len(token_calls) == 1


def test_a_401_refreshes_the_token_and_retries_once(post):
    """
    Without this, rotating the client secret abandons whatever was in flight
    -- and secrets rotate on a schedule, so it would happen on a calendar.
    """
    responses = iter([_token_response(), _response(401), _token_response(), _response(202)])
    post.side_effect = lambda url, **kwargs: next(responses)

    assert _backend().send_messages([_message()]) == 1


def test_a_second_401_is_not_retried_forever(post):
    responses = iter([_token_response(), _response(401), _token_response(), _response(401)])
    post.side_effect = lambda url, **kwargs: next(responses)

    with pytest.raises(GraphSendError):
        _backend().send_messages([_message()])


# --- Failures, and whether they are worth retrying -------------------------

@pytest.mark.parametrize("status", [429, 500, 503, 504])
def test_throttling_and_service_errors_are_transient(post, status):
    post.side_effect = lambda url, **kwargs: (
        _token_response() if "oauth2" in url else _response(status)
    )

    with pytest.raises(GraphSendError) as caught:
        _backend().send_messages([_message()])

    assert is_transient(caught.value) is True


@pytest.mark.parametrize("status", [400, 403, 404])
def test_configuration_failures_are_permanent(post, status):
    """
    Retrying a 403 eight times does not create an application access policy;
    it just delays the SystemFailure that tells somebody to.
    """
    post.side_effect = lambda url, **kwargs: (
        _token_response() if "oauth2" in url else _response(status)
    )

    with pytest.raises(GraphSendError) as caught:
        _backend().send_messages([_message()])

    assert is_transient(caught.value) is False


def test_an_unreachable_graph_is_transient(post):
    post.side_effect = lambda url, **kwargs: (
        _token_response() if "oauth2" in url else (_ for _ in ()).throw(
            requests.ConnectionError("connection reset")
        )
    )

    with pytest.raises(GraphSendError) as caught:
        _backend().send_messages([_message()])

    assert caught.value.status_code is None
    assert is_transient(caught.value) is True


def test_missing_configuration_is_permanent():
    with pytest.raises(GraphConfigurationError) as caught:
        _backend(GRAPH_MAIL_CLIENT_SECRET="").send_messages([_message()])

    assert "GRAPH_MAIL_CLIENT_SECRET" in str(caught.value)
    assert is_transient(caught.value) is False


def test_a_403_names_the_likely_cause(post):
    """
    An operator reading the Staff Console should not have to look up what
    Graph's 403 means for this application.
    """
    post.side_effect = lambda url, **kwargs: (
        _token_response()
        if "oauth2" in url
        else _response(403, {"error": {"code": "ErrorAccessDenied"}})
    )

    with pytest.raises(GraphSendError, match="application access policy"):
        _backend().send_messages([_message()])


def test_a_retry_after_header_is_kept(post):
    post.side_effect = lambda url, **kwargs: (
        _token_response()
        if "oauth2" in url
        else _response(429, headers={"Retry-After": "120"})
    )

    with pytest.raises(GraphSendError) as caught:
        _backend().send_messages([_message()])

    assert caught.value.retry_after == 120


# --- fail_silently ---------------------------------------------------------

def test_fail_silently_reports_nothing_sent_rather_than_raising(post):
    post.side_effect = lambda url, **kwargs: (
        _token_response() if "oauth2" in url else _response(403)
    )

    with mock.patch.multiple("django.conf.settings", **GRAPH_SETTINGS):
        backend = GraphEmailBackend(fail_silently=True)

    assert backend.send_messages([_message()]) == 0


# --- The secret ------------------------------------------------------------

def test_the_client_secret_never_reaches_an_exception_message(post):
    """
    requests exceptions can carry the PreparedRequest, and the token
    request's body *is* the client secret. Failure reasons are written to
    NotificationRecord.failure_reason and rendered in the Staff Console, so
    a leak here is a leak into the database and the browser.
    """
    def explode(url, **kwargs):
        raise requests.ConnectionError(f"failed sending body: {json.dumps(kwargs.get('data'))}")

    post.side_effect = explode

    with pytest.raises(GraphSendError) as caught:
        _backend().send_messages([_message()])

    assert SECRET not in str(caught.value)
    assert SECRET not in repr(caught.value)


def test_a_refused_credential_says_so_without_quoting_it(post):
    post.side_effect = lambda url, **kwargs: _response(
        401, {"error": {"code": "invalid_client"}}
    )

    with pytest.raises(GraphSendError) as caught:
        _backend().send_messages([_message()])

    assert "client secret" in str(caught.value)
    assert SECRET not in str(caught.value)


# --- The bug that made this split necessary --------------------------------

def test_a_message_the_backend_refuses_to_build_is_never_retried(post):
    """
    These once raised GraphSendError with no status code, which is exactly
    the shape of an unreachable endpoint -- so a From mismatch or a
    too-large attachment looked like a network blip and cost eight attempts
    before anybody was told. They are permanent, and nothing about waiting
    changes them.
    """
    message = _message()
    message.attach("huge.pdf", b"x" * (MAX_INLINE_ATTACHMENT_BYTES + 1), "application/pdf")

    for bad, why in (
        (lambda: _backend().send_messages([_message(from_email="other@nasatlabs.example")]),
         "from mismatch"),
        (lambda: _backend().send_messages([_message(to=[])]), "no recipients"),
        (lambda: _backend().send_messages([message]), "oversized attachment"),
    ):
        with pytest.raises(GraphMessageError) as caught:
            bad()
        assert is_transient(caught.value) is False, why


def test_an_unreachable_endpoint_is_still_transient_after_the_split(post):
    """The other half of the same distinction, held in place."""
    post.side_effect = requests.ConnectionError("connection reset")

    with pytest.raises(GraphSendError) as caught:
        _backend().send_messages([_message()])

    assert not isinstance(caught.value, GraphMessageError)
    assert is_transient(caught.value) is True
