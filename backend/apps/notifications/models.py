"""
The record of what the lab told people, and the idempotency key that stops
it telling them twice.

Before this, two places called `send_mail` inline and nothing anywhere said
whether the message had gone out. That is survivable for one verification
email. It is not survivable for a nightly sweep: "email every instrument
whose calibration is due" with no memory of what it already sent emails the
same custodian about the same instrument every night until somebody
calibrates it, and the useful signal is gone inside a week.

So every notification is a row first and an email second, and the row
carries a `dedupe_key` under a unique constraint. A sweep that tries to
send the same thing twice loses the race at the database rather than in
application logic -- which matters because beat and a manually-triggered
task can run concurrently, and `SELECT then INSERT` would let both through.

**The body is deliberately not stored.** Only the subject is. A report-ready
notice is addressed to a customer, and ISO/IEC 17025:2017 4.2 makes the lab
responsible for their information; copying the message body into a
staff-readable table spreads it for no benefit. The row answers "who was
told what, and when" -- which is what anybody auditing this needs -- and the
body is re-derived from the entity at send time (apps/notifications/
messages.py), so it also cannot drift into a stale copy of a record that has
since been corrected.
"""

from django.db import models


class NotificationRecord(models.Model):
    class Kind(models.TextChoices):
        # Staff-facing
        SYSTEM_FAILURE = "system_failure", "System failure recorded"
        OPEN_FAILURE_DIGEST = "open_failure_digest", "Daily open system-failure digest"
        CALIBRATION_DUE = "calibration_due", "Instrument calibration due"
        INVESTIGATION_OPENED = "investigation_opened", "Investigation opened"
        RESULT_OUT_OF_SPEC = "result_out_of_spec", "Test result flagged out of specification"
        # Customer-facing
        SAMPLE_PROGRESS = "sample_progress", "Sample reached a milestone"
        SAMPLE_PROGRESS_DIGEST = "sample_progress_digest", "Daily sample-progress digest"
        REPORT_READY = "report_ready", "Report ready to download"
        TRAINING_SESSION_RESCHEDULED = "training_session_rescheduled", "Training session rescheduled"
        CUSTOMER_EMAIL_VERIFICATION = "customer_email_verification", "Customer email verification"
        CUSTOMER_DUPLICATE_REGISTRATION = "customer_duplicate_registration", "Duplicate registration attempt"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    id = models.BigAutoField(primary_key=True)
    kind = models.CharField(max_length=40, choices=Kind.choices)
    # A plain address rather than a FK: recipients are StaffUser *or*
    # CustomerUser, two deliberately disjoint identity domains (Blueprint
    # Section 2.1 item 7), and a nullable FK to each would be a worse lie
    # than a string. It also records the address actually used at the time,
    # which is the one that matters if somebody asks where a message went.
    recipient = models.EmailField()
    subject = models.CharField(max_length=255)

    # What the notification is about, so the send task can re-derive the body
    # and so "has this instrument already been chased?" is answerable.
    entity_type = models.CharField(max_length=64, blank=True)
    entity_id = models.BigIntegerField(null=True, blank=True)

    # Identifiers, enum values and counts only -- never a measured value,
    # never document content. The body is deliberately not stored (see the
    # module docstring) and this must not become a way around that.
    #
    # It exists because some notifications describe a *transition*, and the
    # entity has moved on by the time a worker picks the row up: a sample
    # that goes received -> in_prep in the same minute would otherwise send
    # "your sample is in prep" under the subject "sample received". Storing
    # the milestone at queue time is what keeps the message true.
    context = models.JSONField(default=dict, blank=True)

    # Unique, and that is the whole mechanism. See the module docstring:
    # a sweep re-running must lose at the database, not in a prior SELECT.
    dedupe_key = models.CharField(max_length=255, unique=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    failure_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification_record"
        indexes = [
            models.Index(fields=["kind", "-created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} -> {self.recipient} ({self.get_status_display()})"
