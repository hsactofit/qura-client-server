"""Relationship Manager (RM) retrieval for the authenticated client.

Client-facing read only. A client's RM is the manager/admin user currently
assigned to them. Qura's schema has no dedicated client->RM assignment table;
the authoritative link that exists today is ``support_tickets.assigned_rm_id``
(the RM a staff process assigned to a client's ticket). We therefore resolve the
client's RM as the assignee of their most recent ticket that has one.

Honesty constraints:
- We NEVER invent an assignment or pick a random employee. If the client has no
  ticket with an assigned RM, there is no RM to show and we return ``None`` —
  the frontend renders the "no RM yet" state.
- Assignment administration (who assigns an RM to a client) is a staff-side
  concern and is intentionally NOT exposed in this client API.
- Only the RM's safe contact fields are returned; no password hash, status,
  internal flags, or other users' data leak.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.identity import User
from app.db.models.support import SupportTicket

_RM_ROLES = ("MANAGER", "ADMIN")


@dataclass(frozen=True)
class RmContact:
    id: str
    full_name: str | None
    email: str | None
    phone: str | None
    designation: str | None


async def get_assigned_rm(
    session: AsyncSession, user_id: str
) -> RmContact | None:
    """Return the client's assigned RM contact, or ``None`` if unassigned."""
    # Most recent ticket (owned by the client) that carries an assigned RM.
    result = await session.execute(
        select(SupportTicket)
        .where(SupportTicket.user_id == user_id)
        .order_by(SupportTicket.created_at.desc())
    )
    rm_id: Any = None
    for ticket in result.scalars().all():
        if ticket.assigned_rm_id is not None:
            rm_id = ticket.assigned_rm_id
            break
    if rm_id is None:
        return None

    rm_result = await session.execute(select(User).where(User.id == rm_id))
    rm = rm_result.scalar_one_or_none()
    # Only surface an active staff account; never a deleted/invalid user.
    if rm is None or rm.is_deleted or rm.role not in _RM_ROLES:
        return None

    designation = "Relationship Manager" if rm.role == "MANAGER" else "Account Manager"
    return RmContact(
        id=str(rm.id),
        full_name=rm.full_name,
        email=rm.email,
        phone=rm.phone,
        designation=designation,
    )


def rm_to_dict(rm: RmContact | None) -> dict[str, Any] | None:
    """Map to the frontend RM shape, or ``None`` when unassigned.

    ``available`` reflects whether any usable contact channel exists so the UI
    can honestly say "contact details coming soon" when they do not.
    """
    if rm is None:
        return None
    has_contact = bool(rm.phone or rm.email)
    name = rm.full_name or "Relationship Manager"
    return {
        "id": rm.id,
        "name": name,
        "full_name": rm.full_name,
        "designation": rm.designation,
        "email": rm.email,
        "phone": rm.phone,
        # Both spellings for the frontend's photo_url ?? photo fallback.
        "photo": None,
        "photo_url": None,
        "available": has_contact,
    }
