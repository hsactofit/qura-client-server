"""Reference-data routes (authenticated reads).

  GET /master-data?category=   -> [{label, value}]
  GET /faqs                    -> [{question, answer, category}]

These require an authenticated session (the frontend calls them only from
signed-in pages). They never seed or fabricate values.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import success
from app.core.security import CurrentUser, require_authenticated
from app.db.session import get_session
from app.modules.reference import service

router = APIRouter(tags=["reference"])


@router.get("/master-data")
async def master_data(
    category: str | None = None,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = await service.list_master_data(session, category)
    return success([{"label": r.label, "value": r.value} for r in rows])


@router.get("/faqs")
async def faqs(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = await service.list_faqs(session)
    return success(
        [
            {"id": str(r.id), "question": r.label, "answer": r.value, "category": "FAQ"}
            for r in rows
        ]
    )
