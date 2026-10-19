"""ORM -> frontend mapping for family members.

The model attribute is ``relation`` but the frontend field is ``relationship``.
"""

from __future__ import annotations

from typing import Any

from app.db.models.family import FamilyMember


def family_member_to_dict(member: FamilyMember) -> dict[str, Any]:
    return {
        "id": str(member.id),
        "name": member.name,
        "relationship": member.relation,
        "dob": member.dob.isoformat() if member.dob else None,
        "gender": member.gender,
        "phone": member.phone,
        "email": member.email,
    }
