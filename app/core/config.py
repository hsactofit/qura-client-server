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
        "openai_api_key",
        "internal_token",
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

    # --- Document storage (private, Qura-owned) ----------------------------
    # Uploaded policy/claim documents are written under this directory and are
    # NEVER served from a public path. Downloads go through an authenticated,
    # ownership-checked endpoint that streams the bytes. ``storage_key`` in
    # ``stored_files`` is a path relative to this root; the download layer
    # resolves it and refuses anything escaping the root (path-traversal guard).
    storage_dir: str = Field(
        default="var/storage",
        description="Private filesystem root for uploaded documents.",
    )
    # Hard cap for a single uploaded document (bytes). Default 15 MB, matching
    # the frontend's client-side limit.
    upload_max_bytes: int = 15 * 1024 * 1024

    # --- AI policy extraction (OpenAI-compatible) --------------------------
    # Extraction is OPTIONAL. When no API key is configured, the extract/upload
    # endpoints report extraction as unavailable instead of inventing data;
    # upload still persists the user-provided fields. All values are Qura-owned
    # and independent of the reference backend's variable names.
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model_name: str = "gpt-4.1"
    # Upper bound on how long an extraction HTTP call may take (seconds).
    openai_timeout_seconds: int = 60

    # --- CRM link (shared qura_main database) -------------------------------
    # The CRM owns the ``crm`` schema next to this service's ``client`` schema.
    # A background loop pulls advisor work (policies, replies, request status)
    # into the portal every N seconds; 0 disables it (tests, local runs without
    # a CRM). Advisor-uploaded files are fetched from the CRM's internal
    # endpoint with a shared token over the private Docker network.
    crm_sync_interval_seconds: int = 0
    crm_internal_url: str = ""
    internal_token: str = ""

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
