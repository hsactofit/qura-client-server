"""Family-member routes.

  GET    /family           list the user's family members
  POST   /family           create
  PUT    /family/{id}      update (ownership-enforced)
  DELETE /family/{id}      delete (ownership-enforced)

Writes require CSRF and are scoped to the authenticated user.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import success
from app.core.security import CurrentUser, enforce_csrf, require_authenticated
from app.db.session import get_session
from app.modules.family import service
from app.modules.family.mappers import family_member_to_dict
from app.modules.family.schemas import (
    FamilyMemberCreateRequest,
    FamilyMemberUpdateRequest,
)

router = APIRouter(prefix="/family", tags=["family"])


@router.get("")
async def list_family(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    members = await service.list_family(session, user.id)
    return success([family_member_to_dict(m) for m in members])


@router.post("")
async def create_member(
    body: FamilyMemberCreateRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    member = await service.create_member(session, user.id, body)
    return success(family_member_to_dict(member), "Family member added")


@router.put("/{member_id}")
async def update_member(
    member_id: str,
    body: FamilyMemberUpdateRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    member = await service.update_member(session, user.id, member_id, body)
    return success(family_member_to_dict(member), "Family member updated")


@router.delete("/{member_id}")
async def delete_member(
    member_id: str,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await service.delete_member(session, user.id, member_id)
    return success(None, "Family member removed")
