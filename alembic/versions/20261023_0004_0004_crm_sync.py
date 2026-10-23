"""link the client portal to the CRM (shared qura_main database)

Revision ID: 0004_crm_sync
Revises: 0003_kyc_documents
Create Date: 2026-10-23

The portal and the CRM now share one database (``qura_main``), each in its own
schema. This revision adds what the portal needs to mirror CRM-side work:

- ``policies.details`` (JSONB): the full AI-read policy (plan, members, vehicle,
  waiting periods, key features, claim support, plain-language summary).
- ``policies.crm_policy_id`` / ``crm_synced_at``: the matching CRM policy and the
  CRM ``updated_at`` last applied, so sync is idempotent and state-based.
- ``verification_status`` gains ``advisor_verified`` (a Qura advisor checked the
  document in the CRM); ``insurer_verified`` stays reserved for insurer APIs.
- ``support_tickets.policy_id`` plus new request categories (renewal, callback,
  policy_query, claim_help), so a client can ask about a specific policy.
- ``ticket_messages.sender_name`` / ``external_ref``: advisor replies synced from
  the CRM (no portal user behind them) without duplicates.

Non-destructive: only adds columns and widens CHECK constraints.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_crm_sync"
down_revision: str | None = "0003_kyc_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

_VERIFICATION_OLD = "('self_reported', 'user_confirmed', 'insurer_verified')"
_VERIFICATION_NEW = (
    "('self_reported', 'user_confirmed', 'advisor_verified', 'insurer_verified')"
)
_CATEGORY_OLD = "('claim', 'payment', 'policy_change', 'login', 'general')"
_CATEGORY_NEW = (
    "('claim', 'payment', 'policy_change', 'login', 'general', "
    "'renewal', 'callback', 'policy_query', 'claim_help')"
)


def _replace_check(table: str, column: str, name: str, expr: str) -> None:
    """Swap the CHECK constraint on ``column`` for ``expr``.

    The existing constraint is found by what it checks, not by name: names
    produced by the metadata naming convention were truncated and hashed by
    Postgres' 63-character limit in the initial migration.
    """
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
        "policies",
        sa.Column(
            "details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("policies", sa.Column("crm_policy_id", UUID, nullable=True))
    op.add_column(
        "policies",
        sa.Column("crm_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_policies_crm_policy_id",
        "policies",
        ["crm_policy_id"],
        unique=True,
        postgresql_where=sa.text("crm_policy_id IS NOT NULL"),
    )
    _replace_check(
        "policies",
        "verification_status",
        "ck_policies_verification_status_valid",
        f"verification_status IN {_VERIFICATION_NEW}",
    )

    op.add_column(
        "support_tickets",
        sa.Column(
            "policy_id",
            UUID,
            sa.ForeignKey("policies.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    _replace_check(
        "support_tickets",
        "category",
        "ck_support_tickets_category_valid",
        f"category IS NULL OR category IN {_CATEGORY_NEW}",
    )

    op.add_column(
        "ticket_messages", sa.Column("sender_name", sa.String(200), nullable=True)
    )
    op.add_column(
        "ticket_messages", sa.Column("external_ref", sa.String(100), nullable=True)
    )
    op.create_index(
        "uq_ticket_messages_external_ref",
        "ticket_messages",
        ["external_ref"],
        unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ticket_messages_external_ref", table_name="ticket_messages")
    op.drop_column("ticket_messages", "external_ref")
    op.drop_column("ticket_messages", "sender_name")
    _replace_check(
        "support_tickets",
        "category",
        "ck_support_tickets_category_valid",
        f"category IS NULL OR category IN {_CATEGORY_OLD}",
    )
    op.drop_column("support_tickets", "policy_id")
    _replace_check(
        "policies",
        "verification_status",
        "ck_policies_verification_status_valid",
        f"verification_status IN {_VERIFICATION_OLD}",
    )
    op.drop_index("uq_policies_crm_policy_id", table_name="policies")
    op.drop_column("policies", "crm_synced_at")
    op.drop_column("policies", "crm_policy_id")
    op.drop_column("policies", "details")
