"""Claims and their documents.

The frontend ``Claim`` type reads: claim_number, claim_amount, approved_amount,
status, description, submission_date, created_at, and a nested ``policy``
summary, plus ``documents[{name, file_url}]`` (Downloads page).

Modelling choices:
- ``timeline`` stays JSONB — it is a genuinely flexible, append-only list of
  ``{status, date, note}`` events (verified reference shape) that the UI renders
  as-is. Documented here and in the README.
- ``documents`` are normalised into a ``claim_documents`` table (not JSONB) so
  each file is a real row linked to ``stored_files`` with its own access control
  in later phases. The ``{name, file_url}`` the frontend reads is composed from
  these rows at the response layer.
- ``approved_amount`` is a real column (frontend reads it) even though the
  reference create-path did not set it; it is populated by claim processing.

Deletion:
- ``user_id``   RESTRICT  — keep claim history; block accidental user hard-delete.
- ``policy_id`` SET NULL  — a removed policy must not delete claim history.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.files import StoredFile
    from app.db.models.identity import User
    from app.db.models.policies import Policy


class Claim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claims"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    claim_number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    claim_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    approved_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'submitted'")
    )
    submission_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    settled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Append-only event list: [{status, date, note}].
    timeline: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    user: Mapped[User] = relationship(back_populates="claims")
    policy: Mapped[Policy | None] = relationship(back_populates="claims")
    documents: Mapped[list[ClaimDocument]] = relationship(
        back_populates="claim",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_claims_user_id", "user_id"),
        Index("ix_claims_user_status", "user_id", "status"),
    )


class ClaimDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A document attached to a claim. Normalised from the reference JSONB blob."""

    __tablename__ = "claim_documents"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("stored_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    claim: Mapped[Claim] = relationship(back_populates="documents")
    file: Mapped[StoredFile | None] = relationship()

    __table_args__ = (Index("ix_claim_documents_claim_id", "claim_id"),)
