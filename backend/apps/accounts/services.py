"""
E-signature capture helper (Blueprint Section 3.1 ESignature, FR-C5-04,
FR-S1-01). Centralized here so every signing action (review, approve,
reject, dispose) records signer, meaning, and the signed entity the same
way, rather than each view constructing an ESignature row by hand.
"""

from apps.accounts.models import ESignature


def capture_esignature(*, signer, meaning, signed_entity_type, signed_entity_id, authentication_method="password_mfa"):
    """Create and return an ESignature row for a review/approve/reject/dispose action."""
    return ESignature.objects.create(
        signer=signer,
        signer_type=ESignature.SignerType.STAFF,
        meaning=meaning,
        signed_entity_type=signed_entity_type,
        signed_entity_id=signed_entity_id,
        authentication_method=authentication_method,
    )
