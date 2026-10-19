"""Alembic environment for the Qura client backend.

- Uses the Qura SQLAlchemy metadata (``app.db.base.Base`` with every model
  imported via ``app.db.models``) as the single autogenerate target.
- Reads the database URL from Qura settings (``QURA_DATABASE_URL``), never from
  ``alembic.ini``, and verifies it with the Qura database-target guard before
  connecting. It never falls back to another database.
- Runs migrations through the async engine (asyncpg).

This is the sole schema authority. Nothing here runs at FastAPI startup.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

# Import the models package so every table registers on Base.metadata.
import app.db.models  # noqa: F401
from alembic import context
from app.core.config import get_settings
from app.db.base import Base
from app.db.guard import verify_database_target
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    settings = get_settings()
    # Verify before use; raises if the target is not a dedicated Qura database.
    verify_database_target(
        settings.database_url, name_prefix=settings.database_name_prefix
    )
    assert settings.database_url is not None
    return settings.database_url


def run_migrations_offline() -> None:
    """Generate SQL without a DB connection (still guards the target name)."""
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
