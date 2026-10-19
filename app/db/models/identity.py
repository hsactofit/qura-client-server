"""Identity: users, profiles, settings, invites, password-reset tokens.

Design notes
------------
- ``users`` holds account/identity + contact fields the frontend ``User`` type
  reads (id, email, full_name, phone, photo_url, address, role, status). Auth
  material (``password_hash``, ``token_invalidated_at``) lives here but is
  populated/consumed only by the later authentication phase.
- PII (``date_of_birth``, ``pan_number``, ``aadhaar_number``) and the softer
  profile attributes (annual income, occupation, lifestyle) live in a separate
  ``user_profiles`` table rather than a free-form JSON blob. This is the
  approved data-handling direction (typed columns, isolatable for encryption).
  The ``/user/profile`` response composes the two; that mapping is a later phase.
- ``role`` and ``status`` are constrained by CHECK to the values the frontend
  and admin console use, rather than Postgres enums, to keep migrations simple.

No fields are invented: every column traces to the verified frontend contract
(``src/contexts/AuthContext.tsx`` User/Profile) or the audited reference schema.
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
    from app.db.models.family import FamilyMember
    from app.db.models.policies import Policy
    from app.db.models.support import SupportTicket
    from app.db.models.transactions import Transaction

USER_ROLES = ("USER", "MANAGER", "ADMIN")
USER_STATUSES = ("ACTIVE", "INACTIVE", "INVITED")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    # Nullable so the auth phase owns how hashes are set; never logged.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'USER'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'ACTIVE'")
    )
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Soft delete (frontend admin console shows/restores deleted users).
    is_deleted: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Session-revocation marker for the auth phase (set on signout/reset).
    token_invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    profile: Mapped[UserProfile | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    settings: Mapped[UserSetting | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    policies: Mapped[list[Policy]] = relationship(
        back_populates="user", passive_deletes=True
    )
    claims: Mapped[list[Claim]] = relationship(
        back_populates="user", passive_deletes=True
    )
    assets: Mapped[list[Asset]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    family_members: Mapped[list[FamilyMember]] = relationship(
        back_populates="user", passive_deletes=True
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="user", passive_deletes=True
    )
    tickets: Mapped[list[SupportTicket]] = relationship(
        back_populates="user",
        foreign_keys="SupportTicket.user_id",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('USER', 'MANAGER', 'ADMIN')", name="users_role_valid"
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'INVITED')", name="users_status_valid"
        ),
        Index("ix_users_status", "status"),
        Index("ix_users_is_deleted", "is_deleted"),
    )


class UserProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Typed profile / PII, 1:1 with ``users``.

    Isolated from ``users`` so sensitive identity fields can later be encrypted
    or access-controlled without touching the account table.
    ``lifestyle`` is JSONB: ``{smoker: bool, alcohol: bool, exercise: str,
    checkups?: str}`` (shape from the frontend ``Profile.lifestyle`` type).
    """

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    pan_number: Mapped[str | None] = mapped_column(String(10), nullable=True)
    aadhaar_number: Mapped[str | None] = mapped_column(String(12), nullable=True)
    annual_income: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    occupation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lifestyle: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user: Mapped[User] = relationship(back_populates="profile")


class UserSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user settings, 1:1 with ``users``.

    ``dashboard_config`` is JSONB holding the flexible settings the frontend
    persists (notification channel toggles, language, font size, layout);
    stable, frequently read fields (``theme``, ``notifications``) are columns.
    """

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # Python-side ``default`` mirrors ``server_default`` so a freshly created
    # instance already carries the value in-process (before any DB refresh);
    # server_default still governs direct SQL inserts. This changes no schema.
    theme: Mapped[str] = mapped_column(
        String(16), nullable=False, default="system", server_default=text("'system'")
    )
    notifications: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )
    dashboard_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user: Mapped[User] = relationship(back_populates="settings")


class Invite(UUIDPrimaryKeyMixin, Base):
    """Invite-only registration token. Role is assigned at invite time.

    The token is stored hashed (the auth phase compares a hash, never the raw
    token) to avoid a readable credential at rest.
    """

    __tablename__ = "invites"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'USER'")
    )
    is_used: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('USER', 'MANAGER', 'ADMIN')", name="invites_role_valid"
        ),
        Index("ix_invites_email", "email"),
    )


class PasswordResetToken(UUIDPrimaryKeyMixin, Base):
    """Single-use password reset token (stored hashed)."""

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("ix_password_reset_tokens_user_id", "user_id"),)
