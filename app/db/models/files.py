"""Registry of uploaded files.

A single table backing every upload (avatar, KYC doc, policy doc, claim doc)
instead of scattering public URLs across rows. Phase 2 only defines the schema;
secure storage and authenticated download are implemented in a later phase.
``storage_key`` is the opaque backend location (object key or relative path),
never a public URL. ``sha256`` supports de-duplication and integrity checks.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.identity import User

FILE_PURPOSES = ("avatar", "kyc", "policy", "claim", "other")


class StoredFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stored_files"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    original_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    owner: Mapped[User] = relationship()

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('avatar', 'kyc', 'policy', 'claim', 'other')",
            name="stored_files_purpose_valid",
        ),
        Index("ix_stored_files_owner_user_id", "owner_user_id"),
    )
