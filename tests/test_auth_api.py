"""Authentication API tests.

All tests use the in-memory FakeSession (labelled mock) — no live database. They
exercise the real routers, security dependencies, cookies, CSRF, and mapping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.passwords import hash_password
from app.core.tokens import hash_token
from app.db.models.identity import Invite, User, UserProfile


def _seed_user(store, email="user@quramail.io", password="Password123", role="USER",
               status="ACTIVE"):  # type: ignore[no-untyped-def]
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name="Test User",
        role=role,
        status=status,
    )
    store.seed(user)
    store.seed(UserProfile(user_id=user.id))
    return user


def _seed_invite(store, email, raw_token, role="USER", used=False, expired=False):  # type: ignore[no-untyped-def]
    expires = datetime.now(UTC) + (timedelta(days=-1) if expired else timedelta(days=7))
    invite = Invite(
        email=email,
        token_hash=hash_token(raw_token),
        role=role,
        is_used=used,
        expires_at=expires,
    )
    store.seed(invite)
    return invite


# --- signin ---------------------------------------------------------------


def test_signin_success_sets_cookies_and_returns_user(db_client, store) -> None:
    _seed_user(store, email="a@quramail.io", password="Password123")
    resp = db_client.post(
        "/api/client/auth/signin", json={"email": "a@quramail.io", "password": "Password123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["user"]["email"] == "a@quramail.io"
    assert body["data"]["csrf_token"]
    # Session + CSRF cookies set.
    cookies = resp.headers.get_list("set-cookie")
    joined = " ".join(cookies)
    assert "qura_client_session=" in joined
    assert "qura_client_csrf=" in joined
    assert "HttpOnly" in joined  # session cookie is HttpOnly


def test_signin_wrong_password_is_generic_401(db_client, store) -> None:
    _seed_user(store, email="a@quramail.io", password="Password123")
    resp = db_client.post(
        "/api/client/auth/signin", json={"email": "a@quramail.io", "password": "wrong"}
    )
    assert resp.status_code == 401
    assert resp.json()["message"] == "Invalid email or password"


def test_signin_unknown_email_is_generic_401(db_client, store) -> None:
    resp = db_client.post(
        "/api/client/auth/signin", json={"email": "nobody@quramail.io", "password": "whatever"}
    )
    assert resp.status_code == 401
    assert resp.json()["message"] == "Invalid email or password"


def test_signin_email_is_case_insensitive(db_client, store) -> None:
    _seed_user(store, email="a@quramail.io", password="Password123")
    resp = db_client.post(
        "/api/client/auth/signin", json={"email": "A@quramail.io", "password": "Password123"}
    )
    assert resp.status_code == 200


def test_signin_rejects_invalid_email_format(db_client, store) -> None:
    resp = db_client.post(
        "/api/client/auth/signin", json={"email": "not-an-email", "password": "x"}
    )
    assert resp.status_code == 422


# --- signup ---------------------------------------------------------------


def test_signup_requires_invite(db_client, store) -> None:
    resp = db_client.post(
        "/api/client/auth/signup",
        json={"email": "new@quramail.io", "password": "Password123", "fullName": "New"},
    )
    assert resp.status_code == 400


def test_signup_with_valid_invite_succeeds(db_client, store) -> None:
    _seed_invite(store, "new@quramail.io", "raw-invite-token")
    resp = db_client.post(
        "/api/client/auth/signup",
        json={
            "email": "new@quramail.io",
            "password": "Password123",
            "fullName": "New User",
            "inviteToken": "raw-invite-token",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["user"]["email"] == "new@quramail.io"
    assert "qura_client_session=" in " ".join(resp.headers.get_list("set-cookie"))


def test_signup_role_comes_from_invite_not_body(db_client, store) -> None:
    # Invite grants USER; body attempts ADMIN via an unexpected field.
    _seed_invite(store, "new@quramail.io", "raw-invite-token", role="USER")
    resp = db_client.post(
        "/api/client/auth/signup",
        json={
            "email": "new@quramail.io",
            "password": "Password123",
            "fullName": "New User",
            "inviteToken": "raw-invite-token",
            "role": "ADMIN",
        },
    )
    # extra="forbid" rejects the unknown 'role' field outright.
    assert resp.status_code == 422


def test_signup_short_password_rejected(db_client, store) -> None:
    _seed_invite(store, "new@quramail.io", "raw-invite-token")
    resp = db_client.post(
        "/api/client/auth/signup",
        json={
            "email": "new@quramail.io",
            "password": "short",
            "fullName": "New User",
            "inviteToken": "raw-invite-token",
        },
    )
    assert resp.status_code == 422


def test_signup_duplicate_email_conflicts(db_client, store) -> None:
    _seed_user(store, email="dupe@quramail.io", password="Password123")
    _seed_invite(store, "dupe@quramail.io", "raw-invite-token")
    resp = db_client.post(
        "/api/client/auth/signup",
        json={
            "email": "dupe@quramail.io",
            "password": "Password123",
            "fullName": "Dupe",
            "inviteToken": "raw-invite-token",
        },
    )
    assert resp.status_code == 409


def test_signup_invite_email_mismatch_rejected(db_client, store) -> None:
    _seed_invite(store, "invited@quramail.io", "raw-invite-token")
    resp = db_client.post(
        "/api/client/auth/signup",
        json={
            "email": "someone-else@quramail.io",
            "password": "Password123",
            "fullName": "X",
            "inviteToken": "raw-invite-token",
        },
    )
    assert resp.status_code == 400


# --- invite verify --------------------------------------------------------


def test_verify_invite_valid(db_client, store) -> None:
    _seed_invite(store, "i@quramail.io", "raw-invite-token")
    resp = db_client.post("/api/client/auth/invite/verify", json={"token": "raw-invite-token"})
    assert resp.status_code == 200
    assert resp.json()["data"] == {"valid": True, "email": "i@quramail.io"}


def test_verify_invite_expired(db_client, store) -> None:
    _seed_invite(store, "i@quramail.io", "raw-invite-token", expired=True)
    resp = db_client.post("/api/client/auth/invite/verify", json={"token": "raw-invite-token"})
    assert resp.status_code == 400


# --- password hashing -----------------------------------------------------


def test_password_is_hashed_not_plaintext(store) -> None:
    user = _seed_user(store, email="h@quramail.io", password="Password123")
    assert user.password_hash != "Password123"
    assert user.password_hash.startswith("$argon2id$")
