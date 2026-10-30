"""Dashboard aggregation from the authenticated user's own records.

Every figure is a real query against the user's data; nothing is hardcoded.

Coverage analysis limitation: the reference backend computed recommendations via
a coverage/plan engine and a plans catalog that are NOT part of the Qura schema
or this phase. We therefore return the one figure we can compute truthfully —
``totalCurrentCoverage`` (sum of active-policy coverage) — and mark the rest
``status: "unavailable"`` with empty recommendations, rather than inventing gap
numbers. This is documented in the README as a follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.claims import Claim
from app.db.models.engagement import Notification
from app.db.models.policies import Policy
from app.db.models.support import SupportTicket
from app.db.models.transactions import Transaction

_RENEWAL_WINDOW_DAYS = 30
# Claims still being worked (see crm_sync._CLAIM_STATUS for the full set).
_ACTIVE_CLAIM_STATES = ("submitted", "documents_pending", "in_review")
# Matches the sidebar's open-ticket badge: resolved/closed are not open.
_OPEN_TICKET_STATES = ("open", "in_progress")


@dataclass(frozen=True)
class DashboardData:
    active_policies: int
    upcoming_renewals: int
    pending_claims: int
    open_tickets: int
    unread_notifications: int
    recent_policies: list[Policy]
    recent_transactions: list[Transaction]
    total_current_coverage: float


async def _all(session: AsyncSession, stmt):  # type: ignore[no-untyped-def]
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def build_dashboard(session: AsyncSession, user_id: str) -> DashboardData:
    policies = await _all(
        session,
        select(Policy)
        .where(Policy.user_id == user_id)
        .order_by(Policy.created_at.desc()),
    )
    claims = await _all(session, select(Claim).where(Claim.user_id == user_id))
    tickets = await _all(
        session, select(SupportTicket).where(SupportTicket.user_id == user_id)
    )
    notifications = await _all(
        session, select(Notification).where(Notification.user_id == user_id)
    )
    transactions = await _all(
        session,
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.created_at.desc())
        .limit(5),
    )

    active = [p for p in policies if p.status == "active"]
    today = datetime.now(UTC).date()
    soon = today + timedelta(days=_RENEWAL_WINDOW_DAYS)

    def _within_renewal(p: Policy) -> bool:
        end = p.end_date
        if end is None:
            return False
        if isinstance(end, datetime):
            end = end.date()
        if not isinstance(end, date):
            return False
        return today <= end <= soon

    upcoming = [p for p in active if _within_renewal(p)]
    pending_claims = [c for c in claims if c.status in _ACTIVE_CLAIM_STATES]
    open_tickets = [t for t in tickets if t.status in _OPEN_TICKET_STATES]
    unread = [n for n in notifications if not n.is_read]

    total_coverage = sum(
        (p.coverage_amount or Decimal(0)) for p in active
    )

    return DashboardData(
        active_policies=len(active),
        upcoming_renewals=len(upcoming),
        pending_claims=len(pending_claims),
        open_tickets=len(open_tickets),
        unread_notifications=len(unread),
        recent_policies=policies[:3],
        recent_transactions=transactions,
        total_current_coverage=float(total_coverage),
    )
