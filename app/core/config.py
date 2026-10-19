"""Qura backend configuration.

All settings are Qura-owned and namespaced with the ``QURA_`` env prefix so that
nothing accidentally shares the reference backend's environment variable names.
Secrets are never logged or echoed; see ``app.core.logging`` for redaction and
``safe_summary`` below for a redaction-aware view of the configuration.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Any

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that must never be accepted as a real secret outside development.
_WEAK_SECRETS: frozenset[str] = frozenset(
    {
        "",
        "secret",
        "change-me",
        "changeme",
        "please-change-me",
        "qura-dev-secret-change-me",
    }
)

_MIN_SECRET_LENGTH = 32

# Env var names whose values must be redacted anywhere config is rendered.
_SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "session_secret",
        "database_url",
        "database_password",
    }
)


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QURA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime -----------------------------------------------------------
    environment: Environment = Environment.DEVELOPMENT
    app_name: str = "Qura Client Portal API"
    api_prefix: str = "/api/client"
    host: str = "0.0.0.0"
    port: int = 8787

    # --- Database ----------------------------------------------------------
    # A Qura-only PostgreSQL DSN. Phase 1 never connects at import time; the
    # engine is created lazily and only used by later phases. Kept optional so
    # the app can boot (and health endpoints work) before a DB is provisioned.
    database_url: str | None = Field(
        default=None,
        description="postgresql+asyncpg://user:pass@host:5432/qura_client",
    )
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_timeout_seconds: int = 30

    # --- Security ----------------------------------------------------------
    # Secret backing session token signing. Qura-owned and independent.
    session_secret: str = "qura-dev-secret-change-me"
    # Qura-specific cookie names the existing frontend already reads.
    session_cookie_name: str = "qura_client_session"
    csrf_cookie_name: str = "qura_client_csrf"
    # Session lifetime (also used as cookie max-age). Default 7 days.
    session_max_age_seconds: int = 7 * 24 * 60 * 60
    # Password-reset token time-to-live. Default 30 minutes.
    password_reset_ttl_seconds: int = 30 * 60

    # --- CORS --------------------------------------------------------------
    # Explicit allow-list only; no wildcard when credentials are enabled.
    cors_allow_origins: list[str] = Field(default_factory=list)
    cors_allow_credentials: bool = True

    # --- Logging -----------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Guard against pointing Qura at a non-async or non-Postgres DSN.
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "QURA_DATABASE_URL must use the postgresql+asyncpg:// driver"
            )
        return value

    @field_validator("session_secret")
    @classmethod
    def _reject_weak_secret(cls, value: str, info: ValidationInfo) -> str:
        env = info.data.get("environment", Environment.DEVELOPMENT)
        if env in (Environment.DEVELOPMENT, Environment.TEST):
            # Dev/test may use the default; it is never used to protect real data.
            return value
        if value.lower() in _WEAK_SECRETS or len(value) < _MIN_SECRET_LENGTH:
            raise ValueError(
                "QURA_SESSION_SECRET must be set to a strong value "
                f"(>= {_MIN_SECRET_LENGTH} chars, not a known default) outside development"
            )
        return value

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        # Accept a comma-separated string from the environment.
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    # --- Database-target guard --------------------------------------------
    # Migrations and the engine refuse any database whose name does not start
    # with this prefix, so Qura can never act on another project's database.
    database_name_prefix: str = "qura_"

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def docs_enabled(self) -> bool:
        # API docs are disabled in production.
        return self.environment != Environment.PRODUCTION

    def safe_summary(self) -> dict[str, Any]:
        """A redaction-aware view of configuration, safe to log at startup."""
        summary: dict[str, Any] = {}
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, Enum):
                value = value.value
            if name in _SENSITIVE_FIELDS and value:
                value = "***redacted***"
            summary[name] = value
        return summary


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor. Override in tests via dependency injection."""
    return Settings()
