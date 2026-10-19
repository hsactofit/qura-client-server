"""Client assets (vehicles and property) for insurance pre-fill.

Fields and the ``asset_type`` set (car, two_wheeler, home, shop, other) come
from the frontend ``Asset`` type (``src/services/insurance.service.ts``).

Deletion policy (deliberate):
- ``user_id``           ON DELETE CASCADE  — assets belong to the user; when a
  user is hard-deleted their assets go with them.
- ``current_policy_id`` ON DELETE SET NULL — a deleted policy must not delete
  the asset; the link is simply cleared.
These mirror the audited ``assets_client`` FK behavior.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
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
    from app.db.models.identity import User
    from app.db.models.policies import Policy

ASSET_TYPES = ("car", "two_wheeler", "home", "shop", "other")


class Asset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Vehicle fields
    registration_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    make: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    color: Mapped[str | None] = mapped_column(String(40), nullable=True)
    chassis_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine_no: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Property fields
    property_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    property_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    property_area_sqft: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    current_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    extra_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    user: Mapped[User] = relationship(back_populates="assets")
    current_policy: Mapped[Policy | None] = relationship(
        back_populates="assets", foreign_keys=[current_policy_id]
    )

    __table_args__ = (
        CheckConstraint(
            "asset_type IN ('car', 'two_wheeler', 'home', 'shop', 'other')",
            name="assets_type_valid",
        ),
        Index("ix_assets_user_id", "user_id"),
        Index(
            "ix_assets_registration_no",
            "registration_no",
            postgresql_where=text("registration_no IS NOT NULL"),
        ),
    )
