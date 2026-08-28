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


def _smtp_env(**overrides):
    env = {
        "DJANGO_EMAIL_BACKEND": SMTP_BACKEND,
        "DJANGO_DEFAULT_FROM_EMAIL": "no-reply@nasatlabs.example",
        "EMAIL_HOST": "smtp.example",
        "EMAIL_HOST_USER": "no-reply@nasatlabs.example",
        "EMAIL_HOST_PASSWORD": "secret",
        "EMAIL_USE_TLS": "true",
        "EMAIL_USE_SSL": "false",
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
    assert module.EMAIL_PORT == 587


# --- The startup checks ----------------------------------------------------

def test_smtp_without_a_host_refuses_to_start():
    with pytest.raises(RuntimeError, match="EMAIL_HOST is unset"):
        _reimport_settings(**_smtp_env(EMAIL_HOST=""))


def test_tls_and_ssl_together_refuse_to_start():
    """Django raises on this too -- but only when the first message is sent."""
    with pytest.raises(RuntimeError, match="mutually"):
        _reimport_settings(**_smtp_env(EMAIL_USE_TLS="true", EMAIL_USE_SSL="true"))


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

    assert "proves nothing about SMTP" in capsys.readouterr().out


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
