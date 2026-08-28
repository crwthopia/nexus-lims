"""
Prove the SMTP transport works, before trusting it with a customer's
verification link.

Everything else about notifications is covered by tests
(tests/test_notifications.py), but those run against Django's locmem backend
-- they prove the right message is built and addressed, not that a real relay
will accept it. What cannot be tested from here is the part that only exists
in a deployment: DNS, the verified sending domain, the credentials, and
whether the provider's endpoint is reachable from inside the VPC at all.

So this is the one-command version of that check. It sends directly rather
than through `notify()` on purpose: the notification path is already proven,
and routing a diagnostic through a queue means a failure surfaces in a worker
log instead of in the terminal of the person running it.
"""

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send one test email, to check SMTP configuration in a real deployment."

    def add_arguments(self, parser):
        parser.add_argument("recipient", help="Address to send the test message to.")
        parser.add_argument(
            "--subject",
            default="NexusLIMS SMTP test",
            help="Override the subject, e.g. to tell two attempts apart in a busy inbox.",
        )

    def handle(self, *args, **options):
        recipient = options["recipient"]

        # Printed before sending, because when the send hangs this is the
        # information you want and the traceback will not carry it. The
        # password is deliberately never echoed -- only whether one is set.
        self.stdout.write("Sending with:")
        self.stdout.write(f"  backend    {settings.EMAIL_BACKEND}")
        self.stdout.write(f"  host       {settings.EMAIL_HOST or '(unset)'}:{settings.EMAIL_PORT}")
        self.stdout.write(f"  from       {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"  user       {settings.EMAIL_HOST_USER or '(none)'}")
        self.stdout.write(f"  password   {'set' if settings.EMAIL_HOST_PASSWORD else '(none)'}")
        self.stdout.write(f"  TLS / SSL  {settings.EMAIL_USE_TLS} / {settings.EMAIL_USE_SSL}")
        self.stdout.write(f"  timeout    {settings.EMAIL_TIMEOUT}s")
        self.stdout.write(f"  to         {recipient}")
        self.stdout.write("")

        if settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
            self.stdout.write(
                self.style.WARNING(
                    "The console backend is active, so this proves nothing about SMTP -- "
                    "the message below is printed, not sent. Set DJANGO_EMAIL_BACKEND to "
                    "django.core.mail.backends.smtp.EmailBackend to test a real relay."
                )
            )

        # fail_silently=False is the entire point of this command: the default
        # send path swallows nothing either, but here the traceback is the
        # deliverable.
        try:
            connection = get_connection(fail_silently=False)
            sent = send_mail(
                subject=options["subject"],
                message=(
                    "This is a NexusLIMS SMTP configuration test.\n\n"
                    "If you are reading it in a real inbox, the sending domain is "
                    "verified, the credentials work, and the relay is reachable from "
                    "wherever this command ran.\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                connection=connection,
                fail_silently=False,
            )
        except Exception as exc:
            # Named rather than re-raised bare: the common failures are
            # diagnosable from the exception type alone, and an operator
            # running this at 2am should not have to read smtplib.
            raise CommandError(
                f"{type(exc).__name__}: {exc}\n\n"
                "Common causes, in the order they usually happen:\n"
                "  - the sending domain is not verified with the provider yet\n"
                "  - EMAIL_HOST_USER is not the address DEFAULT_FROM_EMAIL sends as\n"
                "  - the port is blocked outbound from this subnet\n"
                "  - STARTTLS vs implicit TLS: 587 wants EMAIL_USE_TLS, 465 wants EMAIL_USE_SSL"
            ) from exc

        if not sent:
            raise CommandError(
                "The backend reported zero messages sent and raised nothing, which "
                "usually means a backend that accepts and discards. Check "
                "DJANGO_EMAIL_BACKEND."
            )

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} message to {recipient}."))
        self.stdout.write(
            "A send that succeeds here still only proves the relay accepted it. "
            "Confirm it arrived, and check the spam folder before declaring victory."
        )
