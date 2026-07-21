"""
Standards, Reagents, Equipment entities (Blueprint Section 3.3, C-2/E-3/E-7).
"""

from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.history import get_history_user


class StandardReagent(models.Model):
    """Blueprint Section 3.3: per 6.5 Metrological Traceability."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    lot_number = models.CharField(max_length=100)
    crm_traceability_reference = models.CharField(
        max_length=255, help_text="Certified Reference Material traceability reference, ISO/IEC 17025:2017 6.5.",
    )
    opened_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    storage_location = models.CharField(max_length=255, blank=True)

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "standard_reagent"
        indexes = [models.Index(fields=["status", "expiry_date"])]
        ordering = ["name", "lot_number"]

    def __str__(self):
        return f"{self.name} (lot {self.lot_number})"


class Instrument(models.Model):
    """
    Blueprint Section 3.3: instrument register with parent/child grouping
    (e.g. FESEM with attached EDX shown as one card with an expandable
    child list, Section 5.1).
    """

    class InstrumentModel(models.TextChoices):
        FESEM = "fesem", "FESEM"
        SEM = "sem", "SEM"
        EDX = "edx", "EDX"
        AFM = "afm", "AFM"
        IR_OBIRCH = "ir_obirch", "IR-OBIRCH"
        TGA = "tga", "TGA"
        XRF = "xrf", "XRF"
        EBSD = "ebsd", "EBSD"
        THERMAL_EMISSION_MICROSCOPE = "thermal_emission_microscope", "Thermal Emission Microscope"
        DSC = "dsc", "DSC"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        IN_SERVICE = "in_service", "In Service"
        OUT_OF_CALIBRATION = "out_of_calibration", "Out of Calibration"
        RETIRED = "retired", "Retired"

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    model = models.CharField(max_length=32, choices=InstrumentModel.choices)
    parent_instrument = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="child_instruments",
        help_text="For child detector components, e.g. EDX attached to FESEM.",
    )
    calibration_due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.IN_SERVICE)
    custodian = models.ForeignKey(
        "accounts.StaffUser", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="custodied_instruments",
        help_text="Must hold the Instrument Custodian role (Blueprint Section 3.1 Role).",
    )

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "instrument"
        indexes = [models.Index(fields=["status", "calibration_due_date"])]
        ordering = ["name"]

    def __str__(self):
        return self.name


class CalibrationRecord(models.Model):
    """Blueprint Section 3.3."""

    id = models.BigAutoField(primary_key=True)
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="calibration_records")
    performed_by = models.ForeignKey("accounts.StaffUser", on_delete=models.PROTECT, related_name="performed_calibrations")
    performed_at = models.DateTimeField()
    result = models.CharField(max_length=32, help_text="e.g. pass, fail, conditional")
    next_due_date = models.DateField()

    history = HistoricalRecords(get_user=get_history_user)

    class Meta:
        db_table = "calibration_record"
        ordering = ["-performed_at"]

    def __str__(self):
        return f"{self.instrument.name} calibration @ {self.performed_at:%Y-%m-%d}"
