"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-20

Initial Qura client-portal schema. Covers identity (users, profiles, settings,
invites, password-reset tokens), policies, claims + claim documents, assets,
family members, transactions, notifications, announcements, support tickets +
messages, stored files, master data and the admin audit log.

Reviewed manually against the SQLAlchemy models in app/db/models. Constraint and
index names follow the project naming convention (app/db/base.py). pgcrypto is
required for gen_random_uuid() UUID primary keys.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    # gen_random_uuid() lives in pgcrypto on PostgreSQL < 13; harmless if present.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # --- users -------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("role", sa.String(length=16), server_default=sa.text("'USER'"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('USER', 'MANAGER', 'ADMIN')", name="ck_users_users_role_valid"),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'INVITED')", name="ck_users_users_status_valid"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("phone", name="uq_users_phone"),
    )
    op.create_index("ix_users_status", "users", ["status"])
    op.create_index("ix_users_is_deleted", "users", ["is_deleted"])

    # --- stored_files (referenced by policies/claims) ----------------------
    op.create_table(
        "stored_files",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_user_id", UUID, nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('avatar', 'kyc', 'policy', 'claim', 'other')",
            name="ck_stored_files_stored_files_purpose_valid",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name="fk_stored_files_owner_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stored_files"),
        sa.UniqueConstraint("storage_key", name="uq_stored_files_storage_key"),
    )
    op.create_index("ix_stored_files_owner_user_id", "stored_files", ["owner_user_id"])

    # --- user_profiles -----------------------------------------------------
    op.create_table(
        "user_profiles",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("pan_number", sa.String(length=10), nullable=True),
        sa.Column("aadhaar_number", sa.String(length=12), nullable=True),
        sa.Column("annual_income", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("occupation", sa.String(length=120), nullable=True),
        sa.Column("lifestyle", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_profiles_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_profiles"),
        sa.UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
    )

    # --- user_settings -----------------------------------------------------
    op.create_table(
        "user_settings",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("theme", sa.String(length=16), server_default=sa.text("'system'"), nullable=False),
        sa.Column("notifications", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("dashboard_config", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_settings_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_settings"),
        sa.UniqueConstraint("user_id", name="uq_user_settings_user_id"),
    )

    # --- invites -----------------------------------------------------------
    op.create_table(
        "invites",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), server_default=sa.text("'USER'"), nullable=False),
        sa.Column("is_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('USER', 'MANAGER', 'ADMIN')", name="ck_invites_invites_role_valid"),
        sa.PrimaryKeyConstraint("id", name="pk_invites"),
        sa.UniqueConstraint("token_hash", name="uq_invites_token_hash"),
    )
    op.create_index("ix_invites_email", "invites", ["email"])

    # --- password_reset_tokens ---------------------------------------------
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_password_reset_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])

    # --- policies ----------------------------------------------------------
    op.create_table(
        "policies",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("policy_number", sa.String(length=100), nullable=True),
        sa.Column("policy_type", sa.String(length=50), nullable=True),
        sa.Column("insurer_name", sa.String(length=200), nullable=True),
        sa.Column("coverage_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("premium_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("premium_frequency", sa.String(length=20), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
        sa.Column("nominee_name", sa.String(length=200), nullable=True),
        sa.Column("nominee_relationship", sa.String(length=50), nullable=True),
        sa.Column("benefits", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("exclusions", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("policy_source", sa.String(length=20), server_default=sa.text("'uploaded'"), nullable=False),
        sa.Column("proposal_id", sa.String(length=100), nullable=True),
        sa.Column("external_policy_id", sa.String(length=100), nullable=True),
        sa.Column("product_enum", sa.String(length=100), nullable=True),
        sa.Column("document_original_name", sa.Text(), nullable=True),
        sa.Column("document_file_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_policies_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["document_file_id"], ["stored_files.id"],
            name="fk_policies_document_file_id_stored_files", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_policies"),
    )
    op.create_index("ix_policies_user_id", "policies", ["user_id"])
    op.create_index(
        "uq_policies_policy_number", "policies", ["policy_number"], unique=True,
        postgresql_where=sa.text("policy_number IS NOT NULL"),
    )
    op.create_index(
        "ix_policies_proposal_id", "policies", ["proposal_id"],
        postgresql_where=sa.text("proposal_id IS NOT NULL"),
    )

    # --- assets ------------------------------------------------------------
    op.create_table(
        "assets",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("asset_type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("registration_no", sa.String(length=32), nullable=True),
        sa.Column("make", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=80), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("fuel_type", sa.String(length=20), nullable=True),
        sa.Column("color", sa.String(length=40), nullable=True),
        sa.Column("chassis_no", sa.String(length=64), nullable=True),
        sa.Column("engine_no", sa.String(length=64), nullable=True),
        sa.Column("property_address", sa.Text(), nullable=True),
        sa.Column("property_type", sa.String(length=40), nullable=True),
        sa.Column("property_area_sqft", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("current_policy_id", UUID, nullable=True),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "asset_type IN ('car', 'two_wheeler', 'home', 'shop', 'other')",
            name="ck_assets_assets_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_assets_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["current_policy_id"], ["policies.id"],
            name="fk_assets_current_policy_id_policies", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assets"),
    )
    op.create_index("ix_assets_user_id", "assets", ["user_id"])
    op.create_index(
        "ix_assets_registration_no", "assets", ["registration_no"],
        postgresql_where=sa.text("registration_no IS NOT NULL"),
    )

    # --- family_members ----------------------------------------------------
    op.create_table(
        "family_members",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("relationship", sa.String(length=50), nullable=True),
        sa.Column("dob", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(length=20), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_family_members_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_family_members"),
    )
    op.create_index("ix_family_members_user_id", "family_members", ["user_id"])

    # --- claims ------------------------------------------------------------
    op.create_table(
        "claims",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("policy_id", UUID, nullable=True),
        sa.Column("claim_number", sa.String(length=40), nullable=False),
        sa.Column("claim_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("approved_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'submitted'"), nullable=False),
        sa.Column("submission_date", sa.Date(), nullable=True),
        sa.Column("settled_date", sa.Date(), nullable=True),
        sa.Column("timeline", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_claims_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["policies.id"], name="fk_claims_policy_id_policies", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_claims"),
        sa.UniqueConstraint("claim_number", name="uq_claims_claim_number"),
    )
    op.create_index("ix_claims_user_id", "claims", ["user_id"])
    op.create_index("ix_claims_user_status", "claims", ["user_id", "status"])

    # --- claim_documents ---------------------------------------------------
    op.create_table(
        "claim_documents",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("claim_id", UUID, nullable=False),
        sa.Column("file_id", UUID, nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_id"], ["claims.id"], name="fk_claim_documents_claim_id_claims", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["stored_files.id"],
            name="fk_claim_documents_file_id_stored_files", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_claim_documents"),
    )
    op.create_index("ix_claim_documents_claim_id", "claim_documents", ["claim_id"])

    # --- transactions ------------------------------------------------------
    op.create_table(
        "transactions",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("policy_id", UUID, nullable=True),
        sa.Column("transaction_type", sa.String(length=20), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("payment_mode", sa.String(length=20), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "transaction_type IS NULL OR transaction_type IN "
            "('purchase', 'renewal', 'payout', 'refund')",
            name="ck_transactions_transactions_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('success', 'failed', 'pending')",
            name="ck_transactions_transactions_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_transactions_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["policies.id"], name="fk_transactions_policy_id_policies", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.UniqueConstraint("reference_id", name="uq_transactions_reference_id"),
    )
    op.create_index("ix_transactions_user_created", "transactions", ["user_id", "created_at"])

    # --- notifications -----------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=40), server_default=sa.text("'info'"), nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reference_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_notifications_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])

    # --- announcements -----------------------------------------------------
    op.create_table(
        "announcements",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=40), server_default=sa.text("'info'"), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_announcements"),
    )
    op.create_index("ix_announcements_window", "announcements", ["start_date", "end_date"])

    # --- support_tickets ---------------------------------------------------
    op.create_table(
        "support_tickets",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("assigned_rm_id", UUID, nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'open'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "category IS NULL OR category IN "
            "('claim', 'payment', 'policy_change', 'login', 'general')",
            name="ck_support_tickets_support_tickets_category_valid",
        ),
        sa.CheckConstraint(
            "priority IS NULL OR priority IN ('low', 'medium', 'high', 'urgent')",
            name="ck_support_tickets_support_tickets_priority_valid",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="ck_support_tickets_support_tickets_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_support_tickets_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_rm_id"], ["users.id"],
            name="fk_support_tickets_assigned_rm_id_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_tickets"),
    )
    op.create_index("ix_support_tickets_user_created", "support_tickets", ["user_id", "created_at"])
    op.create_index(
        "ix_support_tickets_assigned_rm_created", "support_tickets", ["assigned_rm_id", "created_at"]
    )

    # --- ticket_messages ---------------------------------------------------
    op.create_table(
        "ticket_messages",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("ticket_id", UUID, nullable=False),
        sa.Column("sender_id", UUID, nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["support_tickets.id"],
            name="fk_ticket_messages_ticket_id_support_tickets", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"], ["users.id"], name="fk_ticket_messages_sender_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ticket_messages"),
    )
    op.create_index("ix_ticket_messages_ticket_created", "ticket_messages", ["ticket_id", "created_at"])

    # --- master_data -------------------------------------------------------
    op.create_table(
        "master_data",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_master_data"),
    )
    op.create_index("ix_master_data_category", "master_data", ["category"])

    # --- audit_logs --------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("actor_id", UUID, nullable=True),
        sa.Column("target_id", UUID, nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("changes", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_logs_actor_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_logs_target_id", "audit_logs", ["target_id"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("master_data")
    op.drop_table("ticket_messages")
    op.drop_table("support_tickets")
    op.drop_table("announcements")
    op.drop_table("notifications")
    op.drop_table("transactions")
    op.drop_table("claim_documents")
    op.drop_table("claims")
    op.drop_table("family_members")
    op.drop_table("assets")
    op.drop_table("policies")
    op.drop_table("password_reset_tokens")
    op.drop_table("invites")
    op.drop_table("user_settings")
    op.drop_table("user_profiles")
    op.drop_table("stored_files")
    op.drop_table("users")
