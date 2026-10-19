"""Admin audit log.

Records admin user-management actions (status change, soft delete, restore, edit)
for the existing admin console. ``actor_id`` is the acting admin; ``target_id``
is the affected user (kept as a plain uuid, not an FK, so a log row survives the
target's hard deletion). ``changes`` is a JSONB diff: ``{field: [old, new]}``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.identity import User


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    changes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    actor: Mapped[User | None] = relationship()

    __table_args__ = (
        Index("ix_audit_logs_target_id", "target_id"),
        Index("ix_audit_logs_actor_id", "actor_id"),
    )
