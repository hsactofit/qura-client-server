"""KYC documents uploaded by a client.

Each row is one KYC document the client submitted (e.g. PAN, Aadhaar), linked to
a private ``stored_files`` row that holds the actual bytes. The frontend Profile
page reads the per-type status under ``preferences.kyc_documents`` (``{pan:
{name, status}, aadhaar: {...}}``); that view is composed from these rows at the
response layer.

Honest verification: ``status`` defaults to ``pending`` on upload and is NEVER
set to ``verified`` by the client action. Qura has no configured KYC/identity
verification provider, so uploading a document records a submission awaiting
review — it does not attest that identity was verified. Re-uploading the same
document type replaces the previous submission (the old stored file is removed by
the service), so there is at most one current document per (user, doc_type).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.files import StoredFile
    from app.db.models.identity import User

KYC_DOC_TYPES = ("pan", "aadhaar", "passport", "voter_id", "driving_license", "other")
KYC_STATUSES = ("pending", "verified", "rejected")


class KycDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "kyc_documents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("stored_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Honest default: a freshly uploaded document is awaiting review, never
    # auto-verified. Only a privileged, staff-side process (not this client API)
    # may ever set 'verified'/'rejected'.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )

    user: Mapped[User] = relationship()
    file: Mapped[StoredFile | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "doc_type IN ('pan', 'aadhaar', 'passport', 'voter_id', "
            "'driving_license', 'other')",
            name="kyc_documents_doc_type_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'verified', 'rejected')",
            name="kyc_documents_status_valid",
        ),
        # At most one current document per (user, doc_type); re-upload replaces.
        UniqueConstraint("user_id", "doc_type", name="uq_kyc_documents_user_id_doc_type"),
        Index("ix_kyc_documents_user_id", "user_id"),
    )
