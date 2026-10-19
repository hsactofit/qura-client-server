"""Policy queries, always scoped to the authenticated user."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.models.policies import Policy


async def list_policies(
    session: AsyncSession, user_id: str, *, status: str | None = None
) -> list[Policy]:
    stmt = select(Policy).where(Policy.user_id == user_id)
    if status:
        stmt = stmt.where(Policy.status == status)
    stmt = stmt.order_by(Policy.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_policy(session: AsyncSession, user_id: str, policy_id: str) -> Policy:
    """Fetch one policy owned by the user, or 404 (no existence disclosure)."""
    result = await session.execute(
        select(Policy).where(Policy.id == policy_id, Policy.user_id == user_id)
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise ApiError("Policy not found", status_code=404)
    return policy
