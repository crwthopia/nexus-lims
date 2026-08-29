"""
The production SMTP configuration, and the startup checks that stop a
half-configured one from shipping.

The failure this guards against is specific and quiet: with DEBUG off, the
console backend prints to a log nobody reads and the SMTP backend with no
host tries localhost:25. Either way a customer never receives their
verification link, the notification register fills with failed rows, and the
first person to notice is the customer.

`config/settings.py` runs its checks at import, so each one is exercised by
re-importing the module under a patched environment rather than by calling a
function -- which is also the only way to prove they fire at *startup*
rather than at first send.
"""

import importlib
import os
import sys
from unittest import mock

import pytest
from django.conf import settings
from django.core import mail
from django.core.management import CommandError, call_command

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

BASE_ENV = {
    "DJANGO_DEBUG": "false",
    "DJANGO_SECRET_KEY": "a-real-key-for-this-test-only-not-the-dev-default",
    "AZURE_AD_TENANT_ID": "00000000-0000-0000-0000-000000000000",
    "AZURE_AD_CLIENT_ID": "00000000-0000-0000-0000-000000000000",
    "AZURE_AD_CLIENT_SECRET": "placeholder",
}


def _reimport_settings(**overrides):
    """
    Re-run config/settings.py under a patched environment.

    Restores the already-imported module afterwards: leaving a half-imported
    settings module in sys.modules would break every test that ran after this
    one, in ways that look nothing like the cause.
    """
    env = {**BASE_ENV, **overrides}
    saved = sys.modules.pop("config.settings", None)
    try:
        with mock.patch.dict(os.environ, env, clear=False):
            return importlib.import_module("config.settings")
    finally:
        if saved is not None:
            sys.modules["config.settings"] = saved


GRAPH_BACKEND = "apps.notifications.graph.GraphEmailBackend"


def _graph_env(**overrides):
    env = {
        "DJANGO_EMAIL_BACKEND": GRAPH_BACKEND,
        "DJANGO_DEFAULT_FROM_EMAIL": "lims-notifications@nasatlabs.example",
        "GRAPH_MAIL_TENANT_ID": "11111111-1111-1111-1111-111111111111",
        "GRAPH_MAIL_CLIENT_ID": "22222222-2222-2222-2222-222222222222",
        "GRAPH_MAIL_CLIENT_SECRET": "placeholder",
        "GRAPH_MAIL_SENDER": "lims-notifications@nasatlabs.example",
    }
    env.update(overrides)
    return env


def _smtp_env(**overrides):
    env = {
        "DJANGO_EMAIL_BACKEND": SMTP_BACKEND,
        "DJANGO_DEFAULT_FROM_EMAIL": "no-reply@nasatlabs.example",
        "EMAIL_HOST": "smtp.example",
        "EMAIL_HOST_USER": "no-reply@nasatlabs.example",
        "EMAIL_HOST_PASSWORD": "secret",
    }
    env.update(overrides)
    return env


# --- The timeout, which is the one Django does not default -----------------

def test_a_send_can_never_block_forever():
    """
    smtplib blocks indefinitely on a socket with no timeout, and sending now
    happens in a Celery worker with a small fixed pool. Two hung sends would
    stop the worker without crashing it -- report generation and the
    retention sweep queued behind a mail server that never answers.
    """
    assert settings.EMAIL_TIMEOUT
    assert settings.EMAIL_TIMEOUT > 0


def test_the_timeout_is_configurable():
    module = _reimport_settings(**_smtp_env(EMAIL_TIMEOUT="3"))

    assert module.EMAIL_TIMEOUT == 3


# --- Defaults --------------------------------------------------------------

def test_development_still_uses_the_console_backend():
    """
    Nothing leaves a developer's machine, and the verification links stay
    readable in the runserver log.

    Checked by re-import rather than against the live `settings`: Django's
    test runner replaces EMAIL_BACKEND with locmem so `mail.outbox` works, so
    the running configuration can never show what the default actually is.
    """
    module = _reimport_settings()

    assert module.EMAIL_BACKEND.endswith("console.EmailBackend")


def test_a_fully_configured_smtp_backend_starts():
    module = _reimport_settings(**_smtp_env())

    assert module.EMAIL_BACKEND == SMTP_BACKEND
    assert module.EMAIL_HOST == "smtp.example"


