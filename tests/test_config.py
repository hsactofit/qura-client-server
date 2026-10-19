"""Configuration validation and secret safety."""

from __future__ import annotations

import pytest
from app.core.config import Environment, Settings
from pydantic import ValidationError

from tests.conftest import build_settings


def test_weak_secret_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment=Environment.PRODUCTION,
            session_secret="secret",
        )


def test_short_secret_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment=Environment.PRODUCTION,
            session_secret="too-short",
        )


def test_strong_secret_accepted_in_production() -> None:
    settings = Settings(
        environment=Environment.PRODUCTION,
        session_secret="x" * 40,
    )
    assert settings.is_production is True
    assert settings.docs_enabled is False


def test_dev_allows_default_secret() -> None:
    settings = build_settings(environment=Environment.DEVELOPMENT)
    assert settings.session_secret  # default permitted in dev


def test_non_async_database_url_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql://user:pass@localhost/qura")


def test_async_database_url_accepted() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/qura_client"
    )
    assert settings.database_url is not None


def test_cors_origins_split_from_csv() -> None:
    settings = build_settings(cors_allow_origins="https://a.test, https://b.test")
    assert settings.cors_allow_origins == ["https://a.test", "https://b.test"]


def test_safe_summary_redacts_sensitive_fields() -> None:
    settings = Settings(
        environment=Environment.PRODUCTION,
        session_secret="x" * 40,
        database_url="postgresql+asyncpg://user:pass@localhost:5432/qura_client",
    )
    summary = settings.safe_summary()
    assert summary["session_secret"] == "***redacted***"
    assert summary["database_url"] == "***redacted***"
    # Non-sensitive values remain visible.
    assert summary["app_name"] == settings.app_name
