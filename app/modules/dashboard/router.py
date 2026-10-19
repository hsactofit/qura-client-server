"""Dashboard route.

  GET /dashboard -> {stats, recentPolicies, recentTransactions, coverageAnalysis}

Matches the frontend dashboard's expected shape. ``coverageAnalysis`` reports the
truthfully-computable ``totalCurrentCoverage`` and marks detailed gap analysis
as unavailable (no coverage/plan engine in this phase).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import success
from app.core.security import CurrentUser, require_authenticated
from app.db.session import get_session
from app.modules.dashboard import service
from app.modules.policies.mappers import policy_to_dict
from app.modules.transactions.mappers import transaction_to_dict

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
async def dashboard(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    data = await service.build_dashboard(session, user.id)
    return success(
        {
            "stats": {
                "activePolicies": data.active_policies,
                "upcomingRenewals": data.upcoming_renewals,
                "pendingClaims": data.pending_claims,
                "openTickets": data.open_tickets,
                "unreadNotifications": data.unread_notifications,
            },
            "recentPolicies": [policy_to_dict(p) for p in data.recent_policies],
            "recentTransactions": [
                transaction_to_dict(t) for t in data.recent_transactions
            ],
            "coverageAnalysis": {
                "status": "unavailable",
                "totalCurrentCoverage": data.total_current_coverage,
                "coverageGaps": None,
                "recommendations": [],
            },
        }
    )
