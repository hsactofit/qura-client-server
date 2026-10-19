"""ORM -> frontend mapping for support tickets and messages."""

from __future__ import annotations

from typing import Any

from app.db.models.support import SupportTicket, TicketMessage


def ticket_to_dict(ticket: SupportTicket) -> dict[str, Any]:
    return {
        "id": str(ticket.id),
        "subject": ticket.subject,
        "category": ticket.category,
        "priority": ticket.priority,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
    }


def message_to_dict(msg: TicketMessage) -> dict[str, Any]:
    return {
        "id": str(msg.id),
        "ticket_id": str(msg.ticket_id),
        "sender_id": str(msg.sender_id) if msg.sender_id else None,
        "message": msg.message,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "attachments": None,
        # sender_profile is resolved at a later phase (needs a user join);
        # null keeps the frontend's optional-chaining happy.
        "sender_profile": None,
    }
