"""Policies owned by or tracked for a client.

Covers the audited ``policies_client`` schema including the documented insurance
extension fields (``policy_source``, ``proposal_id``, ``external_policy_id``,
``product_enum``) and the nullable ``policy_number`` with a partial-unique index
(a policy_number is unique only when present; platform-tracked policies start
pending with no number). ``benefits`` / ``exclusions`` are JSONB string arrays,
matching the frontend ``Policy`` type (``benefits?: string[]``).

Frontend ``Policy.name`` and ``covered_members`` are NOT columns here: ``name``
is derived from ``policy_type`` at the response layer and ``covered_members`` is
composed from family/claim data. See README "JSONB and derived fields".

The ``user_id`` FK keeps integrity (RESTRICT on user delete) — unlike the
reference backend which dropped it for mobile reasons that do not apply to Qura.
Document uploads are referenced via ``document_file_id`` into ``stored_files``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
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
    from app.db.models.assets import Asset
    from app.db.models.claims import Claim
    from app.db.models.identity import User
    from app.db.models.transactions import Transaction


class Policy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "policies"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    policy_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    policy_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    insurer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    coverage_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    premium_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    premium_frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )
    nominee_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    nominee_relationship: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    # JSONB string arrays (frontend: benefits?: string[]; exclusions?: string[]).
    benefits: Mapped[list | None] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    exclusions: Mapped[list | None] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Documented insurance-extension fields.
    policy_source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'uploaded'")
    )
    # Provenance of the stored policy facts, kept separate from ``status``
    # (the coverage lifecycle: active/expired/...). This distinguishes data a
    # user typed or let AI fill (``self_reported``), data the user has reviewed
    # and confirmed (``user_confirmed``), and data an authoritative insurer
    # integration verified (``insurer_verified``). A manual upload is NEVER
    # insurer_verified — that transition requires an authoritative source.
    # ``advisor_verified`` means a Qura advisor checked the document in the CRM.
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'self_reported'")
    )
    proposal_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_policy_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_enum: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_original_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_file_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("stored_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Full AI-read policy (plan, members, vehicle, waiting periods, key features,
    # claim support, summary). Shape: app.modules.policies.coverage.
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # The matching CRM policy (shared qura_main database, ``crm`` schema) and the
    # CRM ``updated_at`` last applied here. See app.modules.crm_sync.
    crm_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    crm_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="policies")
    claims: Mapped[list[Claim]] = relationship(
        back_populates="policy", passive_deletes=True
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="policy", passive_deletes=True
    )
    assets: Mapped[list[Asset]] = relationship(
        back_populates="current_policy",
        foreign_keys="Asset.current_policy_id",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "verification_status IN "
            "('self_reported', 'user_confirmed', 'advisor_verified', "
            "'insurer_verified')",
            name="policies_verification_status_valid",
        ),
        # policy_number unique only when present (platform policies start null).
        Index(
            "uq_policies_policy_number",
            "policy_number",
            unique=True,
            postgresql_where=text("policy_number IS NOT NULL"),
        ),
        Index(
            "ix_policies_proposal_id",
            "proposal_id",
            postgresql_where=text("proposal_id IS NOT NULL"),
        ),
        Index("ix_policies_user_id", "user_id"),
        Index(
            "uq_policies_crm_policy_id",
            "crm_policy_id",
            unique=True,
            postgresql_where=text("crm_policy_id IS NOT NULL"),
        ),
    )
