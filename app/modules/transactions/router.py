"""Transaction routes (read-only).

  GET /transactions?page=&limit=&type=&status=&search=

Returns ``{data, pagination: {total, page, limit}, stats}`` to match the
frontend's transaction page. No creation/refund/gateway (out of scope).
Invoice generation (/transactions/{id}/invoice) is deferred — see README.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import success
from app.core.pagination import parse_page
from app.core.security import CurrentUser, require_authenticated
from app.db.session import get_session
from app.modules.transactions import service
from app.modules.transactions.mappers import transaction_to_dict

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("")
async def list_transactions(
    page: int = 1,
    limit: int = 10,
    type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    paging = parse_page(page, limit)
    rows, total = await service.list_transactions(
        session, user.id, paging, type_=type, status=status, search=search
    )
    stats = await service.compute_stats(session, user.id)
    return success(
        {
            "data": [transaction_to_dict(t) for t in rows],
            "pagination": {"total": total, "page": paging.page, "limit": paging.limit},
            "stats": {
                "totalPaid": stats.total_paid,
                "totalReceived": stats.total_received,
                "netAmount": stats.net_amount,
            },
        }
    )