def test_the_transport_defaults_can_reach_directmail():
    """
    The port default used to be 587, which DirectMail does not offer at all --
    its SMTP ports are 25, 80 and 465, and outbound 25 is disabled on ECS. So
    the shipped default could not connect to the provider the deployment
    actually uses, and the failure surfaced as a timeout in a worker.

    The three settings are asserted together because they only mean anything
    together: 465 with STARTTLS is as unusable as 587 was.
    """
    module = _reimport_settings(**_smtp_env())

    assert module.EMAIL_PORT == 465
    assert module.EMAIL_USE_SSL is True
    assert module.EMAIL_USE_TLS is False


def test_starttls_on_587_is_still_available_for_other_relays():
    """The default is DirectMail-shaped, not DirectMail-only."""
    module = _reimport_settings(
        **_smtp_env(EMAIL_PORT="587", EMAIL_USE_TLS="true", EMAIL_USE_SSL="false")
    )

    assert module.EMAIL_PORT == 587
    assert module.EMAIL_USE_TLS is True
    assert module.EMAIL_USE_SSL is False


# --- The startup checks ----------------------------------------------------

def test_smtp_without_a_host_refuses_to_start():
    with pytest.raises(RuntimeError, match="EMAIL_HOST is unset"):
        _reimport_settings(**_smtp_env(EMAIL_HOST=""))


def test_tls_and_ssl_together_refuse_to_start():
    """Django raises on this too -- but only when the first message is sent."""
    with pytest.raises(RuntimeError, match="mutually"):
        _reimport_settings(**_smtp_env(EMAIL_USE_TLS="true", EMAIL_USE_SSL="true"))


def test_neither_tls_nor_ssl_refuses_to_start():
    """
    Not a hypothetical: turning EMAIL_USE_SSL off without turning EMAIL_USE_TLS
    on is one edit, and it leaves verification links crossing the internet in
    the clear -- customer information, under ISO/IEC 17025 clause 4.2.
    """
    with pytest.raises(RuntimeError, match="in the clear"):
        _reimport_settings(**_smtp_env(EMAIL_USE_TLS="false", EMAIL_USE_SSL="false"))


def test_starttls_on_465_refuses_to_start():
    """
    A 465 listener wants the handshake before any SMTP command, so STARTTLS on
    it never completes: the send hangs until EMAIL_TIMEOUT and then fails, once
    per attempt, in a worker.
    """
    with pytest.raises(RuntimeError, match="465 but EMAIL_USE_TLS"):
        _reimport_settings(
            **_smtp_env(EMAIL_PORT="465", EMAIL_USE_TLS="true", EMAIL_USE_SSL="false")
        )


def test_implicit_tls_on_587_refuses_to_start():
    """The same mistake in the other direction -- the shape left behind by
    changing the port away from the default and nothing else."""
    with pytest.raises(RuntimeError, match="587 but EMAIL_USE_SSL"):
        _reimport_settings(
            **_smtp_env(EMAIL_PORT="587", EMAIL_USE_TLS="false", EMAIL_USE_SSL="true")
        )


def test_a_username_without_a_password_refuses_to_start():
    with pytest.raises(RuntimeError, match="must be set together"):
        _reimport_settings(**_smtp_env(EMAIL_HOST_PASSWORD=""))


def test_a_password_without_a_username_refuses_to_start():
    with pytest.raises(RuntimeError, match="must be set together"):
        _reimport_settings(**_smtp_env(EMAIL_HOST_USER=""))


def test_the_development_from_address_refuses_to_start_over_smtp():
    """
    A provider that verifies sending domains rejects every message from an
    unverified From, so this would send nothing while looking configured.
    """
    with pytest.raises(RuntimeError, match="development address"):
        _reimport_settings(**_smtp_env(DJANGO_DEFAULT_FROM_EMAIL="no-reply@nasatlabs.test"))


def test_no_relay_is_needed_when_the_console_backend_is_in_use():
    """The checks are about SMTP, not about email in general -- dev must stay simple."""
    module = _reimport_settings(
        DJANGO_EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        EMAIL_HOST="",
    )

    assert module.EMAIL_HOST == ""


# --- The test-send command -------------------------------------------------

def test_the_command_sends_one_message():
    mail.outbox.clear()

    call_command("send_test_email", "operator@nasatlabs.example")

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["operator@nasatlabs.example"]


def test_the_command_never_echoes_the_password(capsys, settings):
    settings.EMAIL_HOST_PASSWORD = "hunter2-do-not-print-me"

    call_command("send_test_email", "operator@nasatlabs.example")

    assert "hunter2-do-not-print-me" not in capsys.readouterr().out


