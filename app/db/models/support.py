"""Support tickets and their messages.

Frontend ``Ticket`` type: subject, category (claim|payment|policy_change|login|
general), priority (low|medium|high|urgent), status (open|in_progress|resolved|
closed), timestamps; ``TicketMessage``: ticket_id, sender_id (nullable), message,
created_at, sender_profile.

- A ticket has an owner (``user_id``) and an assigned RM (``assigned_rm_id``),
  both referencing ``users``. The two FKs to the same table require explicit
  ``foreign_keys`` on the relationships.
- Owner delete CASCADEs the ticket (it belongs to the client); the assigned RM
  link SET NULLs so removing staff does not delete client tickets.
- Messages CASCADE with their ticket; a removed sender SET NULLs the author.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.identity import User

TICKET_CATEGORIES = ("claim", "payment", "policy_change", "login", "general")
TICKET_PRIORITIES = ("low", "medium", "high", "urgent")
TICKET_STATUSES = ("open", "in_progress", "resolved", "closed")


class SupportTicket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_tickets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_rm_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'open'")
    )

    user: Mapped[User] = relationship(
        back_populates="tickets", foreign_keys=[user_id]
    )
    assigned_rm: Mapped[User | None] = relationship(foreign_keys=[assigned_rm_id])
    messages: Mapped[list[TicketMessage]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "category IS NULL OR category IN "
            "('claim', 'payment', 'policy_change', 'login', 'general')",
            name="support_tickets_category_valid",
        ),
        CheckConstraint(
            "priority IS NULL OR priority IN ('low', 'medium', 'high', 'urgent')",
            name="support_tickets_priority_valid",
        ),
        CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="support_tickets_status_valid",
        ),
        Index("ix_support_tickets_user_created", "user_id", "created_at"),
        Index(
            "ix_support_tickets_assigned_rm_created", "assigned_rm_id", "created_at"
        ),
    )


class TicketMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ticket_messages"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    ticket: Mapped[SupportTicket] = relationship(back_populates="messages")
    sender: Mapped[User | None] = relationship()

    __table_args__ = (
        Index("ix_ticket_messages_ticket_created", "ticket_id", "created_at"),
    )
