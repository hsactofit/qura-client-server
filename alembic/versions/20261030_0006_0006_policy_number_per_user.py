"""policy numbers are unique per client, not across all clients

Revision ID: 0006_policy_number_per_user
Revises: 0005_callback_requests
Create Date: 2026-10-30

``uq_policies_policy_number`` made a policy number unique across every client,
while uploads only checked the uploading client's own policies. A number already
on another account (a family floater shared by two members, the same sample
policy uploaded from two test accounts) therefore failed with an integrity error
(HTTP 500). A number is now unique per client.

Non-destructive: the old index was stricter, so existing rows already satisfy
the new one. Downgrade recreates the global index and fails if two clients now
share a number.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_policy_number_per_user"
down_revision: str | None = "0005_callback_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_policies_user_policy_number",
        "policies",
        ["user_id", "policy_number"],
        unique=True,
        postgresql_where=sa.text("policy_number IS NOT NULL"),
    )
    op.drop_index("uq_policies_policy_number", table_name="policies")


def downgrade() -> None:
    op.create_index(
        "uq_policies_policy_number",
        "policies",
        ["policy_number"],
        unique=True,
        postgresql_where=sa.text("policy_number IS NOT NULL"),
    )
    op.drop_index("uq_policies_user_policy_number", table_name="policies")
