from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    label = "audit"

    def ready(self):
        # Connected here rather than at import time: the receivers resolve
        # their senders through the app registry, which is only populated
        # once every app is loaded.
        from apps.audit import signals

        signals.connect()
