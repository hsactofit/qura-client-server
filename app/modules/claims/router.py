"""Claim routes (read-only in Phase 4).

  GET /claims          list the user's claims
  GET /claims/{id}     one claim with its documents, ownership-enforced

Claim creation and document upload are deferred (see service docstring).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import success
from app.core.security import CurrentUser, require_authenticated
from app.db.session import get_session
from app.modules.claims import service
from app.modules.claims.mappers import claim_to_dict

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("")
async def list_claims(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    claims = await service.list_claims(session, user.id)
    return success([claim_to_dict(c) for c in claims])


@router.get("/{claim_id}")
async def get_claim(
    claim_id: str,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    claim = await service.get_claim(session, user.id, claim_id)
    return success(claim_to_dict(claim, include_documents=True))
