"""Default-deny authorization scaffolding."""

from __future__ import annotations

from app.core.errors import register_error_handlers
from app.core.security import (
    CurrentUser,
    require_authenticated,
    require_roles,
    resolve_current_user,
)
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def _protected_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/protected")
    async def protected(user: CurrentUser = Depends(require_authenticated)) -> dict:
        return {"success": True, "message": "ok", "data": {"id": user.id}}

    @app.get("/admin-only")
    async def admin_only(
        user: CurrentUser = Depends(require_roles("ADMIN")),
    ) -> dict:
        return {"success": True, "message": "ok", "data": {"id": user.id}}

    return app


def _override_user(app: FastAPI, user: CurrentUser | None) -> None:
    # Override the resolver directly so these guard tests never touch the DB.
    async def _resolver() -> CurrentUser | None:
        return user

    app.dependency_overrides[resolve_current_user] = _resolver


def test_protected_route_denies_by_default() -> None:
    # No session resolved -> 401 (default-deny).
    app = _protected_app()
    _override_user(app, None)
    with TestClient(app) as client:
        response = client.get("/protected")
        assert response.status_code == 401
        assert response.json()["success"] is False


def test_role_route_denies_by_default() -> None:
    app = _protected_app()
    _override_user(app, None)
    with TestClient(app) as client:
        assert client.get("/admin-only").status_code == 401


def test_protected_route_allows_when_user_resolved() -> None:
    app = _protected_app()
    _override_user(
        app, CurrentUser(id="u1", email="u1@quramail.io", role="USER", status="ACTIVE")
    )
    with TestClient(app) as client:
        assert client.get("/protected").status_code == 200
        # USER role is not ADMIN → 403 on the role-gated route.
        assert client.get("/admin-only").status_code == 403
