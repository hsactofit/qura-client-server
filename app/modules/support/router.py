"""Support ticket routes.

  GET  /support/tickets                      list the user's tickets
  GET  /support/tickets/{id}                 one ticket (ownership-enforced)
  GET  /support/tickets/{id}/messages        messages (ownership-enforced)
  POST /support/tickets/create               create a ticket
  POST /support/tickets/{id}/messages        post a message (ownership-enforced)
  POST /support/requests                     request a call back (multipart:
                                             kind, preferred_callback_at, policy_id?,
                                             insurance_type?, message?, document?)

The assigned-tickets (RM) view and WebSocket live updates are deferred. Writes
require CSRF.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.envelope import success
from app.core.errors import ApiError
from app.core.security import CurrentUser, enforce_csrf, require_authenticated
from app.core.uploads import enforce_size, sniff_document
from app.db.session import get_session
from app.modules.support import requests as callback_requests
from app.modules.support import service
from app.modules.support.mappers import message_to_dict, ticket_to_dict
from app.modules.support.schemas import CreateMessageRequest, CreateTicketRequest

router = APIRouter(prefix="/support/tickets", tags=["support"])
requests_router = APIRouter(prefix="/support/requests", tags=["support"])


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
        priority=body.priority, message=body.message,
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


@requests_router.post("")
async def create_request(
    kind: Annotated[str, Form()],
    preferred_callback_at: Annotated[str, Form()],
    policy_id: Annotated[str | None, Form()] = None,
    insurance_type: Annotated[str | None, Form()] = None,
    message: Annotated[str | None, Form()] = None,
    document: Annotated[UploadFile | None, File()] = None,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Ask the advisor to call back about a fixed topic at a chosen time."""
    try:
        when = datetime.fromisoformat(preferred_callback_at)
    except ValueError as exc:
        raise ApiError("Choose a valid call-back date and time", status_code=422) from exc
    note = (message or "").strip() or None
    if note and (len(note) > 2000 or "<" in note or ">" in note):
        raise ApiError(
            "Message must be under 2000 characters without '<' or '>'", status_code=422
        )
    data: bytes | None = None
    detected = None
    original_name: str | None = None
    if document is not None:
        data = await document.read() or None
        if data is not None:
            enforce_size(data, max_bytes=settings.upload_max_bytes)
            detected = sniff_document(data)
            original_name = document.filename
    ticket = await callback_requests.create_request(
        session,
        settings,
        user.id,
        kind=kind,
        preferred_callback_at=when,
        policy_id=(policy_id or "").strip() or None,
        insurance_type=(insurance_type or "").strip() or None,
        message=note,
        document=data,
        detected=detected,
        original_name=original_name,
    )
    return success(ticket_to_dict(ticket), "Call back requested")
