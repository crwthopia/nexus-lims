"""
The nightly expiry sweep.

A quotation's validity is a date on the row, so `is_expired` is always
correct and acceptance checks it directly -- a quote that lapsed at
midnight is lapsed at 00:01, not at 03:30 when this runs. What the sweep
adds is the *state*: without it, a lapsed offer sits in `sent` forever, so
"what is outstanding" over-counts and nobody's list of open quotations is
true. The task exists to make the status catch up with the date, and
nothing depends on it having run.
"""

import logging

from celery import shared_task
from django.db import transaction

from apps.quotations.models import Quotation
from apps.quotations.services import today

logger = logging.getLogger(__name__)


@shared_task
def expire_quotations():
    """Move every sent quotation whose validity has passed into `expired`."""
    lapsed = Quotation.objects.filter(status=Quotation.Status.SENT, valid_until__lt=today())

    expired = 0
    for quotation in lapsed:
        # One transaction each: a quotation that somehow refuses the
        # transition should not take the rest of the night's sweep with it.
        with transaction.atomic():
            quotation.expire()
            quotation.save()
        expired += 1

    if expired:
        logger.info("expired %s quotation(s) past their validity date", expired)
    return expired
