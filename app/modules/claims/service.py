"""Claim queries, scoped to the authenticated user.

Read-only in Phase 4. Claim submission and document upload depend on a secure
file-storage capability that is not yet implemented (StoredFile exists, but the
upload pipeline does not), so they are intentionally deferred and documented.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ApiError
from app.db.models.claims import Claim


async def list_claims(session: AsyncSession, user_id: str) -> list[Claim]:
    result = await session.execute(
        select(Claim)
        .where(Claim.user_id == user_id)
        .order_by(Claim.created_at.desc())
    )
    return list(result.scalars().all())


async def get_claim(session: AsyncSession, user_id: str, claim_id: str) -> Claim:
    result = await session.execute(
        select(Claim)
        .where(Claim.id == claim_id, Claim.user_id == user_id)
        .options(selectinload(Claim.documents))
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        raise ApiError("Claim not found", status_code=404)
    return claim
