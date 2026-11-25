"""users.phone_verified_at for mobile-number (SMS code) sign-in

Revision ID: 0007_phone_verified_at
Revises: 0006_policy_number_per_user
Create Date: 2026-11-25

A client can sign in with their mobile number once they have proved they own
it with an SMS code (Firebase Phone Auth). This column records when that
happened. Existing numbers were typed in, never proved, so they start
unverified. Non-destructive; downgrade drops the column.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_phone_verified_at"
down_revision: str | None = "0006_policy_number_per_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "phone_verified_at")
