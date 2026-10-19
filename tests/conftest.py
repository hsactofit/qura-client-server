"""Shared pytest fixtures.

Each test builds the app from an explicit ``Settings`` so no real ``.env`` or
environment variables leak in. No database is contacted.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.core.config import Environment, Settings
from app.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient


def build_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "environment": Environment.TEST,
        "database_url": None,
        "session_secret": "qura-dev-secret-change-me",
        "cors_allow_origins": [],
        "log_json": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def settings() -> Settings:
    return build_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


# --- Database-backed route fixtures (in-memory fake, no live DB) -----------


@pytest.fixture
def store():  # type: ignore[no-untyped-def]
    from tests.fakes import FakeStore

    return FakeStore()


@pytest.fixture
def db_app(settings: Settings, store):  # type: ignore[no-untyped-def]
    """App whose ``get_session`` dependency yields the in-memory FakeSession."""
    from app.db.session import get_session

    from tests.fakes import FakeSession

    application = create_app(settings)

    async def _override_get_session():  # type: ignore[no-untyped-def]
        yield FakeSession(store)

    application.dependency_overrides[get_session] = _override_get_session
    return application


@pytest.fixture
def db_client(db_app) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    with TestClient(db_app) as test_client:
        yield test_client
