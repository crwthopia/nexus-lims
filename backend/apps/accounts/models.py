"""
Identity and Access entities (Blueprint Section 3.1, 3.1a).

Two segregated identity domains, per NASAT's explicit requirement
(Blueprint Section 2.1 item 7): StaffUser (Entra ID via django-auth-adfs)
and CustomerUser (self-service, Django-native auth backend). These do not
share a table and there is no FK between them; a staff Entra ID principal
has no path to a Customer role and vice versa.
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user


class Role(models.Model):
    """
    The 10 named staff roles from the blueprint's RBAC model
    (Blueprint Section 7.1). Also referenced descriptively by
    django-fsm-2 @transition guards on Sample/TestRequest/ApprovalAction.
    """

    class RoleName(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        SAMPLE_RECEIVER = "sample_receiver", "Sample Receiver"
        ANALYST = "analyst", "Analyst"
        REVIEWER = "reviewer", "Reviewer"
        APPROVER = "approver", "Approver"
        QA_OFFICER = "qa_officer", "QA Officer"
        LAB_SUPERVISOR = "lab_supervisor", "Lab Supervisor"
        INSTRUMENT_CUSTODIAN = "instrument_custodian", "Instrument Custodian"
        TRAINING_COORDINATOR = "training_coordinator", "Training Coordinator"
        SYSTEM_ADMINISTRATOR = "system_administrator", "System Administrator"

    name = models.CharField(max_length=32, choices=RoleName.choices, unique=True)
    permission_set = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "role"
        ordering = ["name"]

    def __str__(self):
        return self.get_name_display()


class StaffUserManager(BaseUserManager):
    def create_user(self, email, entra_oid, display_name, password=None, **extra_fields):
        if not email:
            raise ValueError("StaffUser requires an email address")
        if not entra_oid:
            raise ValueError("StaffUser requires an Entra ID object ID")
        email = self.normalize_email(email)
        user = self.model(email=email, entra_oid=entra_oid, display_name=display_name, **extra_fields)
        if password:
            # Only set for local-dev/admin accounts (e.g. createsuperuser); ordinary
            # staff are provisioned via Entra ID and get no usable local password.
            user.set_password(password)
        else:
            user.set_unusable_password()  # authentication is delegated to Entra ID / django-auth-adfs
        user.save(using=self._db)
        return user

    def create_superuser(self, email, entra_oid, display_name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, entra_oid, display_name, password=password, **extra_fields)


class StaffUser(AbstractBaseUser, PermissionsMixin):
    """
    Blueprint Section 3.1: linked 1:1 to an Entra ID object ID via
    django-auth-adfs. Carries prc_license_number / prc_license_validity_date
    (added per NASAT architectural review) to support dynamic signatory
    blocks on DOH/DENR COAs (Blueprint Section 2.1a).
    """

    id = models.BigAutoField(primary_key=True)
    entra_oid = models.CharField(max_length=64, unique=True, db_index=True)
    display_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    roles = models.ManyToManyField(Role, related_name="staff_users", blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=True)
    instrument_certifications = models.ManyToManyField(
        "testing.TestMethod",
        related_name="certified_staff",
        blank=True,
        help_text="Supports FR-C3-02 competency enforcement: role membership alone is not sufficient.",
    )
    prc_license_number = models.CharField(
        max_length=64, null=True, blank=True,
        help_text="Required only for staff who act as Reviewer/Approver on regulated (DOH/DENR) reports.",
    )
    prc_license_validity_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(get_user=get_history_user)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["entra_oid", "display_name"]

    objects = StaffUserManager()

    class Meta:
        db_table = "staff_user"
        ordering = ["display_name"]

    def __str__(self):
        return f"{self.display_name} <{self.email}>"


class CustomerUser(models.Model):
    """
    Blueprint Section 3.1: self-service customer identity, entirely separate
    from StaffUser. prc_license_number (added per NASAT architectural review)
    is populated for customers enrolled in CPD-accredited trainings, feeding
    the Attendee Export in Blueprint Section 3.6.
    """

    id = models.BigAutoField(primary_key=True)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255)
    is_email_verified = models.BooleanField(default=False)
    school_id_document = models.ForeignKey(
        "documents.Document", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="student_discount_customers",
        help_text="For student discount eligibility per NASAT catalog.",
    )
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(
        max_length=64, null=True, blank=True,
        help_text="Base32 TOTP secret (RFC 6238). Set by /auth/customer/mfa/enable, only "
                   "activated (mfa_enabled=True) once confirmed with a real code.",
    )
    pending_mfa_secret = models.CharField(
        max_length=64, null=True, blank=True,
        help_text=(
            "A new secret being enrolled, held here until it is confirmed. Re-enrolling "
            "used to overwrite mfa_secret directly while mfa_enabled stayed True, which "
            "locked the customer out of their own account the moment they opened the "
            "enrolment screen: their authenticator still held the old secret and the "
            "server no longer accepted it."
        ),
    )
    mfa_last_used_timestep = models.BigIntegerField(
        null=True, blank=True,
        help_text=(
            "The TOTP time step of the last accepted code, so it cannot be replayed. "
            "Without it a code observed over someone's shoulder, or captured anywhere "
            "in transit, stayed usable for the whole validity window."
        ),
    )
    organization_name = models.CharField(max_length=255, null=True, blank=True)
    prc_license_number = models.CharField(
        max_length=64, null=True, blank=True,
        help_text="Populated for customers enrolled in CPD-accredited trainings; feeds the Attendee Export (Section 3.6).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "customer_user"
        ordering = ["-created_at"]

    def __str__(self):
        return self.email

    @property
    def is_authenticated(self):
        """
        CustomerUser is deliberately NOT AUTH_USER_MODEL (Blueprint Section
        2.1 item 7: two segregated identity domains) and never appears as
        request.user via Django's own auth pipeline. It only ever reaches
        request.user through CustomerSessionAuthentication
        (apps/accounts/authentication.py) on customer-facing views, which
        DRF's permission classes then check via `request.user.is_authenticated`
        -- this property exists purely to satisfy that contract, mirroring
        how django.contrib.auth.models.AnonymousUser.is_authenticated works.
        """
        return True


class ESignature(models.Model):
    """
    Blueprint Section 3.1, per FR-C5-04 / FR-S1-01. Generic e-signature
    capture referenced by ReviewAction, ApprovalAction, and disposition
    actions (Investigation, Sample rejection routing).
    """

    class Meaning(models.TextChoices):
        REVIEWED = "reviewed", "Reviewed"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        DISPOSED = "disposed", "Disposed"

    class SignerType(models.TextChoices):
        STAFF = "staff", "Staff"
        CUSTOMER = "customer", "Customer"

    id = models.BigAutoField(primary_key=True)
    signer = models.ForeignKey(StaffUser, on_delete=models.PROTECT, related_name="signatures")
    signer_type = models.CharField(max_length=16, choices=SignerType.choices, default=SignerType.STAFF)
    meaning = models.CharField(max_length=16, choices=Meaning.choices)
    signed_entity_type = models.CharField(max_length=64, help_text="e.g. 'Sample', 'TestResult', 'Investigation'")
    signed_entity_id = models.BigIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
    authentication_method = models.CharField(
        max_length=32, default="password_mfa",
        help_text="e.g. password_mfa, entra_conditional_access",
    )

    class Meta:
        db_table = "e_signature"
        indexes = [models.Index(fields=["signed_entity_type", "signed_entity_id"])]
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.get_meaning_display()} by {self.signer} @ {self.timestamp:%Y-%m-%d %H:%M}"
