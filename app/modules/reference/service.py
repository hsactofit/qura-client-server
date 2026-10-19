"""Reference / master-data queries (public read).

``master_data`` rows are keyed by ``category``. The frontend requests categories
like RELATIONSHIP and GENDER and reads ``{label, value}``; FAQs are stored under
category 'FAQ' where ``label`` is the question and ``value`` the answer.

No reference values are fabricated: if the table is empty for a category, an
empty list is returned. Seeding reference data is a later, explicitly-approved
step (documented in the README); this phase does not write to the database.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.reference import MasterData

_FAQ_CATEGORY = "FAQ"


async def list_master_data(
    session: AsyncSession, category: str | None
) -> list[MasterData]:
    stmt = select(MasterData).where(MasterData.is_active.is_(True))
    if category:
        stmt = stmt.where(MasterData.category == category)
    stmt = stmt.order_by(MasterData.category, MasterData.sort_order)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_faqs(session: AsyncSession) -> list[MasterData]:
    result = await session.execute(
        select(MasterData)
        .where(MasterData.category == _FAQ_CATEGORY, MasterData.is_active.is_(True))
        .order_by(MasterData.sort_order)
    )
    return list(result.scalars().all())
