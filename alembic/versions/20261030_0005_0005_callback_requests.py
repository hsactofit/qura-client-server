"""call-back requests: categories, preferred time, endorsement copies

Revision ID: 0005_callback_requests
Revises: 0004_crm_sync
Create Date: 2026-10-30

A client asks their advisor to call back about one of a fixed set of topics
(quotation, policy correction, endorsement, renewal, payment, other) at a time
they choose, instead of free-text tickets with a fixed two-hour promise:

- ``support_tickets.preferred_callback_at``: when the client wants the call.
- ``support_tickets.insurance_type``: what a quotation request is for.
- ``support_tickets.document_file_id``: an endorsement copy the client uploaded.
- New categories ``quotation``, ``policy_correction``, ``endorsement``.
- ``stored_files.purpose`` gains ``endorsement``.

Non-destructive: only adds nullable columns and widens CHECK constraints.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005_callback_requests"
down_revision: str | None = "0004_crm_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

_CATEGORY_OLD = (
    "('claim', 'payment', 'policy_change', 'login', 'general', "
    "'renewal', 'callback', 'policy_query', 'claim_help')"
)
_CATEGORY_NEW = (
    "('claim', 'payment', 'policy_change', 'login', 'general', "
    "'renewal', 'callback', 'policy_query', 'claim_help', "
    "'quotation', 'policy_correction', 'endorsement')"
)
_PURPOSE_OLD = "('avatar', 'kyc', 'policy', 'claim', 'other')"
_PURPOSE_NEW = "('avatar', 'kyc', 'policy', 'claim', 'endorsement', 'other')"


def _replace_check(table: str, column: str, name: str, expr: str) -> None:
    """Swap the CHECK constraint on ``column`` for ``expr`` (found by definition)."""
    op.execute(
        f"""
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = '{table}'::regclass AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%{column}%'
            LOOP
                EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', r.conname);
            END LOOP;
        END $$;
        """
    )
    op.execute(f'ALTER TABLE {table} ADD CONSTRAINT "{name}" CHECK ({expr})')


def upgrade() -> None:
    op.add_column(
        "support_tickets",
        sa.Column("preferred_callback_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "support_tickets", sa.Column("insurance_type", sa.String(32), nullable=True)
    )
    op.add_column(
        "support_tickets",
        sa.Column(
            "document_file_id",
            UUID,
            sa.ForeignKey("stored_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    _replace_check(
        "support_tickets",
        "category",
        "ck_support_tickets_category_valid",
        f"category IS NULL OR category IN {_CATEGORY_NEW}",
    )
    _replace_check(
        "stored_files",
        "purpose",
        "ck_stored_files_purpose_valid",
        f"purpose IN {_PURPOSE_NEW}",
    )


def downgrade() -> None:
    # Fold the new values into older ones so the narrower constraints can be restored.
    op.execute(
        "UPDATE support_tickets SET category = 'policy_change' "
        "WHERE category IN ('policy_correction', 'endorsement')"
    )
    op.execute("UPDATE support_tickets SET category = 'general' WHERE category = 'quotation'")
    op.execute("UPDATE stored_files SET purpose = 'other' WHERE purpose = 'endorsement'")
    _replace_check(
        "stored_files",
        "purpose",
        "ck_stored_files_purpose_valid",
        f"purpose IN {_PURPOSE_OLD}",
    )
    _replace_check(
        "support_tickets",
        "category",
        "ck_support_tickets_category_valid",
        f"category IS NULL OR category IN {_CATEGORY_OLD}",
    )
    op.drop_column("support_tickets", "document_file_id")
    op.drop_column("support_tickets", "insurance_type")
    op.drop_column("support_tickets", "preferred_callback_at")
