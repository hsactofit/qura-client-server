"""Model metadata: registration, keys, FKs, constraints, indexes.

These checks run without a database. They pin the schema the models declare so
drift is caught in CI even when no PostgreSQL is available.
"""

from __future__ import annotations

import app.db.models as models
from app.db.base import Base

# Tables created by the initial migration (0001). Kept as its own set so the
# initial-migration tests can assert against exactly what 0001 creates, while
# later migrations (e.g. 0003 adds kyc_documents) introduce additional tables.
TABLES_IN_INITIAL_MIGRATION = {
    "users",
    "user_profiles",
    "user_settings",
    "invites",
    "password_reset_tokens",
    "policies",
    "claims",
    "claim_documents",
    "assets",
    "family_members",
    "transactions",
    "notifications",
    "announcements",
    "support_tickets",
    "ticket_messages",
    "stored_files",
    "master_data",
    "audit_logs",
}

# The full set of tables the models declare today (initial migration plus every
# table added by a later migration).
EXPECTED_TABLES = TABLES_IN_INITIAL_MIGRATION | {
    "kyc_documents",  # added in migration 0003
}


def test_all_models_importable() -> None:
    # Importing the package registered every model; spot-check the exports.
    assert models.User.__tablename__ == "users"
    assert models.Claim.__tablename__ == "claims"
    assert models.StoredFile.__tablename__ == "stored_files"


def test_expected_tables_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_table_has_uuid_primary_key() -> None:
    for name, table in Base.metadata.tables.items():
        pk_cols = list(table.primary_key.columns)
        assert len(pk_cols) == 1, f"{name} should have a single-column PK"
        assert pk_cols[0].name == "id", f"{name} PK column should be 'id'"


def test_naming_convention_applied() -> None:
    users = Base.metadata.tables["users"]
    assert users.primary_key.name == "pk_users"
    # Unique constraint on email uses the convention.
    uqs = {c.name for c in users.constraints if c.__class__.__name__ == "UniqueConstraint"}
    assert "uq_users_email" in uqs


def _fk(table_name: str, column: str):  # type: ignore[no-untyped-def]
    table = Base.metadata.tables[table_name]
    for fk in table.foreign_keys:
        if fk.parent.name == column:
            return fk
    raise AssertionError(f"no FK on {table_name}.{column}")


def test_key_foreign_keys_and_ondelete() -> None:
    # Cascade: profile/settings/assets/family/stored_files/notifications belong
    # to the user and go with a hard delete.
    assert _fk("user_profiles", "user_id").ondelete == "CASCADE"
    assert _fk("assets", "user_id").ondelete == "CASCADE"
    assert _fk("family_members", "user_id").ondelete == "CASCADE"
    assert _fk("stored_files", "owner_user_id").ondelete == "CASCADE"
    # Restrict: policies/claims/transactions preserve history.
    assert _fk("policies", "user_id").ondelete == "RESTRICT"
    assert _fk("claims", "user_id").ondelete == "RESTRICT"
    assert _fk("transactions", "user_id").ondelete == "RESTRICT"
    # Set null: a removed policy must not delete dependent history.
    assert _fk("claims", "policy_id").ondelete == "SET NULL"
    assert _fk("transactions", "policy_id").ondelete == "SET NULL"
    assert _fk("assets", "current_policy_id").ondelete == "SET NULL"
    # Support: owner cascade, assigned RM set null.
    assert _fk("support_tickets", "user_id").ondelete == "CASCADE"
    assert _fk("support_tickets", "assigned_rm_id").ondelete == "SET NULL"
    assert _fk("ticket_messages", "ticket_id").ondelete == "CASCADE"
    assert _fk("ticket_messages", "sender_id").ondelete == "SET NULL"


def test_unique_constraints_present() -> None:
    users = Base.metadata.tables["users"]
    unique_cols = {
        tuple(c.name for c in con.columns)
        for con in users.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("email",) in unique_cols
    assert ("phone",) in unique_cols

    for table_name, col in [
        ("claims", "claim_number"),
        ("transactions", "reference_id"),
        ("invites", "token_hash"),
        ("user_profiles", "user_id"),
        ("user_settings", "user_id"),
        ("stored_files", "storage_key"),
    ]:
        table = Base.metadata.tables[table_name]
        uniques = {
            tuple(c.name for c in con.columns)
            for con in table.constraints
            if con.__class__.__name__ == "UniqueConstraint"
        }
        assert (col,) in uniques, f"{table_name}.{col} should be unique"


def test_partial_unique_index_on_policy_number() -> None:
    policies = Base.metadata.tables["policies"]
    idx = {i.name: i for i in policies.indexes}
    assert "uq_policies_policy_number" in idx
    assert idx["uq_policies_policy_number"].unique is True
    # Partial predicate present (policy_number IS NOT NULL).
    assert idx["uq_policies_policy_number"].dialect_options["postgresql"]["where"] is not None


def test_check_constraints_present() -> None:
    users = Base.metadata.tables["users"]
    checks = {c.name for c in users.constraints if c.__class__.__name__ == "CheckConstraint"}
    assert "ck_users_users_role_valid" in checks
    assert "ck_users_users_status_valid" in checks


def test_monetary_columns_use_numeric_14_2() -> None:
    for table_name, col in [
        ("policies", "coverage_amount"),
        ("policies", "premium_amount"),
        ("claims", "claim_amount"),
        ("transactions", "amount"),
    ]:
        column = Base.metadata.tables[table_name].columns[col]
        assert column.type.precision == 14
        assert column.type.scale == 2


def test_jsonb_columns_exist() -> None:
    # Documented JSONB fields are represented as JSONB.
    jsonb_fields = [
        ("policies", "benefits"),
        ("policies", "exclusions"),
        ("claims", "timeline"),
        ("user_profiles", "lifestyle"),
        ("user_settings", "dashboard_config"),
        ("assets", "metadata"),
        ("audit_logs", "changes"),
    ]
    for table_name, col in jsonb_fields:
        column = Base.metadata.tables[table_name].columns[col]
        assert column.type.__class__.__name__ == "JSONB", f"{table_name}.{col}"
