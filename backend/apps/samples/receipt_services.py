"""
Receiving an item, and the one gate that receiving puts on the work.

ISO/IEC 17025:2017 7.4.3 says that where there is doubt about an item's
suitability, or it does not conform to the description supplied, the
laboratory shall consult the customer *before proceeding*. The wording
matters: it does not say refuse the item, and it does not say accept it
quietly. It says stop, ask, and write down the answer.

That maps onto two functions here, and deliberately not onto one:

  `record_receipt` accepts the item and writes what was observed. It never
  refuses -- a leaking bottle at 17:40 still has to be booked in, put in a
  fridge and accounted for, and a receiving screen that rejected the record
  would leave the lab holding an item with no record of holding it.

  `check_can_begin_work` is where the standard's "before proceeding" bites,
  called from the start_prep transition. A nonconforming item is received,
  stored and visible, and simply cannot reach an analyst until somebody has
  spoken to the customer and recorded what they said.

Putting the gate on start_prep rather than on receive is the difference
between a control and an obstruction. The lab's own records stay complete
either way; what waits is the testing.
"""

from django.db import transaction
from django.utils import timezone

from apps.samples.models import ChainOfCustodyEvent, SampleReceipt


class ReceiptDeviationUnresolved(Exception):
    """Raised when work is attempted on an item whose receipt deviation has no recorded consultation."""


@transaction.atomic
def record_receipt(sample, *, received_by, received_at=None, location="", **observations):
    """
    Write the arrival record for `sample` and open its chain of custody.

    Returns the SampleReceipt. Also mirrors the arrival time onto
    `Sample.received_at` -- see that field for why it is denormalized --
    but does *not* run the FSM transition: the caller owns that, so a
    refused transition and a written receipt can never disagree.

    The checklist defaults to conforming. That is the receiver's
    affirmation rather than an assumption the system makes on their behalf:
    every field here is settable, the row records who asserted it and when,
    and the deviation path is the one the CHECK constraints police. A
    receiving screen is expected to put the checklist in front of the clerk
    (see the Receiving bench screen in the README) -- the defaults exist so
    that booking in a routine delivery is one action, not eleven.
    """
    received_at = received_at or timezone.now()

    receipt = SampleReceipt.objects.create(
        sample=sample, received_by=received_by, received_at=received_at, **observations,
    )

    sample.received_at = received_at

    ChainOfCustodyEvent.objects.create(
        sample=sample,
        to_holder=received_by,
        to_location=location,
        occurred_at=received_at,
        event_type=ChainOfCustodyEvent.EventType.RECEIPT,
    )

    return receipt


def check_can_begin_work(sample):
    """
    Raise ReceiptDeviationUnresolved if 7.4.3 has not been discharged for
    this item; return silently otherwise.

    Three ways to pass, and the third is a deployment concession rather
    than a principle:

      1. The receipt was conforming -- nothing to consult about.
      2. It deviated and the consultation is recorded, whatever the
         customer decided. If they said proceed, the disclaimer flag is
         already set and the COA will carry it; if they said stop, the
         item should be going to reject_at_receipt instead, and this gate
         is not the thing that should be arguing about it.
      3. There is no receipt row at all. Samples already past intake when
         this shipped have none, and failing them would strand live work
         in the middle of the lab to satisfy a record that could never
         have existed. New arrivals always have one, because
         `record_receipt` and the receive transition are the same call.
    """
    receipt = getattr(sample, "receipt", None)
    if receipt is None or receipt.is_conforming or receipt.consultation_recorded:
        return

    raise ReceiptDeviationUnresolved(
        f"Sample {sample.unique_sample_code} was received with deviations "
        f"({'; '.join(receipt.deviation_reasons)}) and no customer consultation has been recorded. "
        "ISO/IEC 17025:2017 7.4.3 requires the customer be consulted before proceeding: record the "
        "outcome via POST /samples/{id}/receipt-consultation/, or refuse the item via "
        "POST /samples/{id}/reject-at-receipt/."
    )
