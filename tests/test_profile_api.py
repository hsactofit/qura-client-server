"""Profile and settings API tests (in-memory fake DB)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.passwords import hash_password
from app.db.models.identity import User, UserProfile


def _seed_user(store, email="p@quramail.io", password="Password123"):  # type: ignore[no-untyped-def]
    user = User(
        email=email, password_hash=hash_password(password), full_name="P", role="USER",
        status="ACTIVE",
    )
    store.seed(user)
    return user


def _signin(db_client, email, password="Password123"):  # type: ignore[no-untyped-def]
    r = db_client.post(
        "/api/client/auth/signin", json={"email": email, "password": password}
    )
    return r.json()["data"]["csrf_token"]


def test_profile_requires_auth(db_client) -> None:
    assert db_client.get("/api/client/user/profile").status_code == 401


def test_get_profile_maps_pii_fields(db_client, store) -> None:
    user = _seed_user(store, email="p@quramail.io")
    store.seed(
        UserProfile(
            user_id=user.id,
            date_of_birth=date(1990, 5, 1),
            pan_number="ABCDE1234F",
            aadhaar_number="123456789012",
            annual_income=Decimal("1800000.00"),
            occupation="Engineer",
            lifestyle={"smoker": False, "alcohol": False, "exercise": "Weekly"},
        )
    )
    _signin(db_client, "p@quramail.io")
    resp = db_client.get("/api/client/user/profile")
    assert resp.status_code == 200
    data = resp.json()["data"]
    # PII at the top level as the frontend expects.
    assert data["date_of_birth"] == "1990-05-01"
    assert data["pan_number"] == "ABCDE1234F"
    assert data["aadhaar_number"] == "123456789012"
    # Soft fields under preferences.
    assert data["preferences"]["annualIncome"] == "1800000.00"
    assert data["preferences"]["occupation"] == "Engineer"
    assert data["preferences"]["lifestyle"]["exercise"] == "Weekly"
    # Secrets never exposed.
    assert "password_hash" not in data
    assert "token_invalidated_at" not in data


def test_update_profile_persists_and_maps_back(db_client, store) -> None:
    user = _seed_user(store, email="p@quramail.io")
    store.seed(UserProfile(user_id=user.id))
    csrf = _signin(db_client, "p@quramail.io")
    resp = db_client.put(
        "/api/client/user/profile/update",
        headers={"X-CSRF-Token": csrf},
        json={
            "full_name": "Updated Name",
            "phone": "9999999999",
            "date_of_birth": "1985-03-02",
            "pan_number": "ZYXWV9876E",
            "aadhaar_number": "999988887777",
            "annualIncome": 2500000,
            "occupation": "Doctor",
            "lifestyle": {"smoker": True, "alcohol": False, "exercise": "Daily"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["full_name"] == "Updated Name"
    assert data["date_of_birth"] == "1985-03-02"
    assert data["pan_number"] == "ZYXWV9876E"
    assert data["preferences"]["occupation"] == "Doctor"


def test_update_profile_requires_csrf(db_client, store) -> None:
    _seed_user(store, email="p@quramail.io")
    _signin(db_client, "p@quramail.io")
    resp = db_client.put(
        "/api/client/user/profile/update",
        headers={"X-CSRF-Token": ""},
        json={"full_name": "No CSRF"},
    )
    assert resp.status_code == 403


def test_update_profile_rejects_protected_fields(db_client, store) -> None:
    _seed_user(store, email="p@quramail.io")
    csrf = _signin(db_client, "p@quramail.io")
    # Attempt to escalate role / change status / flip ownership.
    resp = db_client.put(
        "/api/client/user/profile/update",
        headers={"X-CSRF-Token": csrf},
        json={"full_name": "X", "role": "ADMIN", "status": "ACTIVE", "is_deleted": False},
    )
    assert resp.status_code == 422  # extra="forbid" blocks unknown keys


def test_update_profile_cannot_change_role_in_db(db_client, store) -> None:
    user = _seed_user(store, email="p@quramail.io")
    store.seed(UserProfile(user_id=user.id))
    csrf = _signin(db_client, "p@quramail.io")
    db_client.put(
        "/api/client/user/profile/update",
        headers={"X-CSRF-Token": csrf},
        json={"full_name": "Legit Update"},
    )
    assert user.role == "USER"  # unchanged
    assert user.status == "ACTIVE"


def test_user_cannot_read_another_users_profile(db_client, store) -> None:
    # Two users; signing in as A must only ever return A's data. Identity comes
    # from the session, so there is no user-id input to tamper with.
    a = _seed_user(store, email="a@quramail.io")
    b = _seed_user(store, email="b@quramail.io")
    store.seed(UserProfile(user_id=a.id, occupation="A-job"))
    store.seed(UserProfile(user_id=b.id, occupation="B-job"))
    _signin(db_client, "a@quramail.io")
    data = db_client.get("/api/client/user/profile").json()["data"]
    assert data["email"] == "a@quramail.io"
    assert data["preferences"].get("occupation") == "A-job"


def test_settings_get_and_update(db_client, store) -> None:
    _seed_user(store, email="p@quramail.io")
    csrf = _signin(db_client, "p@quramail.io")
    # Defaults on first read.
    got = db_client.get("/api/client/user/settings").json()["data"]
    assert got["theme"] == "system"
    # Update.
    resp = db_client.put(
        "/api/client/user/settings",
        headers={"X-CSRF-Token": csrf},
        json={"theme": "dark", "notifications": False, "dashboard_config": {"layout": "grid"}},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["theme"] == "dark"
    assert data["notifications"] is False
    assert data["dashboard_config"] == {"layout": "grid"}
