"""Shared mapping from the User/UserProfile models to the frontend user shape.

The database splits account fields (``users``) from PII/soft profile fields
(``user_profiles``). The frontend, however, reads ``date_of_birth``,
``pan_number`` and ``aadhaar_number`` at the top level and the softer fields
(``annualIncome``, ``occupation``, ``lifestyle``) plus ``kyc_documents`` under a
``preferences`` object. This module composes that response shape without
changing the model split.

Sensitive fields (PAN, Aadhaar, DOB) are included only because the existing
frontend profile page requires them; nothing else about the user is exposed, and
password hashes / reset tokens / internal flags are never included.
"""

from __future__ import annotations

from typing import Any

from app.db.models.identity import User, UserProfile


def _iso(value: Any) -> Any:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def build_preferences(
    profile: UserProfile | None,
    kyc_documents: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the ``preferences`` object the Profile page reads.

    ``kyc_documents`` is the ``{<doc_type>: {name, status}}`` summary the KYC
    center renders; it is always present (possibly empty) so the frontend's
    ``preferences.kyc_documents`` access is safe.
    """
    prefs: dict[str, Any] = {}
    if profile is not None:
        if profile.annual_income is not None:
            # Frontend treats this as a number|string; expose as string for Numeric.
            prefs["annualIncome"] = str(profile.annual_income)
        if profile.occupation is not None:
            prefs["occupation"] = profile.occupation
        if profile.lifestyle is not None:
            prefs["lifestyle"] = profile.lifestyle
    prefs["kyc_documents"] = kyc_documents or {}
    return prefs


def user_to_dict(
    user: User,
    profile: UserProfile | None,
    kyc_documents: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the frontend user object (plain dict for the response envelope)."""
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "photo_url": user.photo_url,
        "address": user.address,
        "role": user.role,
        "date_of_birth": _iso(profile.date_of_birth) if profile else None,
        "pan_number": profile.pan_number if profile else None,
        "aadhaar_number": profile.aadhaar_number if profile else None,
        "preferences": build_preferences(profile, kyc_documents),
    }
