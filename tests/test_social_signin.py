"""Google / Apple sign-in (POST /api/client/auth/social).

Tokens are signed here with a throwaway RSA key standing in for Google's
securetoken keys, so every verification rule runs for real; only the key
download is replaced. Uses the in-memory FakeSession (no live database).
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from app.core import firebase_tokens
from app.core.passwords import hash_password
from app.db.models.identity import User, UserProfile
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.conftest import build_settings

PROJECT = "qura-test-project"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings():  # type: ignore[no-untyped-def]
    return build_settings(firebase_project_id=PROJECT)


@pytest.fixture(autouse=True)
def google_keys(monkeypatch):  # type: ignore[no-untyped-def]
    """Serve our test public key in place of Google's key set."""
    monkeypatch.setattr(
        firebase_tokens._jwks_client,
        "get_signing_key_from_jwt",
        lambda _token: SimpleNamespace(key=_KEY.public_key()),
    )


def _token(
    *,
    email: str = "new.person@gmail.com",
    verified: bool = True,
    provider: str = "google.com",
    aud: str = PROJECT,
    iss: str | None = None,
    exp_in: int = 3600,
    key=_KEY,  # type: ignore[no-untyped-def]
    name: str | None = "New Person",
    sub: str = "firebase-uid-1",
) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": iss or f"https://securetoken.google.com/{PROJECT}",
        "aud": aud,
        "auth_time": now - 5,
        "iat": now - 5,
        "exp": now + exp_in,
        "sub": sub,
        "email": email,
        "email_verified": verified,
        "firebase": {"sign_in_provider": provider, "identities": {}},
    }
    if name:
        claims["name"] = name
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


def _post(client, token: str, provider: str = "google", **extra):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/client/auth/social", json={"provider": provider, "idToken": token, **extra}
    )


def _seed(store, email: str, status: str = "ACTIVE", deleted: bool = False):  # type: ignore[no-untyped-def]
    user = User(
        email=email,
        password_hash=hash_password("Password123"),
        full_name="Existing",
        role="USER",
        status=status,
        is_deleted=deleted,
    )
    store.seed(user)
    store.seed(UserProfile(user_id=user.id))
    return user


def test_new_google_account_is_created_and_signed_in(db_client, store) -> None:
    resp = _post(db_client, _token())
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["created"] is True
    assert data["user"]["email"] == "new.person@gmail.com"
    assert data["user"]["full_name"] == "New Person"
    assert data["csrf_token"]
    joined = " ".join(resp.headers.get_list("set-cookie"))
    assert "qura_client_session=" in joined and "qura_client_csrf=" in joined
    # The new session works.
    assert db_client.get("/api/client/auth/session").status_code == 200
    user = next(u for u in store.data[User] if u.email == "new.person@gmail.com")
    assert user.role == "USER" and user.password_hash is None


def test_full_name_hint_is_used_for_new_accounts(db_client) -> None:
    resp = _post(db_client, _token(name=None), provider="google", fullName="Asha Rao")
    assert resp.json()["data"]["user"]["full_name"] == "Asha Rao"


def test_existing_email_account_signs_in_and_keeps_its_password(db_client, store) -> None:
    _seed(store, "asha@gmail.com")
    resp = _post(db_client, _token(email="Asha@Gmail.com"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["created"] is False
    assert resp.json()["data"]["user"]["full_name"] == "Existing"
    signin = db_client.post(
        "/api/client/auth/signin", json={"email": "asha@gmail.com", "password": "Password123"}
    )
    assert signin.status_code == 200


def test_unverified_email_is_refused(db_client, store) -> None:
    _seed(store, "victim@example.com")
    resp = _post(db_client, _token(email="victim@example.com", verified=False))
    assert resp.status_code == 401
    assert "set-cookie" not in resp.headers


@pytest.mark.parametrize(
    "status,deleted", [("INACTIVE", False), ("INVITED", False), ("ACTIVE", True)]
)
def test_inactive_or_deleted_account_is_refused(db_client, store, status, deleted) -> None:
    _seed(store, "gone@gmail.com", status=status, deleted=deleted)
    resp = _post(db_client, _token(email="gone@gmail.com"))
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: _token(aud="someone-elses-project"), id="wrong-audience"),
        pytest.param(lambda: _token(iss="https://securetoken.google.com/other"), id="wrong-issuer"),
        pytest.param(lambda: _token(exp_in=-3600), id="expired"),
        pytest.param(lambda: _token(key=_OTHER_KEY), id="forged-signature"),
        pytest.param(lambda: _token(provider="password"), id="firebase-email-password-token"),
        pytest.param(lambda: _token(provider="apple.com"), id="apple-token-sent-as-google"),
        pytest.param(lambda: _token(sub=""), id="empty-subject"),
        pytest.param(lambda: "not-a-token", id="garbage"),
    ],
)
def test_bad_tokens_are_refused(db_client, store, token) -> None:
    resp = _post(db_client, token())
    assert resp.status_code == 401
    assert resp.json()["message"] == "Sign-in could not be verified. Please try again."
    assert store.data[User] == []


def test_unsigned_token_is_refused(db_client) -> None:
    now = int(time.time())
    claims = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "sub": "x",
        "iat": now,
        "exp": now + 60,
        "auth_time": now,
        "email": "a@gmail.com",
        "email_verified": True,
        "firebase": {"sign_in_provider": "google.com"},
    }
    unsigned = jwt.encode(claims, None, algorithm="none")
    assert _post(db_client, unsigned).status_code == 401


def test_apple_tokens_work_with_provider_apple(db_client) -> None:
    resp = _post(
        db_client,
        _token(email="x1@privaterelay.appleid.com", provider="apple.com", name=None),
        provider="apple",
        fullName="Ravi K",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["user"]["full_name"] == "Ravi K"


def test_email_in_body_is_rejected(db_client) -> None:
    resp = _post(db_client, _token(), email="victim@example.com")
    assert resp.status_code == 422


def test_unknown_provider_is_rejected(db_client) -> None:
    assert _post(db_client, _token(), provider="facebook").status_code == 422


def test_not_configured_returns_503(db_client, db_app) -> None:
    from app.core.config import get_settings

    db_app.dependency_overrides[get_settings] = lambda: build_settings(firebase_project_id="")
    assert _post(db_client, _token()).status_code == 503


def test_key_download_failure_returns_503(db_client, monkeypatch) -> None:
    def _fail(_token):  # type: ignore[no-untyped-def]
        raise jwt.PyJWKClientConnectionError("offline")

    monkeypatch.setattr(firebase_tokens._jwks_client, "get_signing_key_from_jwt", _fail)
    assert _post(db_client, _token()).status_code == 503
