"""Shared helpers for Phase 4 API tests (in-memory fake DB)."""

from __future__ import annotations

from app.core.passwords import hash_password
from app.db.models.identity import User, UserProfile


def seed_user(store, email, password="Password123", role="USER"):  # type: ignore[no-untyped-def]
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name="Test User",
        role=role,
        status="ACTIVE",
    )
    store.seed(user, UserProfile(user_id=user.id))
    return user


def signin(db_client, email, password="Password123"):  # type: ignore[no-untyped-def]
    resp = db_client.post(
        "/api/client/auth/signin", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["csrf_token"]


def signout_client(db_client):  # type: ignore[no-untyped-def]
    db_client.cookies.clear()
