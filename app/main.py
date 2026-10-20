"""Qura backend application factory and entry point.

Mounts health, authentication, and profile routers under the API prefix. The app
still boots without a database connection; database-backed routes require a
configured Qura PostgreSQL instance at request time.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from app.db.session import dispose_engine

logger = logging.getLogger("qura.app")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info("Starting %s", settings.app_name, extra={"config": settings.safe_summary()})
    try:
        yield
    finally:
        # Dispose the engine if any phase created it. Safe when never used.
        await dispose_engine()
        logger.info("Shutdown complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=_lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings

    # Ensure dependency-injected settings are the exact instance this app was
    # built with (not the process-wide cached default), so per-app config —
    # including tests' isolated Settings — is authoritative everywhere.
    app.dependency_overrides[get_settings] = lambda: settings

    # --- Middleware (outermost added last) ---------------------------------
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)

    # --- Error handlers ----------------------------------------------------
    register_error_handlers(app)

    # --- Routers -----------------------------------------------------------
    # Everything is mounted under the API prefix so the frontend's same-origin
    # /api/client/* routing reaches it.
    from app.api.health import router as health_router
    from app.modules.assets.router import router as assets_router
    from app.modules.auth.router import router as auth_router
    from app.modules.claims.router import router as claims_router
    from app.modules.dashboard.router import router as dashboard_router
    from app.modules.family.router import router as family_router
    from app.modules.notifications.router import router as notifications_router
    from app.modules.policies.router import router as policies_router
    from app.modules.profile.router import router as profile_router
    from app.modules.reference.router import router as reference_router
    from app.modules.rm.router import router as rm_router
    from app.modules.support.router import router as support_router
    from app.modules.transactions.router import router as transactions_router

    api = settings.api_prefix
    app.include_router(health_router, prefix=api)
    app.include_router(auth_router, prefix=api)
    app.include_router(profile_router, prefix=api)
    app.include_router(dashboard_router, prefix=api)
    app.include_router(policies_router, prefix=api)
    app.include_router(assets_router, prefix=api)
    app.include_router(family_router, prefix=api)
    app.include_router(claims_router, prefix=api)
    app.include_router(transactions_router, prefix=api)
    app.include_router(notifications_router, prefix=api)
    app.include_router(support_router, prefix=api)
    app.include_router(reference_router, prefix=api)
    app.include_router(rm_router, prefix=api)

    return app


# Module-level app for `uvicorn app.main:app`.
app = create_app()
