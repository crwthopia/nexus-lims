"""
The system failure register (ISO/IEC 17025:2017 7.11.3(e)).

Read for any authenticated staff member -- an analyst waiting on a report
that never appeared should be able to see that report generation is failing
without asking anyone. Write is QA Officer / Lab Supervisor, matching the
Investigation endpoints this one links to: recording a corrective action is
the same class of act as recording a CAPA, and belongs to the same people.

There is no create and no destroy. Rows are written by the system at the
moment of failure (apps/audit/failures.py), and migration 0005 revokes
DELETE at the database level -- a register somebody can tidy up is not a
register.
"""

from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.accounts.permissions import roles_required
from apps.audit.models import SystemFailure
from apps.audit.serializers import SystemFailureSerializer

RoleName = Role.RoleName
FAILURE_WRITE_ROLES = (RoleName.QA_OFFICER, RoleName.LAB_SUPERVISOR)


class SystemFailureViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = SystemFailure.objects.select_related("acknowledged_by", "closed_by", "investigation")
    serializer_class = SystemFailureSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        ?status= and ?component= (both comma-separated). Same gap the other
        viewsets closed: DRF ignores query params it does not recognise, so
        without this the operator's "show me what is still open" filters
        silently returned everything.
        """
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__in=status_param.split(","))
        component = self.request.query_params.get("component")
        if component:
            qs = qs.filter(component__in=component.split(","))
        return qs

    def get_permissions(self):
        if self.action in ("update", "partial_update", "acknowledge", "close"):
            return [IsAuthenticated(), roles_required(*FAILURE_WRITE_ROLES)()]
        return [IsAuthenticated()]

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        """
        POST /system-failures/{id}/acknowledge/ -- somebody has seen it.

        Deliberately its own step rather than a side effect of writing a
        corrective action: "we know about this" and "we have done something
        about it" are different claims, and an assessor reading the register
        is entitled to see which one is being made.

        Acknowledging also stops new occurrences coalescing into this row
        (apps/audit/failures.py) -- from here on a recurrence opens a fresh
        one, so a failure that comes back after somebody looked at it is
        visible rather than absorbed into a counter.
        """
        failure = self.get_object()
        if failure.status != SystemFailure.Status.OPEN:
            raise ValidationError(f"This failure is already {failure.get_status_display().lower()}.")
        failure.status = SystemFailure.Status.ACKNOWLEDGED
        failure.acknowledged_by = request.user
        failure.acknowledged_at = timezone.now()
        failure.save(update_fields=["status", "acknowledged_by", "acknowledged_at"])
        return Response(SystemFailureSerializer(failure).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """
        POST /system-failures/{id}/close/ -- the only path to Status.CLOSED.

        Refuses while `corrective_action` is empty, and that refusal is the
        whole reason this endpoint exists rather than a status field anyone
        can PATCH. 7.11.3(e) asks for the failure *and* the action taken;
        a register where failures can be closed with nothing written against
        them decays into a list of things that stopped being annoying.

        A corrective action of "none needed, transient dependency blip" is a
        perfectly good answer -- it is a decision somebody put their name to,
        which is what was missing.
        """
        failure = self.get_object()
        if failure.status == SystemFailure.Status.CLOSED:
            raise ValidationError("This failure is already closed.")

        corrective_action = (request.data.get("corrective_action") or failure.corrective_action or "").strip()
        if not corrective_action:
            raise ValidationError({
                "corrective_action": (
                    "Required to close a system failure (ISO/IEC 17025:2017 7.11.3(e)). "
                    "If no action was needed, say so and why."
                )
            })

        failure.corrective_action = corrective_action
        failure.status = SystemFailure.Status.CLOSED
        failure.closed_by = request.user
        failure.closed_at = timezone.now()
        failure.save(update_fields=["corrective_action", "status", "closed_by", "closed_at"])
        return Response(SystemFailureSerializer(failure).data)
