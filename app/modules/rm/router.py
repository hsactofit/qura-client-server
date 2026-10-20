"""Relationship Manager route (client-facing read).

  GET /rm/assignment  -> the authenticated client's assigned RM, or null

Identity comes only from the session. A client can only ever see their own RM;
there is no id input to tamper with. Returns ``data: null`` (not an error) when
the client has no RM assigned yet, which the frontend renders as the empty
state.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import success
from app.core.security import CurrentUser, require_authenticated
from app.db.session import get_session
from app.modules.rm import service

router = APIRouter(prefix="/rm", tags=["relationship-manager"])


@router.get("/assignment")
async def get_assignment(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rm = await service.get_assigned_rm(session, user.id)
    return success(service.rm_to_dict(rm))
