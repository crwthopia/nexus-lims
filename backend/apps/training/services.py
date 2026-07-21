"""Shared business logic for training/enrollment endpoints (apps/training/views.py)."""

from apps.training.models import CreditNote


class CreditNoteApplyError(Exception):
    pass


def compute_discount(customer, course):
    """
    Blueprint Section 3.6 (RESOLVED, non-stackable): the single highest
    valid discount a customer qualifies for. Only the student discount is
    computable here -- eligibility is CustomerUser.school_id_document being
    set. Early-bird eligibility would require a cutoff-date field that
    doesn't exist on TrainingCourse/TrainingSession under the current
    schema, so it isn't auto-applied here; staff can still grant it
    manually via Enrollment.discount_override.
    """
    if customer.school_id_document_id:
        return course.student_discount_pct
    return 0


def apply_credit_note(credit_note, target_enrollment):
    if credit_note.status != CreditNote.Status.AVAILABLE:
        raise CreditNoteApplyError(f"Credit note is '{credit_note.status}', not available to apply.")
    if target_enrollment.customer_id != credit_note.customer_id:
        raise CreditNoteApplyError("This credit note belongs to a different customer.")

    credit_note.status = CreditNote.Status.APPLIED
    credit_note.applied_to_enrollment = target_enrollment
    credit_note.save(update_fields=["status", "applied_to_enrollment"])
    return credit_note
