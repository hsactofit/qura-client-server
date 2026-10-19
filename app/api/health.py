"""Health and readiness endpoints.

- ``/health``        liveness: the process is up. Never touches the database.
- ``/health/ready``  readiness: verifies the DB is reachable when configured.

Both return the standard envelope. Readiness degrades to 503 if a database URL
is configured but a ``SELECT 1`` fails. When no database is configured (valid in
Phase 1), readiness reports ``database: "not_configured"`` and still returns 200
so the service can run before a DB is provisioned.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.core.envelope import success
from app.db.session import get_sessionmaker

logger = logging.getLogger("qura.health")

router = APIRouter(tags=["health"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


@router.get("/health")
async def health() -> dict:
    return success({"status": "healthy", "timestamp": _now()}, "OK")


@router.get("/health/ready")
async def ready(response: Response) -> dict:
    settings = get_settings()
    if settings.database_url is None:
        return success(
            {"status": "ready", "database": "not_configured", "timestamp": _now()},
            "Ready (no database configured)",
        )

    try:
        maker = get_sessionmaker()
        async with maker() as session:
            await session.execute(text("SELECT 1"))
        return success(
            {"status": "ready", "database": "connected", "timestamp": _now()},
            "Ready",
        )
    except Exception:
        logger.warning("Readiness check failed: database unreachable")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "success": False,
            "message": "Service not ready",
            "error": {"database": "unavailable", "timestamp": _now()},
        }
