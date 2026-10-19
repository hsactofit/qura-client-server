"""Family members associated with a client.

Fields from the frontend ``FamilyMember`` type and the family CRUD contract
(``name, relationship, dob, gender, phone?, email?``). ``user_id`` cascades on
user delete: family rows have no meaning without their owner.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.identity import User


class FamilyMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "family_members"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Column is "relationship" in the contract; attribute renamed to avoid the
    # clash with SQLAlchemy's relationship() helper.
    relation: Mapped[str | None] = mapped_column(
        "relationship", String(50), nullable=True
    )
    dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    user: Mapped[User] = relationship(back_populates="family_members")

    __table_args__ = (Index("ix_family_members_user_id", "user_id"),)
