"""Policy API tests (in-memory fake DB)."""

from __future__ import annotations

from decimal import Decimal

from app.db.models.policies import Policy

from tests.phase4_helpers import seed_user, signin


def _seed_policy(store, user, **kw):  # type: ignore[no-untyped-def]
    defaults = {
        "user_id": user.id,
        "policy_number": "POL-1",
        "policy_type": "health",
        "insurer_name": "Acme",
        "coverage_amount": Decimal("1000000"),
        "premium_amount": Decimal("12000"),
        "status": "active",
        "benefits": [],
        "exclusions": [],
        "policy_source": "uploaded",
    }
    defaults.update(kw)
    policy = Policy(**defaults)
    store.seed(policy)
    return policy


def test_policies_requires_auth(db_client) -> None:
    assert db_client.get("/api/client/policies").status_code == 401


def test_list_policies_returns_only_own(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    b = seed_user(store, "b@quramail.io")
    _seed_policy(store, a, policy_number="A-1")
    _seed_policy(store, b, policy_number="B-1")
    signin(db_client, "a@quramail.io")
    data = db_client.get("/api/client/policies").json()["data"]
    assert len(data) == 1
    assert data[0]["policy_number"] == "A-1"
    assert data[0]["name"] == "health"  # derived display name


def test_list_policies_status_filter(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    _seed_policy(store, a, policy_number="A-active", status="active")
    _seed_policy(store, a, policy_number="A-expired", status="expired")
    signin(db_client, "a@quramail.io")
    data = db_client.get("/api/client/policies?status=active").json()["data"]
    assert [p["policy_number"] for p in data] == ["A-active"]


def test_get_policy_owned(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    p = _seed_policy(store, a)
    signin(db_client, "a@quramail.io")
    resp = db_client.get(f"/api/client/policies/{p.id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == str(p.id)


def test_get_other_users_policy_is_404(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    b = seed_user(store, "b@quramail.io")
    p_b = _seed_policy(store, b)
    signin(db_client, "a@quramail.io")
    # IDOR attempt: A requests B's policy by id.
    assert db_client.get(f"/api/client/policies/{p_b.id}").status_code == 404


def test_get_missing_policy_is_404(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    signin(db_client, "a@quramail.io")
    assert db_client.get("/api/client/policies/nonexistent").status_code == 404


def test_empty_policies_ok(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    signin(db_client, "a@quramail.io")
    resp = db_client.get("/api/client/policies")
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "message": "Success", "data": []}
