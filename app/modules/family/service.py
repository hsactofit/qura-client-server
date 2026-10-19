"""Family-member CRUD, scoped to the authenticated user."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.models.family import FamilyMember
from app.modules.family.schemas import (
    FamilyMemberCreateRequest,
    FamilyMemberUpdateRequest,
)


def _parse_dob(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ApiError("Invalid dob (expected YYYY-MM-DD)", status_code=400) from exc


async def list_family(session: AsyncSession, user_id: str) -> list[FamilyMember]:
    result = await session.execute(
        select(FamilyMember)
        .where(FamilyMember.user_id == user_id)
        .order_by(FamilyMember.created_at.desc())
    )
    return list(result.scalars().all())


async def get_member(
    session: AsyncSession, user_id: str, member_id: str
) -> FamilyMember:
    result = await session.execute(
        select(FamilyMember).where(
            FamilyMember.id == member_id, FamilyMember.user_id == user_id
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise ApiError("Family member not found", status_code=404)
    return member


async def create_member(
    session: AsyncSession, user_id: str, body: FamilyMemberCreateRequest
) -> FamilyMember:
    member = FamilyMember(
        user_id=user_id,
        name=body.name,
        relation=body.relationship,
        dob=_parse_dob(body.dob),
        gender=body.gender,
        phone=body.phone,
        email=body.email,
    )
    session.add(member)
    await session.flush()
    return member


async def update_member(
    session: AsyncSession, user_id: str, member_id: str, body: FamilyMemberUpdateRequest
) -> FamilyMember:
    member = await get_member(session, user_id, member_id)
    provided = body.model_dump(exclude_unset=True, by_alias=False)
    if "name" in provided and body.name is not None:
        member.name = body.name
    if "relationship" in provided:
        member.relation = body.relationship
    if "dob" in provided:
        member.dob = _parse_dob(body.dob)
    if "gender" in provided:
        member.gender = body.gender
    if "phone" in provided:
        member.phone = body.phone
    if "email" in provided:
        member.email = body.email
    await session.flush()
    return member


async def delete_member(session: AsyncSession, user_id: str, member_id: str) -> None:
    member = await get_member(session, user_id, member_id)
    await session.delete(member)
    await session.flush()
