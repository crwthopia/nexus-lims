"""
Data migration seeding the 10 named staff roles (Blueprint Section 3.1, 7.1).
"""

from django.db import migrations

# NOTE: Historical model state reconstructed by Django's migration framework
# does not preserve custom inner classes (TextChoices) defined on the real
# model, so role names are hardcoded here rather than referenced via
# Role.RoleName.choices. Must stay in sync with accounts.models.Role.RoleName.
ROLE_NAMES = [
    "customer",
    "sample_receiver",
    "analyst",
    "reviewer",
    "approver",
    "qa_officer",
    "lab_supervisor",
    "instrument_custodian",
    "training_coordinator",
    "system_administrator",
]


def seed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for name in ROLE_NAMES:
        Role.objects.get_or_create(name=name, defaults={"permission_set": {}})


def unseed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(seed_roles, unseed_roles),
    ]
