"""Mobile-number sign-in (POST /auth/phone) and number verification
(POST /user/phone/verify) with Firebase Phone Auth ID tokens.

Firebase sends and checks the SMS code; the server only verifies the resulting
token. Tokens are signed here with a throwaway RSA key standing in for Google's
securetoken keys, so every verification rule runs for real. Uses the in-memory
FakeSession (no live database).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
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
NUMBER = "+919876543210"


@pytest.fixture
def settings():  # type: ignore[no-untyped-def]
    return build_settings(firebase_project_id=PROJECT)


@pytest.fixture(autouse=True)
def google_keys(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        firebase_tokens._jwks_client,
        "get_signing_key_from_jwt",
        lambda _token: SimpleNamespace(key=_KEY.public_key()),
    )


def _token(
    *,
    phone: str | None = NUMBER,
    provider: str = "phone",
    aud: str = PROJECT,
    exp_in: int = 3600,
    key=_KEY,  # type: ignore[no-untyped-def]
    email: str | None = None,
) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": aud,
        "auth_time": now - 5,
        "iat": now - 5,
        "exp": now + exp_in,
        "sub": "firebase-phone-uid",
        "firebase": {"sign_in_provider": provider, "identities": {}},
    }
    if phone is not None:
        claims["phone_number"] = phone
    if email is not None:
        claims["email"] = email
        claims["email_verified"] = True
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


def _seed(  # type: ignore[no-untyped-def]
    store,
    email: str = "asha@example.com",
    phone: str | None = NUMBER,
    verified: bool = True,
    status: str = "ACTIVE",
    deleted: bool = False,
):
    user = User(
        email=email,
        password_hash=hash_password("Password123"),
        full_name="Asha",
        phone=phone,
        phone_verified_at=datetime.now(UTC) if verified else None,
        role="USER",
        status=status,
        is_deleted=deleted,
    )
    store.seed(user)
    store.seed(UserProfile(user_id=user.id))
    return user


def _phone_signin(client, token: str, **extra):  # type: ignore[no-untyped-def]
    return client.post("/api/client/auth/phone", json={"idToken": token, **extra})


def _email_signin(client, email: str = "asha@example.com") -> str:  # type: ignore[no-untyped-def]
    r = client.post("/api/client/auth/signin", json={"email": email, "password": "Password123"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["csrf_token"]


def _verify(client, csrf: str, token: str):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/client/user/phone/verify",
        headers={"X-CSRF-Token": csrf},
        json={"idToken": token},
    )


# --- Sign-in -----------------------------------------------------------------


def test_verified_number_signs_in(db_client, store) -> None:
    _seed(store)
    resp = _phone_signin(db_client, _token())
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["user"]["email"] == "asha@example.com"
    assert data["user"]["phone"] == NUMBER
    assert data["user"]["phone_verified"] is True
    assert data["csrf_token"]
    joined = " ".join(resp.headers.get_list("set-cookie"))
    assert "qura_client_session=" in joined and "qura_client_csrf=" in joined
    assert db_client.get("/api/client/auth/session").status_code == 200


def test_number_only_typed_in_cannot_sign_in(db_client, store) -> None:
    """A mistyped number must not let that number's real owner into the account."""
    _seed(store, verified=False)
    resp = _phone_signin(db_client, _token())
    assert resp.status_code == 404
    assert "verify your number" in resp.json()["message"]
    assert "set-cookie" not in resp.headers


def test_unknown_number_is_not_signed_up(db_client, store) -> None:
    resp = _phone_signin(db_client, _token(phone="+919000000001"))
    assert resp.status_code == 404
    assert store.data[User] == []


@pytest.mark.parametrize(
    "status,deleted", [("INACTIVE", False), ("INVITED", False), ("ACTIVE", True)]
)
def test_inactive_or_deleted_account_is_refused(db_client, store, status, deleted) -> None:
    _seed(store, status=status, deleted=deleted)
    assert _phone_signin(db_client, _token()).status_code == 403


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: _token(aud="someone-elses-project"), id="wrong-audience"),
        pytest.param(lambda: _token(exp_in=-3600), id="expired"),
        pytest.param(lambda: _token(key=_OTHER_KEY), id="forged-signature"),
        pytest.param(
            lambda: _token(provider="google.com", phone=None, email="a@gmail.com"),
            id="google-token-sent-as-phone",
        ),
        pytest.param(lambda: _token(phone=None), id="no-phone-number"),
        pytest.param(lambda: _token(phone="9876543210"), id="not-e164"),
        pytest.param(lambda: "not-a-token", id="garbage"),
    ],
)
def test_bad_tokens_are_refused(db_client, store, token) -> None:
    _seed(store)
    resp = _phone_signin(db_client, token())
    assert resp.status_code == 401
    assert resp.json()["message"] == "Sign-in could not be verified. Please try again."


