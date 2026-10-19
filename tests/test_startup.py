"""Application startup and wiring."""

from __future__ import annotations

from app.core.config import Environment
from app.main import create_app
from fastapi import FastAPI

from tests.conftest import build_settings


def test_app_boots_without_database() -> None:
    app = create_app(build_settings(database_url=None))
    assert isinstance(app, FastAPI)


def test_lifespan_runs(client) -> None:  # type: ignore[no-untyped-def]
    # TestClient context triggers startup/shutdown; a successful health call
    # proves the lifespan entered without a database.
    response = client.get("/api/client/health")
    assert response.status_code == 200


def test_docs_disabled_in_production() -> None:
    app = create_app(
        build_settings(
            environment=Environment.PRODUCTION,
            session_secret="x" * 40,
        )
    )
    with __import__("fastapi").testclient.TestClient(app) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404


def test_docs_enabled_outside_production(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/openapi.json").status_code == 200


def test_security_headers_present(client) -> None:  # type: ignore[no-untyped-def]
    headers = client.get("/api/client/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in headers
    assert "X-Request-Id" in headers
