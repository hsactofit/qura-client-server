"""Database-target guard: only a dedicated Qura database is accepted."""

from __future__ import annotations

import pytest
from app.db.guard import DatabaseTargetError, verify_database_target


def test_rejects_missing_url() -> None:
    with pytest.raises(DatabaseTargetError):
        verify_database_target(None, name_prefix="qura_")


def test_rejects_non_async_driver() -> None:
    with pytest.raises(DatabaseTargetError):
        verify_database_target(
            "postgresql://u:p@host:5432/qura_client", name_prefix="qura_"
        )


def test_rejects_non_qura_database_name() -> None:
    # e.g. accidentally pointing at another project's database.
    with pytest.raises(DatabaseTargetError):
        verify_database_target(
            "postgresql+asyncpg://u:p@host:5432/other_project_db",
            name_prefix="qura_",
        )


def test_accepts_dedicated_qura_database() -> None:
    name = verify_database_target(
        "postgresql+asyncpg://u:p@host:5432/qura_client", name_prefix="qura_"
    )
    assert name == "qura_client"


def test_error_message_does_not_leak_credentials() -> None:
    try:
        verify_database_target(
            "postgresql+asyncpg://user:supersecret@host:5432/other_db",
            name_prefix="qura_",
        )
    except DatabaseTargetError as exc:
        assert "supersecret" not in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected DatabaseTargetError")
