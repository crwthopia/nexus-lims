"""
Catalogue operations that are more than a save.

Pricing is the whole of it: a price is never edited, it is superseded, and
doing that correctly means closing the outgoing price on the day before the
incoming one starts, inside one transaction. Leaving that to the serializer
would put it behind exactly one endpoint, and the CSV importer would then
have its own subtly different copy.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.catalogue.models import OfferingPrice


def today():
    """Local date, since a rate card takes effect on a Manila calendar day, not a UTC one."""
    return timezone.localdate()


@transaction.atomic
def set_price(offering, *, amount, vat_treatment, vat_rate_pct, effective_from, currency="PHP", note="", created_by=None):
    """
    Give `offering` a new price from `effective_from`, closing whatever it
    was before.

    Returns the new OfferingPrice.

    Two cases the caller does not have to think about:

    - **Replacing a price that starts on the same day.** Correcting a rate
      you entered this morning is not a new period in the price history, it
      is a fix to the one you just made; the unique constraint on
      (offering, effective_from) says the same thing. So a same-day write
      updates that row rather than raising.
    - **Back-dating.** Any price whose window contains `effective_from` is
      closed the day before, whether or not it is the current one, so
      windows cannot overlap even when prices arrive out of order.
    """
    same_day = offering.prices.filter(effective_from=effective_from).first()

    # Any earlier price still open, or whose window covers the new start
    # date, ends the day before it.
    covering = offering.prices.filter(effective_from__lt=effective_from).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=effective_from)
    )
    for price in covering:
        price.effective_to = effective_from - timedelta(days=1)
        price.save(update_fields=["effective_to"])

    if same_day is not None:
        same_day.amount = amount
        same_day.currency = currency
        same_day.vat_treatment = vat_treatment
        same_day.vat_rate_pct = vat_rate_pct
        same_day.note = note
        same_day.created_by = created_by or same_day.created_by
        same_day.save()
        return same_day

    # A price starting before an existing one inherits that one's start as
    # its own end, so back-dating a rate does not silently overwrite the
    # period that follows it.
    following = offering.prices.filter(effective_from__gt=effective_from).order_by("effective_from").first()
    return OfferingPrice.objects.create(
        offering=offering,
        amount=amount,
        currency=currency,
        vat_treatment=vat_treatment,
        vat_rate_pct=vat_rate_pct,
        effective_from=effective_from,
        effective_to=(following.effective_from - timedelta(days=1)) if following else None,
        note=note,
        created_by=created_by,
    )
