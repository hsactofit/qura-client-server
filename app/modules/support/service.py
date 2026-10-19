"""Support ticket + message queries/mutations.

Ownership model matches the reference contract: a client sees only their own
tickets; message access requires being the ticket owner (RM/assignee access is
an admin/manager concern deferred to a later phase). Ticket IDs cannot be used
to read another user's conversation — every message query re-checks ownership.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.models.support import SupportTicket, TicketMessage


async def list_tickets(session: AsyncSession, user_id: str) -> list[SupportTicket]:
    result = await session.execute(
        select(SupportTicket)
        .where(SupportTicket.user_id == user_id)
        .order_by(SupportTicket.created_at.desc())
    )
    return list(result.scalars().all())


async def get_ticket(
    session: AsyncSession, user_id: str, ticket_id: str
) -> SupportTicket:
    result = await session.execute(
        select(SupportTicket).where(
            SupportTicket.id == ticket_id, SupportTicket.user_id == user_id
        )
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise ApiError("Ticket not found", status_code=404)
    return ticket


async def list_messages(
    session: AsyncSession, user_id: str, ticket_id: str
) -> list[TicketMessage]:
    # Ownership check first (raises 404 if not the user's ticket).
    await get_ticket(session, user_id, ticket_id)
    result = await session.execute(
        select(TicketMessage)
        .where(TicketMessage.ticket_id == ticket_id)
        .order_by(TicketMessage.created_at.asc())
    )
    return list(result.scalars().all())


async def create_ticket(
    session: AsyncSession,
    user_id: str,
    *,
    subject: str,
    category: str | None,
    priority: str | None,
) -> SupportTicket:
    ticket = SupportTicket(
        user_id=user_id,
        subject=subject,
        category=category,
        priority=priority,
        status="open",
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def create_message(
    session: AsyncSession, user_id: str, ticket_id: str, *, message: str
) -> TicketMessage:
    await get_ticket(session, user_id, ticket_id)  # ownership
    msg = TicketMessage(ticket_id=ticket_id, sender_id=user_id, message=message)
    session.add(msg)
    await session.flush()
    return msg
