"""
A Django email backend that sends through Microsoft Graph, as a shared mailbox.

Why this exists rather than SMTP to Exchange Online: a shared mailbox has no
password and no licence, so it cannot authenticate over SMTP at all. The
workaround -- authenticate as a licensed user and send as the shared mailbox --
is refused by Exchange with `5.7.60 Client does not have permissions to send as
this sender`, because SMTP AUTH requires the From to match the authenticating
mailbox. Microsoft is also retiring SMTP AUTH client submission in Exchange
Online, which makes it a poor foundation for a system that has to stay
validated under ISO/IEC 17025:2017 clause 7.11.2.

Graph has neither problem. Application permissions send *as* a mailbox rather
than *from* an account, so the shared mailbox is the sender, and the credential
is an Entra client secret: rotatable, revocable, and auditable in a way an SMTP
password in an environment variable is not.

The credential belongs to its own app registration, separate from the SSO one
in AUTH_ADFS. Mail and login fail independently, and rotating the mail secret
must never be able to lock the laboratory out of the system.

## The permission is dangerous by default

`Mail.Send` as an *application* permission is tenant-wide: it sends as anybody,
including the Laboratory Director. It has to be narrowed in Exchange Online
with an application access policy scoping this app to a mail-enabled security
group containing only the notifications mailbox. That is a step in the Entra
console, not something this module can assert, so it is written down in
infra/m365-graph-mail.md and repeated here because a leaked secret without that
policy is a very different incident from one with it.

## What this module deliberately does not do

No `msal`. The client-credentials flow is one form POST, and a dependency whose
token cache we would then have to reason about is a poor trade for the twenty
lines below.

Attachments over the Graph inline limit raise rather than send without them.
Nothing in the notification path attaches anything today, but a backend that
silently drops an attachment is exactly the failure this codebase keeps trying
not to ship.
"""

import base64
import logging
import threading
import time
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
LOGIN_ENDPOINT = "https://login.microsoftonline.com"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"

# Graph rejects a sendMail request whose total body exceeds 4 MB, and the
# base64 encoding of an attachment costs about a third on top of its own size.
# Anything larger needs a draft message plus an upload session, which is a
# different API shape and is not built here -- so this is the line at which
# this backend says so out loud rather than sending a message without its
# attachment.
MAX_INLINE_ATTACHMENT_BYTES = 3 * 1024 * 1024

# Refresh this far before the token actually expires. A token that dies in
# flight costs a round trip and a retry; one refreshed slightly early costs
# nothing, because the token endpoint is not rate-limited at this volume.
_TOKEN_REFRESH_MARGIN_SECONDS = 300


class GraphPermanentError(Exception):
    """
    Base for the failures that no retry can fix.

    Separate from GraphSendError on purpose. A GraphSendError with no status
    code means the request never reached Graph -- DNS, TLS, a dropped
    connection -- which is the *most* retryable case there is. A message this
    backend refused to build has the same shape, no status code and no HTTP
    round trip, and is the least retryable case there is. Folding them into
    one class made a From mismatch look like a network blip and cost it eight
    attempts before anybody was told.
    """


class GraphConfigurationError(GraphPermanentError):
    """Graph is the active backend but was not given what it needs to send."""


class GraphMessageError(GraphPermanentError):
    """
    This message cannot be represented as a Graph sendMail request.

    Refused here rather than sent in a degraded form: a notification that
    arrives without its attachment, or from an address the application did
    not choose, is worse than one that visibly fails.
    """


