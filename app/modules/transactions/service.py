"""Transaction read queries (paginated list + stats), scoped to the user.

Read-only: Phase 4 adds no creation, status change, refund, or gateway. Stats
mirror the frontend/demo contract: totalPaid = sum of successful purchase+renewal
amounts; totalReceived = sum of successful payout+refund; netAmount = received -
paid. Filtering by type/status and a free-text search on description/reference
are supported; sort is fixed to newest-first for determinism.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page
from app.db.models.transactions import Transaction

_PAID_TYPES = ("purchase", "renewal")
_RECEIVED_TYPES = ("payout", "refund")


@dataclass(frozen=True)
class TransactionStats:
    total_paid: float
    total_received: float
    net_amount: float


def _base_filters(user_id: str, type_: str | None, status: str | None, search: str | None):  # type: ignore[no-untyped-def]
    conditions = [Transaction.user_id == user_id]
    if type_:
        conditions.append(Transaction.transaction_type == type_)
    if status:
        conditions.append(Transaction.status == status)
    if search:
        like = f"%{search}%"
        conditions.append(
            or_(
                Transaction.description.ilike(like),
                Transaction.reference_id.ilike(like),
            )
        )
    return conditions


async def list_transactions(
    session: AsyncSession,
    user_id: str,
    page: Page,
    *,
    type_: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> tuple[list[Transaction], int]:
    conditions = _base_filters(user_id, type_, status, search)

    total_result = await session.execute(
        select(func.count()).select_from(Transaction).where(*conditions)
    )
    total = int(total_result.scalar_one() or 0)

    result = await session.execute(
        select(Transaction)
        .where(*conditions)
        .order_by(Transaction.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(result.scalars().all()), total


async def compute_stats(session: AsyncSession, user_id: str) -> TransactionStats:
    """Aggregate successful amounts for the user (not page-limited)."""
    result = await session.execute(
        select(Transaction).where(
            Transaction.user_id == user_id, Transaction.status == "success"
        )
    )
    rows = list(result.scalars().all())
    paid = sum(
        (r.amount or Decimal(0)) for r in rows if r.transaction_type in _PAID_TYPES
    )
    received = sum(
        (r.amount or Decimal(0)) for r in rows if r.transaction_type in _RECEIVED_TYPES
    )
    return TransactionStats(
        total_paid=float(paid),
        total_received=float(received),
        net_amount=float(received - paid),
    )
