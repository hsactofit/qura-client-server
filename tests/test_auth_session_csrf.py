"""Session lifecycle, CSRF, logout, and forgot/reset tests (in-memory fake DB)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.passwords import hash_password, verify_password
from app.core.sessions import issue_session_token, parse_session_token
from app.core.tokens import hash_token
from app.db.models.identity import PasswordResetToken, User, UserProfile


def _seed_user(store, email="u@quramail.io", password="Password123", status="ACTIVE"):  # type: ignore[no-untyped-def]
    user = User(
        email=email, password_hash=hash_password(password), role="USER", status=status
    )
    store.seed(user, UserProfile(user_id=user.id))
    return user


def _signin(db_client, email, password="Password123"):  # type: ignore[no-untyped-def]
    return db_client.post(
        "/api/client/auth/signin", json={"email": email, "password": password}
    )


# --- session bootstrap ----------------------------------------------------


def test_session_bootstrap_requires_cookie(db_client) -> None:
    assert db_client.get("/api/client/auth/session").status_code == 401


def test_session_bootstrap_after_signin(db_client, store) -> None:
    _seed_user(store, email="s@quramail.io")
    _signin(db_client, "s@quramail.io")  # TestClient persists cookies
    resp = db_client.get("/api/client/auth/session")
    assert resp.status_code == 200
    assert resp.json()["data"]["user"]["email"] == "s@quramail.io"


def test_invalid_session_cookie_rejected(db_client, store) -> None:
    _seed_user(store, email="s@quramail.io")
    db_client.cookies.set("qura_client_session", "tampered.value.signature")
    assert db_client.get("/api/client/auth/session").status_code == 401


def test_expired_session_rejected(db_client, store, settings) -> None:
    user = _seed_user(store, email="s@quramail.io")
    # Issue a token dated well beyond the max age.
    old = int((datetime.now(UTC) - timedelta(days=999)).timestamp())
    token = issue_session_token(str(user.id), settings.session_secret, now=old)
    db_client.cookies.set("qura_client_session", token)
    assert db_client.get("/api/client/auth/session").status_code == 401


def test_session_for_inactive_user_rejected(db_client, store, settings) -> None:
    user = _seed_user(store, email="s@quramail.io", status="INACTIVE")
    token = issue_session_token(str(user.id), settings.session_secret)
    db_client.cookies.set("qura_client_session", token)
    assert db_client.get("/api/client/auth/session").status_code == 401


def test_session_revoked_after_token_invalidation(db_client, store, settings) -> None:
    user = _seed_user(store, email="s@quramail.io")
    # Session issued one hour ago.
    issued = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
    token = issue_session_token(str(user.id), settings.session_secret, now=issued)
    db_client.cookies.set("qura_client_session", token)
    # Invalidate everything as of now.
    user.token_invalidated_at = datetime.now(UTC)
    assert db_client.get("/api/client/auth/session").status_code == 401


# --- CSRF -----------------------------------------------------------------


def test_signout_requires_csrf(db_client, store) -> None:
    _seed_user(store, email="c@quramail.io")
    _signin(db_client, "c@quramail.io")
    # Drop the CSRF header by clearing the memory of it: send without header.
    # TestClient will still send cookies; omit X-CSRF-Token explicitly.
    resp = db_client.post("/api/client/auth/signout", headers={"X-CSRF-Token": ""})
    assert resp.status_code == 403
    assert "CSRF" in resp.json()["message"]


def test_signout_with_valid_csrf_succeeds(db_client, store) -> None:
    _seed_user(store, email="c@quramail.io")
    signin = _signin(db_client, "c@quramail.io")
    csrf = signin.json()["data"]["csrf_token"]
    resp = db_client.post("/api/client/auth/signout", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    # Cookies cleared on logout.
    joined = " ".join(resp.headers.get_list("set-cookie"))
    assert "qura_client_session=" in joined  # delete sets an empty value


def test_csrf_mismatch_rejected(db_client, store) -> None:
    _seed_user(store, email="c@quramail.io")
    _signin(db_client, "c@quramail.io")
    resp = db_client.post(
        "/api/client/auth/signout", headers={"X-CSRF-Token": "not-the-cookie-value"}
    )
    assert resp.status_code == 403


def test_csrf_missing_header_rejected(db_client, store) -> None:
    # Authenticated (session cookie present) mutating request with NO
    # X-CSRF-Token header at all must be rejected by the double-submit check.
    _seed_user(store, email="c@quramail.io")
    _signin(db_client, "c@quramail.io")
    resp = db_client.post("/api/client/auth/signout")
    assert resp.status_code == 403
    assert "CSRF" in resp.json()["message"]


def test_csrf_missing_cookie_rejected(db_client, store) -> None:
    # Session cookie present but the CSRF cookie removed: even a supplied header
    # cannot satisfy the double-submit check without the matching cookie.
    _seed_user(store, email="c@quramail.io")
    signin = _signin(db_client, "c@quramail.io")
    csrf = signin.json()["data"]["csrf_token"]
    db_client.cookies.delete("qura_client_csrf")
    resp = db_client.post(
        "/api/client/auth/signout", headers={"X-CSRF-Token": csrf}
    )
    assert resp.status_code == 403


# --- forgot / reset -------------------------------------------------------


def test_forgot_password_generic_for_unknown_account(db_client) -> None:
    resp = db_client.post(
        "/api/client/auth/forgot-password", json={"email": "ghost@quramail.io"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data == {"email": "ghost@quramail.io"}  # no debug_token (TEST env)


def test_forgot_password_generic_for_known_account(db_client, store) -> None:
    _seed_user(store, email="known@quramail.io")
    resp = db_client.post(
        "/api/client/auth/forgot-password", json={"email": "known@quramail.io"}
    )
    assert resp.status_code == 200
    # Same generic shape; no token leaked outside development.
    assert "debug_token" not in resp.json()["data"]


def test_reset_password_consumes_token_and_changes_password(db_client, store) -> None:
    user = _seed_user(store, email="r@quramail.io", password="OldPassword1")
    raw = "raw-reset-token"
    store.seed(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    resp = db_client.post(
        "/api/client/auth/reset-password",
        json={"email": "r@quramail.io", "token": raw, "newPassword": "BrandNew123"},
    )
    assert resp.status_code == 200
    assert verify_password(user.password_hash, "BrandNew123")
    # Token is now consumed -> reuse fails.
    resp2 = db_client.post(
        "/api/client/auth/reset-password",
        json={"email": "r@quramail.io", "token": raw, "newPassword": "Another123"},
    )
    assert resp2.status_code == 400


def test_reset_password_rejects_expired_token(db_client, store) -> None:
    user = _seed_user(store, email="r@quramail.io")
    raw = "raw-reset-token"
    store.seed(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    resp = db_client.post(
        "/api/client/auth/reset-password",
        json={"email": "r@quramail.io", "token": raw, "newPassword": "BrandNew123"},
    )
    assert resp.status_code == 400


def test_reset_password_rejects_invalid_token(db_client, store) -> None:
    _seed_user(store, email="r@quramail.io")
    resp = db_client.post(
        "/api/client/auth/reset-password",
        json={"email": "r@quramail.io", "token": "bogus", "newPassword": "BrandNew123"},
    )
    assert resp.status_code == 400


def test_session_token_signature_is_tamper_evident(settings) -> None:
    token = issue_session_token("user-1", settings.session_secret)
    assert parse_session_token(token, settings.session_secret) is not None
    assert parse_session_token(token, "a-different-secret") is None
    assert parse_session_token(token + "x", settings.session_secret) is None
