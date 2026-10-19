"""Transaction history (read-only for the client portal).

Backs the portal's transaction list and invoice views. Phase 2 defines the
schema only; there is intentionally NO transaction-creation or payment workflow
(those were insecure in the reference backend and are out of scope). Rows are
populated by a trusted source in a later phase.

Frontend ``Transaction`` type reads: reference_id, description, policy_number?,
insurer_name?, transaction_type, amount (string), payment_mode?, status,
created_at. ``policy_number`` / ``insurer_name`` are joined from the policy at
the response layer, not duplicated here.

Deletion:
- ``user_id``   RESTRICT  — financial history is retained.
- ``policy_id`` SET NULL  — a removed policy keeps the transaction record.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.identity import User
    from app.db.models.policies import Policy

TRANSACTION_TYPES = ("purchase", "renewal", "payout", "refund")
TRANSACTION_STATUSES = ("success", "failed", "pending")


class Transaction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "transactions"

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
    transaction_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )
    payment_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship(back_populates="transactions")
    policy: Mapped[Policy | None] = relationship(back_populates="transactions")

    __table_args__ = (
        CheckConstraint(
            "transaction_type IS NULL OR transaction_type IN "
            "('purchase', 'renewal', 'payout', 'refund')",
            name="transactions_type_valid",
        ),
        CheckConstraint(
            "status IN ('success', 'failed', 'pending')",
            name="transactions_status_valid",
        ),
        Index("ix_transactions_user_created", "user_id", "created_at"),
    )
