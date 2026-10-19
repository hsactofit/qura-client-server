"""Notifications (per-user) and announcements (global).

Frontend contract: notifications have title, message, type, is_read, created_at,
and an optional reference_id; announcements have title, message, type, start_date,
end_date, created_at and are shown within their active window.

``type`` is free text (the frontend maps a range of type strings to UI styling);
it is not constrained here so the UI's evolving set is not blocked.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.identity import User


class Notification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'info'")
    )
    is_read: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    reference_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship()

    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )


class Announcement(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "announcements"

    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'info'")
    )
    start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("ix_announcements_window", "start_date", "end_date"),)
