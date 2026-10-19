"""Database-target safety guard.

Ensures Qura only ever connects to or migrates a dedicated Qura database. The
guard inspects the configured DSN *without* printing credentials and enforces:

1. The async ``postgresql+asyncpg://`` driver.
2. A database name beginning with the configured Qura prefix (default ``qura_``).

If the target cannot be verified the guard raises; callers must not fall back to
any other database or silently reuse an existing connection. This never contacts
the reference backend's database.
"""

from __future__ import annotations

from urllib.parse import urlsplit


class DatabaseTargetError(RuntimeError):
    """Raised when the configured database target cannot be verified as Qura."""


def extract_database_name(database_url: str) -> str:
    """Return the database name from a DSN, without exposing credentials."""
    path = urlsplit(database_url).path  # "/dbname"
    return path.lstrip("/")


def verify_database_target(database_url: str | None, *, name_prefix: str) -> str:
    """Validate a DSN as a dedicated Qura target. Returns the database name.

    Raises ``DatabaseTargetError`` with a credential-free message otherwise.
    """
    if not database_url:
        raise DatabaseTargetError(
            "No database configured (QURA_DATABASE_URL is unset). Refusing to "
            "connect; set a dedicated Qura database before running migrations."
        )
    if not database_url.startswith("postgresql+asyncpg://"):
        raise DatabaseTargetError(
            "QURA_DATABASE_URL must use the postgresql+asyncpg:// driver."
        )
    name = extract_database_name(database_url)
    if not name:
        raise DatabaseTargetError(
            "QURA_DATABASE_URL does not include a database name."
        )
    if not name.startswith(name_prefix):
        raise DatabaseTargetError(
            f"Refusing to use database {name!r}: a dedicated Qura database whose "
            f"name starts with {name_prefix!r} is required. "
            "This guard prevents acting on another project's database."
        )
    return name