def test_the_command_says_when_it_is_proving_nothing(capsys, settings):
    """The console backend prints rather than sends; a green run would be a lie."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

    call_command("send_test_email", "operator@nasatlabs.example")

    assert "proves nothing about the transport" in capsys.readouterr().out


def test_a_transport_failure_becomes_an_actionable_error(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

    # Patched where it is *used*, not where it is defined: the command does
    # `from django.core.mail import send_mail`, so the name is bound in its own
    # module at import and patching the source module would not touch it.
    with mock.patch(
        "apps.common.management.commands.send_test_email.send_mail",
        side_effect=OSError("Connection refused"),
    ), pytest.raises(CommandError) as raised:
        call_command("send_test_email", "operator@nasatlabs.example")

    message = str(raised.value)
    assert "Connection refused" in message
    # The point of the command: an operator should not have to read smtplib.
    assert "sending domain is not verified" in message


# --- Microsoft Graph -------------------------------------------------------
#
# The startup checks matter more here than for SMTP, because Graph fails in
# ways that look like success: a wrong From is rewritten rather than refused,
# and a missing application access policy is a 403 that only appears once a
# customer is waiting for a message.

def test_a_fully_configured_graph_backend_starts():
    module = _reimport_settings(**_graph_env())

    assert module.EMAIL_BACKEND == module.GRAPH_EMAIL_BACKEND
    assert module.GRAPH_MAIL_SENDER == "lims-notifications@nasatlabs.example"


def test_the_graph_tenant_falls_back_to_the_sso_tenant():
    """
    It is genuinely the same tenant. Asking an operator to paste the same
    GUID into two variables invites them to differ.
    """
    module = _reimport_settings(**_graph_env(GRAPH_MAIL_TENANT_ID=""))

    assert module.GRAPH_MAIL_TENANT_ID == BASE_ENV["AZURE_AD_TENANT_ID"]


def test_the_graph_credential_is_separate_from_the_sso_credential():
    """
    A separate app registration is the point: rotating the mail secret must
    not be able to lock the laboratory out of signing in.
    """
    module = _reimport_settings(**_graph_env())

    assert module.GRAPH_MAIL_CLIENT_ID != module.AUTH_ADFS["CLIENT_ID"]


@pytest.mark.parametrize(
    "unset",
    ["GRAPH_MAIL_CLIENT_ID", "GRAPH_MAIL_CLIENT_SECRET", "GRAPH_MAIL_SENDER"],
)
def test_a_half_configured_graph_backend_refuses_to_start(unset):
    with pytest.raises(RuntimeError, match=unset):
        _reimport_settings(**_graph_env(**{unset: ""}))


def test_a_from_address_that_is_not_the_mailbox_refuses_to_start():
    """
    Graph sends as the mailbox in the request URL whatever the message says,
    so this would arrive from an address the application never chose -- and
    the customer's reply would go there.
    """
    with pytest.raises(RuntimeError, match="rewrites the From"):
        _reimport_settings(
            **_graph_env(DJANGO_DEFAULT_FROM_EMAIL="no-reply@nasatlabs.example")
        )


def test_a_display_name_on_the_from_address_is_allowed():
    """`NexusLIMS <mailbox>` is the same mailbox, and is what customers should see."""
    module = _reimport_settings(
        **_graph_env(
            DJANGO_DEFAULT_FROM_EMAIL="NexusLIMS <lims-notifications@nasatlabs.example>"
        )
    )

    assert module.DEFAULT_FROM_EMAIL.startswith("NexusLIMS <")


def test_the_development_from_address_refuses_to_start_over_graph():
    """The same rule the SMTP backend gets: a real transport, a real sender."""
    with pytest.raises(RuntimeError, match="development address"):
        _reimport_settings(
            **_graph_env(
                DJANGO_DEFAULT_FROM_EMAIL="no-reply@nasatlabs.test",
                GRAPH_MAIL_SENDER="no-reply@nasatlabs.test",
            )
        )


def test_the_smtp_transport_checks_do_not_fire_for_graph():
    """
    EMAIL_HOST is unset in a Graph deployment and that is correct, not
    half-configured. A shared guard would make the two transports impossible
    to run one at a time.
    """
    module = _reimport_settings(**_graph_env(EMAIL_HOST=""))

    assert module.EMAIL_HOST == ""
