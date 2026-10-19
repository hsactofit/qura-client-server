"""Support ticket routes.

  GET  /support/tickets                      list the user's tickets
  GET  /support/tickets/{id}                 one ticket (ownership-enforced)
  GET  /support/tickets/{id}/messages        messages (ownership-enforced)
  POST /support/tickets/create               create a ticket
  POST /support/tickets/{id}/messages        post a message (ownership-enforced)

The assigned-tickets (RM) view and WebSocket live updates are deferred. Writes
require CSRF.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import success
from app.core.security import CurrentUser, enforce_csrf, require_authenticated
from app.db.session import get_session
from app.modules.support import service
from app.modules.support.mappers import message_to_dict, ticket_to_dict
from app.modules.support.schemas import CreateMessageRequest, CreateTicketRequest

router = APIRouter(prefix="/support/tickets", tags=["support"])


@router.get("")
async def list_tickets(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    tickets = await service.list_tickets(session, user.id)
    return success([ticket_to_dict(t) for t in tickets])


@router.post("/create")
async def create_ticket(
    body: CreateTicketRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ticket = await service.create_ticket(
        session, user.id, subject=body.subject, category=body.category,
        priority=body.priority,
    )
    return success(ticket_to_dict(ticket), "Ticket created")


@router.get("/{ticket_id}/messages")
async def list_messages(
    ticket_id: str,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    messages = await service.list_messages(session, user.id, ticket_id)
    return success([message_to_dict(m) for m in messages])


@router.post("/{ticket_id}/messages")
async def create_message(
    ticket_id: str,
    body: CreateMessageRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    msg = await service.create_message(session, user.id, ticket_id, message=body.message)
    return success(message_to_dict(msg), "Message sent")


@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ticket = await service.get_ticket(session, user.id, ticket_id)
    return success(ticket_to_dict(ticket))
