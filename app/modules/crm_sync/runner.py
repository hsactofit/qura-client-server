"""Background loop that runs :func:`service.sync_once` every few seconds.

Started from the app lifespan only when ``crm_sync_interval_seconds > 0`` and a
database is configured. A single uvicorn worker runs one loop; if more workers
are ever added, a Postgres advisory lock keeps passes from overlapping.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy import text

from app.core.config import Settings
from app.db.session import get_sessionmaker
from app.modules.crm_sync import service

logger = logging.getLogger("qura.crm_sync")

# Arbitrary constant: "qura" in ASCII. Scopes the advisory lock to this loop.
_LOCK_KEY = 0x71757261


async def run_pass() -> service.SyncResult:
    maker = get_sessionmaker()
    async with maker() as session:
        got = await session.execute(
            text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _LOCK_KEY}
        )
        if not got.scalar_one():
            return service.SyncResult()
        result = await service.sync_once(session)
        await session.commit()
        return result


async def _loop(interval: int) -> None:
    logger.info("CRM sync started (every %ss)", interval)
    while True:
        try:
            result = await run_pass()
            if result.changed:
                logger.info(
                    "CRM sync applied",
                    extra={
                        "policies": result.policies,
                        "messages": result.messages,
                        "tickets": result.tickets,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive; retry next tick
            logger.exception("CRM sync pass failed")
        await asyncio.sleep(interval)


def start(settings: Settings) -> asyncio.Task[None] | None:
    if settings.crm_sync_interval_seconds <= 0 or not settings.database_url:
        return None
    return asyncio.create_task(_loop(settings.crm_sync_interval_seconds))


async def stop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
