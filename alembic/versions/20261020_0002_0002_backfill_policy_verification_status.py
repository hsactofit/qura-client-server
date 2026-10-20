"""backfill policies.verification_status for pre-existing databases

Revision ID: 0002_policy_verification
Revises: 0001_initial
Create Date: 2026-10-20

Context: ``verification_status`` is declared in the initial migration so a FRESH
database gets the column directly. But a database created from an earlier
revision of ``0001`` (before the column existed) is already stamped at
``0001_initial`` and would never receive it. This migration backfills the
column for those pre-existing databases.

It is written to be SAFE on both:
- a fresh DB that already has the column from ``0001`` -> ``ADD COLUMN IF NOT
  EXISTS`` / ``CREATE ... IF NOT EXISTS`` are no-ops.
- a pre-existing DB missing the column -> the column and its check constraint
  are added, backfilling existing rows to ``self_reported`` via the server
  default.

Non-destructive: no table/column is dropped, truncated, or rewritten. The
downgrade is intentionally a no-op because the initial migration owns the
column's lifecycle (dropping it here would conflict with ``0001``'s downgrade).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_policy_verification"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add the column only when it is missing (idempotent across both DB states).
    op.execute(
        "ALTER TABLE policies ADD COLUMN IF NOT EXISTS verification_status "
        "VARCHAR(20) NOT NULL DEFAULT 'self_reported'"
    )
    # Add the CHECK constraint only when absent. DO block keeps it idempotent
    # since PostgreSQL has no ADD CONSTRAINT IF NOT EXISTS.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'policies_verification_status_valid'
            ) THEN
                ALTER TABLE policies ADD CONSTRAINT
                    policies_verification_status_valid
                    CHECK (verification_status IN
                        ('self_reported', 'user_confirmed', 'insurer_verified'));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # No-op: the column's lifecycle is owned by the initial migration.
    pass
