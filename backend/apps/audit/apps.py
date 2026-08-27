from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    label = "audit"

    def ready(self):
        # Connected here rather than at import time: the receivers resolve
        # their senders through the app registry, which is only populated
        # once every app is loaded.
        from django.core.signals import got_request_exception

        from apps.audit import signals
        from apps.audit.failures import record_request_exception

        signals.connect()

        # An unhandled exception during a request is a system failure
        # (ISO/IEC 17025:2017 7.11.3(e)). Connected here rather than in
        # middleware so it cannot be ordered wrong relative to the
        # exception handling it observes, and so it still fires for an
        # exception raised outside the view.
        got_request_exception.connect(record_request_exception, dispatch_uid="audit.record_request_exception")
