"""
The dashboard endpoint.

One read, one response: every figure the screen shows is aggregated here so
the browser is never handed a worklist to reduce for itself. Read-only, and
open to any authenticated staff member -- it reports on work the whole lab
does, and the rate card it prices that work at is already visible to them
(apps/catalogue/views.py).
"""

import datetime

from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics import services


def _date_param(value, name):
    """An ISO date from the query string, or None. A malformed one is a 400."""
    if value in (None, ""):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: "Expected an ISO date (YYYY-MM-DD)."}) from exc


class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            services.dashboard(
                date_from=_date_param(request.query_params.get("from"), "from"),
                date_to=_date_param(request.query_params.get("to"), "to"),
                # Local date, not UTC: a lab's day is a Manila calendar day,
                # and "today" either side of midnight UTC is 8am here.
                # Anything but "value" ranks by volume, rather than 400ing on
                # a typo: the dashboard is a read, and a misspelled sort
                # param should show the default view, not an error page.
                rank="value" if request.query_params.get("rank") == "value" else "volume",
                today=timezone.localdate(),
            )
        )
