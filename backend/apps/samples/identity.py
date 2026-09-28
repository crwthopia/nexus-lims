"""
Sample identity: allocating the code that goes on the bottle.

ISO/IEC 17025:2017 7.4.2 asks for a system of unambiguous identification
that is *retained for the life of the item in the laboratory*, and that
guarantees items are never confused physically or in the records. Until
this module existed, `unique_sample_code` was a writable string: a caller
could invent one, and a PATCH could change it after the fact. A unique
index stops two rows sharing a code; nothing stopped one row changing the
code that is printed on a physical container sitting in a fridge.

So the code is allocated here, server-side, and only here. Immutability is
enforced one layer lower still, by a trigger on `sample` (migration 0007),
for the same reason the audit log's append-only guarantee is a trigger
rather than a convention: the ORM is not the only thing that can issue an
UPDATE.

Shape: `WE-202609-0001` -- service-line prefix, allocation month, then a
zero-padded counter that restarts each month. Human-readable at a bench,
short enough for a 50mm label, and sortable by eye. The month is part of
the key rather than a running total for the life of the lab, because a
four-digit counter that never resets eventually stops fitting on a label
and starts having to be widened -- which changes the format of codes
already printed on containers.
"""

from django.db import transaction

from apps.samples.models import SampleCodeSequence, ServiceLine

# Deliberately short and distinct at a glance. These are baked into
# physical labels the moment one is printed, so changing a prefix here
# orphans every container already in the building -- treat them as
# append-only.
SERVICE_LINE_PREFIXES = {
    ServiceLine.WATER_ENVIRONMENTAL: "WE",
    ServiceLine.FAILURE_ANALYSIS: "FA",
    ServiceLine.TRAINING: "TR",
}

COUNTER_WIDTH = 4


class UnknownServiceLine(Exception):
    """Raised when a service line has no code prefix, rather than inventing one."""


def period_for(on_date):
    return on_date.strftime("%Y%m")


@transaction.atomic
def allocate_sample_code(service_line, *, on_date=None):
    """
    Reserve and return the next code for `service_line`.

    Serialised with SELECT ... FOR UPDATE on the counter row rather than
    computed as `max(code) + 1`. Two clerks booking in the same delivery is
    the ordinary case at a receiving bench, and max+1 under concurrency
    hands both of them the same number -- which the unique index then turns
    into a 500 for whoever commits second, on a screen where the right
    answer was simply the next code. The lock is per service line per
    month, so it never spans more than the handful of rows being allocated
    at once.

    `on_date` exists for the tests and for backfills; ordinary callers let
    it default, since the allocation month is a property of when the lab
    took the item in.
    """
    from apps.catalogue.services import today

    try:
        prefix = SERVICE_LINE_PREFIXES[service_line]
    except KeyError as exc:
        raise UnknownServiceLine(
            f"No sample-code prefix is defined for service line {service_line!r}. "
            f"Add one to SERVICE_LINE_PREFIXES before booking work in against it."
        ) from exc

    period = period_for(on_date or today())

    counter, _ = SampleCodeSequence.objects.select_for_update().get_or_create(
        prefix=prefix, period=period,
    )
    counter.last_number += 1
    counter.save(update_fields=["last_number"])

    return f"{prefix}-{period}-{counter.last_number:0{COUNTER_WIDTH}d}"
