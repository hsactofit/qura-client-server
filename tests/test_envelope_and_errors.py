"""Response envelope and centralised error handling."""

from __future__ import annotations

from app.core.envelope import error, success
from app.core.errors import ApiError, register_error_handlers
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_success_envelope_shape() -> None:
    env = success({"a": 1}, "done")
    assert env == {"success": True, "message": "done", "data": {"a": 1}}


def test_error_envelope_shape() -> None:
    env = error("nope", {"field": "x"})
    assert env == {"success": False, "message": "nope", "error": {"field": "x"}}


def _app_with_failing_routes() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom-api")
    async def boom_api() -> dict:
        raise ApiError("bad input", status_code=400, detail={"why": "test"})

    @app.get("/boom-unhandled")
    async def boom_unhandled() -> dict:
        raise RuntimeError("secret internal detail")

    return app


def test_api_error_renders_envelope() -> None:
    with TestClient(_app_with_failing_routes()) as client:
        response = client.get("/boom-api")
        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert body["message"] == "bad input"
        assert body["error"] == {"why": "test"}


def test_unhandled_error_is_generic() -> None:
    # raise_server_exceptions=False so the handler runs instead of re-raising.
    client = TestClient(_app_with_failing_routes(), raise_server_exceptions=False)
    response = client.get("/boom-unhandled")
    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["message"] == "Internal server error"
    # The internal message must not leak.
    assert "secret internal detail" not in response.text
