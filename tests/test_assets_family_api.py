"""Assets and family-member API tests (in-memory fake DB)."""

from __future__ import annotations

from app.db.models.assets import Asset
from app.db.models.family import FamilyMember

from tests.phase4_helpers import seed_user, signin

# --- assets ---------------------------------------------------------------


def test_assets_requires_auth(db_client) -> None:
    assert db_client.get("/api/client/assets").status_code == 401


def test_create_and_list_asset(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.post(
        "/api/client/assets",
        headers={"X-CSRF-Token": csrf},
        json={"asset_type": "car", "name": "My Car", "registration_no": "MH12AB1234"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["asset_type"] == "car"
    listed = db_client.get("/api/client/assets").json()["data"]
    assert len(listed) == 1


def test_create_asset_requires_csrf(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    signin(db_client, "a@quramail.io")
    resp = db_client.post(
        "/api/client/assets", headers={"X-CSRF-Token": ""}, json={"asset_type": "car"}
    )
    assert resp.status_code == 403


def test_create_asset_invalid_type_rejected(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.post(
        "/api/client/assets",
        headers={"X-CSRF-Token": csrf},
        json={"asset_type": "spaceship"},
    )
    assert resp.status_code == 422


def test_update_other_users_asset_is_404(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    b = seed_user(store, "b@quramail.io")
    asset_b = Asset(user_id=b.id, asset_type="car", name="B car")
    store.seed(asset_b)
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.put(
        f"/api/client/assets/{asset_b.id}",
        headers={"X-CSRF-Token": csrf},
        json={"asset_type": "car", "name": "hijack"},
    )
    assert resp.status_code == 404
    assert asset_b.name == "B car"  # untouched


def test_delete_own_asset(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    asset = Asset(user_id=a.id, asset_type="home", name="Flat")
    store.seed(asset)
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.delete(
        f"/api/client/assets/{asset.id}", headers={"X-CSRF-Token": csrf}
    )
    assert resp.status_code == 200
    assert db_client.get("/api/client/assets").json()["data"] == []


# --- family ---------------------------------------------------------------


def test_family_requires_auth(db_client) -> None:
    assert db_client.get("/api/client/family").status_code == 401


def test_create_and_list_family(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.post(
        "/api/client/family",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Spouse", "relationship": "SPOUSE", "dob": "1990-01-01"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["name"] == "Spouse"
    assert body["relationship"] == "SPOUSE"  # model attr `relation` mapped back
    listed = db_client.get("/api/client/family").json()["data"]
    assert len(listed) == 1


def test_family_cross_user_update_is_404(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    b = seed_user(store, "b@quramail.io")
    member_b = FamilyMember(user_id=b.id, name="B kid", relation="CHILD")
    store.seed(member_b)
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.put(
        f"/api/client/family/{member_b.id}",
        headers={"X-CSRF-Token": csrf},
        json={"name": "hijack"},
    )
    assert resp.status_code == 404
    assert member_b.name == "B kid"


def test_family_invalid_dob_rejected(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.post(
        "/api/client/family",
        headers={"X-CSRF-Token": csrf},
        json={"name": "X", "dob": "not-a-date"},
    )
    assert resp.status_code == 400