def test_phone_token_cannot_be_used_for_google_sign_in(db_client, store) -> None:
    _seed(store)
    resp = db_client.post(
        "/api/client/auth/social", json={"provider": "google", "idToken": _token()}
    )
    assert resp.status_code == 401


def test_number_in_body_is_rejected(db_client, store) -> None:
    _seed(store)
    assert _phone_signin(db_client, _token(), phone="+919000000001").status_code == 422


def test_foreign_number_gets_a_plain_message(db_client) -> None:
    resp = _phone_signin(db_client, _token(phone="+14155550100"))
    assert resp.status_code == 422
    assert resp.json()["message"] == "Please use an Indian mobile number."


def test_not_configured_returns_503(db_client, db_app) -> None:
    from app.core.config import get_settings

    db_app.dependency_overrides[get_settings] = lambda: build_settings(firebase_project_id="")
    resp = _phone_signin(db_client, _token())
    assert resp.status_code == 503
    assert resp.json()["message"] == "Mobile number sign-in isn't available yet."


# --- Verifying a number --------------------------------------------------------


def test_verify_sets_the_number_and_then_it_signs_in(db_client, store) -> None:
    user = _seed(store, phone="+919000000009", verified=False)
    csrf = _email_signin(db_client)
    resp = _verify(db_client, csrf, _token())
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["phone"] == NUMBER and data["phone_verified"] is True
    assert user.phone == NUMBER and user.phone_verified_at is not None

    db_client.cookies.clear()
    assert _phone_signin(db_client, _token()).status_code == 200


def test_verify_needs_sign_in_and_csrf(db_client, store) -> None:
    _seed(store, verified=False)
    assert _verify(db_client, "x", _token()).status_code in (401, 403)
    _email_signin(db_client)
    assert _verify(db_client, "", _token()).status_code == 403


def test_number_verified_by_another_account_stays_there(db_client, store) -> None:
    _seed(store, email="owner@example.com", phone=NUMBER, verified=True)
    me = _seed(store, email="asha@example.com", phone=None, verified=False)
    csrf = _email_signin(db_client)
    resp = _verify(db_client, csrf, _token())
    assert resp.status_code == 409
    assert me.phone is None


def test_proof_beats_a_number_another_account_only_typed_in(db_client, store) -> None:
    other = _seed(store, email="typo@example.com", phone=NUMBER, verified=False)
    me = _seed(store, email="asha@example.com", phone=None, verified=False)
    csrf = _email_signin(db_client)
    assert _verify(db_client, csrf, _token()).status_code == 200
    assert other.phone is None
    assert me.phone == NUMBER and me.phone_verified_at is not None


def test_verify_rejects_a_google_token(db_client, store) -> None:
    _seed(store, verified=False)
    csrf = _email_signin(db_client)
    token = _token(provider="google.com", phone=None, email="asha@example.com")
    assert _verify(db_client, csrf, token).status_code == 401


# --- Profile updates -----------------------------------------------------------


def test_changing_the_number_in_the_profile_clears_verification(db_client, store) -> None:
    user = _seed(store)
    csrf = _email_signin(db_client)
    resp = db_client.put(
        "/api/client/user/profile/update",
        headers={"X-CSRF-Token": csrf},
        json={"phone": "98765 00000"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["phone"] == "+919876500000"
    assert resp.json()["data"]["phone_verified"] is False
    assert user.phone_verified_at is None


def test_saving_the_same_number_keeps_verification(db_client, store) -> None:
    user = _seed(store)
    csrf = _email_signin(db_client)
    resp = db_client.put(
        "/api/client/user/profile/update",
        headers={"X-CSRF-Token": csrf},
        json={"phone": "9876543210"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["phone_verified"] is True
    assert user.phone_verified_at is not None


def test_profile_cannot_take_another_accounts_number(db_client, store) -> None:
    _seed(store, email="owner@example.com", phone=NUMBER, verified=True)
    _seed(store, email="asha@example.com", phone=None, verified=False)
    csrf = _email_signin(db_client)
    resp = db_client.put(
        "/api/client/user/profile/update",
        headers={"X-CSRF-Token": csrf},
        json={"phone": NUMBER},
    )
    assert resp.status_code == 409