class GraphSendError(Exception):
    """
    A send that Graph refused, or that never reached it.

    Carries `status_code` so `apps.notifications.tasks.is_transient` can tell
    "try again in a minute" from "this will never work", which is the whole
    basis of the retry policy. `status_code` is None when the request did not
    get far enough to have one -- a transport failure, and retryable. A
    message that was never valid raises GraphMessageError instead.

    The message is built from the status and Graph's own error code, never
    from the request that produced it: that request carries a bearer token,
    and failure reasons are written to NotificationRecord.failure_reason and
    read in the Staff Console.
    """

    def __init__(self, message, status_code=None, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class _TokenCache:
    """
    One token per process, shared across the worker's threads.

    Celery runs a small fixed pool of long-lived processes, so caching here
    turns two HTTP round trips per notification into one. The lock matters
    because a burst from the retry sweep would otherwise have every thread
    fetch its own token at the same moment.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._token = None
        self._expires_at = 0.0

    def get(self, fetch):
        with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            token, expires_in = fetch()
            self._token = token
            self._expires_at = time.monotonic() + max(
                expires_in - _TOKEN_REFRESH_MARGIN_SECONDS, 60
            )
            return token

    def invalidate(self):
        with self._lock:
            self._token = None
            self._expires_at = 0.0


_TOKENS = _TokenCache()


def _address_of(value):
    """The bare address from a possibly display-named `Name <a@b>` string."""
    return parseaddr(value)[1]


def _display_name_of(value):
    return parseaddr(value)[0]


class GraphEmailBackend(BaseEmailBackend):
    """
    Sends via POST /users/{mailbox}/sendMail.

    Stateless between messages apart from the shared token cache: Graph is
    HTTP, so there is no connection to open or close and `open()`/`close()`
    from BaseEmailBackend stay no-ops.
    """

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.tenant_id = settings.GRAPH_MAIL_TENANT_ID
        self.client_id = settings.GRAPH_MAIL_CLIENT_ID
        self.client_secret = settings.GRAPH_MAIL_CLIENT_SECRET
        self.sender = settings.GRAPH_MAIL_SENDER
        self.timeout = settings.GRAPH_MAIL_TIMEOUT
        self.save_to_sent_items = settings.GRAPH_MAIL_SAVE_TO_SENT_ITEMS

    def send_messages(self, email_messages):
        """
        Returns the number sent, which is Django's contract and what
        `send_mail` hands back to `send_notification`.

        Raises on the first failure unless fail_silently, because the caller
        decides whether a failure is worth retrying and it cannot decide
        about an exception it never sees.
        """
        if not email_messages:
            return 0

        missing = [
            name
            for name, value in (
                ("GRAPH_MAIL_TENANT_ID", self.tenant_id),
                ("GRAPH_MAIL_CLIENT_ID", self.client_id),
                ("GRAPH_MAIL_CLIENT_SECRET", self.client_secret),
                ("GRAPH_MAIL_SENDER", self.sender),
            )
            if not value
        ]
        if missing:
            # Reachable in DEBUG, where the startup checks in settings.py do
            # not run. In production this has already been refused at boot.
            exc = GraphConfigurationError(
                f"The Graph email backend is active but {', '.join(missing)} "
                f"{'is' if len(missing) == 1 else 'are'} unset. Nothing can be sent."
            )
            if self.fail_silently:
                return 0
            raise exc

        sent = 0
        for message in email_messages:
            try:
                self._send(message)
            except Exception:
                if not self.fail_silently:
                    raise
                continue
            sent += 1
        return sent

    # --- The two HTTP calls ------------------------------------------------

    def _access_token(self):
        return _TOKENS.get(self._fetch_token)

    def _fetch_token(self):
        url = f"{LOGIN_ENDPOINT}/{self.tenant_id}/oauth2/v2.0/token"
        try:
            response = requests.post(
                url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": GRAPH_SCOPE,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            # type(exc).__name__ rather than str(exc): a requests exception can
            # carry the PreparedRequest, and this particular request body is
            # the client secret.
            raise GraphSendError(
                f"Could not reach the Entra token endpoint ({type(exc).__name__})."
            ) from None

        if response.status_code != 200:
            raise GraphSendError(
                "Entra refused the client credentials "
                f"(HTTP {response.status_code}, {_error_code(response)}). "
                "Usually an expired client secret, or the wrong tenant.",
                status_code=response.status_code,
            )

        payload = response.json()
        return payload["access_token"], int(payload.get("expires_in", 3600))

    def _send(self, message):
        body = _to_graph_message(message, self.sender, self.save_to_sent_items)
        url = f"{GRAPH_ENDPOINT}/users/{self.sender}/sendMail"

        response = self._post(url, body, self._access_token())

        if response.status_code == 401:
            # The token expired between the cache check and the request, or
            # was revoked. Worth exactly one retry with a fresh one: without
            # this, every secret rotation abandons whatever was in flight.
            logger.info("Graph returned 401; refreshing the token and retrying once")
            _TOKENS.invalidate()
            response = self._post(url, body, self._access_token())

        if response.status_code not in (200, 202):
            raise GraphSendError(
                _failure_message(response, self.sender),
                status_code=response.status_code,
                retry_after=_retry_after(response),
            )

    def _post(self, url, body, token):
        try:
            return requests.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise GraphSendError(
                f"Could not reach Microsoft Graph ({type(exc).__name__})."
            ) from None


# --- Turning a Django EmailMessage into Graph's shape -----------------------

def _to_graph_message(message, sender, save_to_sent_items):
    if not message.recipients():
        # Django's SMTP backend returns False here rather than sending. Raising
        # is the more useful answer inside a notification task, where a message
        # with no recipients is a bug upstream and silence would hide it.
        raise GraphMessageError("The message has no recipients.")

    from_address = _address_of(message.from_email or sender)
    if from_address.lower() != sender.lower():
        # Graph sends as the mailbox in the URL whatever this says, so a
        # mismatch means the recipient sees a different From than the code
        # believes it used -- and the reply address in customer mail is not a
        # detail to be quietly wrong about.
        raise GraphMessageError(
            f"This message is from {from_address} but the backend sends as {sender}. "
            "Graph sends as the mailbox it is scoped to, so the From would be "
            "silently rewritten. Set DEFAULT_FROM_EMAIL to the shared mailbox."
        )

    content_type, content = _body_of(message)

    graph_message = {
        "subject": message.subject,
        "body": {"contentType": content_type, "content": content},
        "toRecipients": _recipients(message.to),
    }
    if message.cc:
        graph_message["ccRecipients"] = _recipients(message.cc)
    if message.bcc:
        graph_message["bccRecipients"] = _recipients(message.bcc)
    if message.reply_to:
        graph_message["replyTo"] = _recipients(message.reply_to)

    display_name = _display_name_of(message.from_email or "")
    if display_name:
        graph_message["from"] = {
            "emailAddress": {"address": sender, "name": display_name}
        }

    attachments = [_attachment(a) for a in getattr(message, "attachments", [])]
    if attachments:
        graph_message["attachments"] = attachments

    return {"message": graph_message, "saveToSentItems": bool(save_to_sent_items)}


def _body_of(message):
    """
    Graph takes one body, so an HTML alternative wins over the plain text.

    Django's EmailMultiAlternatives carries both and lets the client choose;
    Graph does not offer that, and sending the plain part while an HTML one
    exists would quietly discard the version that was actually designed.
    """
    for content, mimetype in getattr(message, "alternatives", []) or []:
        if mimetype == "text/html":
            return "HTML", content
    if message.content_subtype == "html":
        return "HTML", message.body
    return "Text", message.body


def _recipients(addresses):
    return [{"emailAddress": {"address": _address_of(a)}} for a in addresses]


def _attachment(attachment):
    if not isinstance(attachment, tuple):
        # A MIMEBase instance. Supporting it means re-deriving the filename
        # and content type from headers, which nothing here needs yet.
        raise GraphMessageError(
            "This backend takes attachments as (filename, content, mimetype) "
            "tuples; a raw MIME part is not supported."
        )

    filename, content, mimetype = attachment
    if isinstance(content, str):
        content = content.encode("utf-8")

    if len(content) > MAX_INLINE_ATTACHMENT_BYTES:
        raise GraphMessageError(
            f"Attachment {filename!r} is {len(content)} bytes, over the "
            f"{MAX_INLINE_ATTACHMENT_BYTES}-byte limit for a single sendMail "
            "request. Graph needs a draft plus an upload session for that, "
            "which this backend does not implement -- link to the document "
            "instead of attaching it."
        )

    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": filename,
        "contentType": mimetype or "application/octet-stream",
        "contentBytes": base64.b64encode(content).decode("ascii"),
    }


# --- Reading Graph's failures ----------------------------------------------

def _error_code(response):
    """Graph's own error code, which names the cause far better than the status."""
    try:
        return response.json().get("error", {}).get("code") or "no error code"
    except ValueError:
        return "unparseable response body"


def _failure_message(response, sender):
    code = _error_code(response)
    hint = {
        403: (
            f" Usually the Exchange application access policy does not grant this app "
            f"access to {sender}, or Mail.Send has not been admin-consented."
        ),
        404: f" Usually {sender} is not a mailbox in this tenant.",
        429: " Graph is throttling this mailbox; the retry sweep will pick it up.",
    }.get(response.status_code, "")
    return f"Graph refused the send (HTTP {response.status_code}, {code}).{hint}"


def _retry_after(response):
    try:
        return int(response.headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        return None
