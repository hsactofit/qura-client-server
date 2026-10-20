"""add kyc_documents table

Revision ID: 0003_kyc_documents
Revises: 0002_policy_verification
Create Date: 2026-10-20

Adds the ``kyc_documents`` table backing client KYC uploads (PAN, Aadhaar, etc).
Each row links to a private ``stored_files`` row and records an honest review
status that defaults to ``pending`` (uploading never auto-verifies identity).

Non-destructive: only creates a new table, its constraints and indexes. Nothing
existing is altered or dropped. ``CREATE EXTENSION IF NOT EXISTS pgcrypto`` is
repeated defensively so ``gen_random_uuid()`` is available even if this runs on
a database that predates the initial migration's extension creation; it is a
no-op when the extension already exists.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_kyc_documents"
down_revision: str | None = "0002_policy_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "kyc_documents",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("file_id", UUID, nullable=True),
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "doc_type IN ('pan', 'aadhaar', 'passport', 'voter_id', "
            "'driving_license', 'other')",
            name="ck_kyc_documents_kyc_documents_doc_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'rejected')",
            name="ck_kyc_documents_kyc_documents_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_kyc_documents_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["stored_files.id"],
            name="fk_kyc_documents_file_id_stored_files", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_kyc_documents"),
        sa.UniqueConstraint("user_id", "doc_type", name="uq_kyc_documents_user_id_doc_type"),
    )
    op.create_index("ix_kyc_documents_user_id", "kyc_documents", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_kyc_documents_user_id", table_name="kyc_documents")
    op.drop_table("kyc_documents")
