"""Regression tests for client-portal bug fixes (in-memory fake DB).

The fake session ignores loader options, so eager-loaded relationships are set
on seeded objects as the real ``selectinload`` would; the loader option itself
is asserted on the compiled statement.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.config import Environment, Settings
from app.db.models.claims import Claim
from app.db.models.kyc import KycDocument
from app.db.models.policies import Policy
from app.db.models.support import SupportTicket
from app.main import create_app
from app.modules.claims import service as claims_service
from app.modules.profile.uploads import avatar_url, public_photo_url
from fastapi.testclient import TestClient

from tests.phase4_helpers import seed_user, signin

# Minimal valid PNG (8-byte signature + IHDR is enough for content sniffing).
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f"
    b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _policy(user, **kw):  # type: ignore[no-untyped-def]
    defaults = {
        "user_id": user.id,
        "status": "active",
        "benefits": [],
        "exclusions": [],
        "policy_source": "uploaded",
    }
    defaults.update(kw)
    return Policy(**defaults)


# --- 8. claim list carries the policy summary -------------------------------


def test_list_claims_eager_loads_policy() -> None:
    captured = {}

    class _Spy:
        async def execute(self, stmt):  # type: ignore[no-untyped-def]
            captured["stmt"] = stmt

            class _R:
                def scalars(self):  # type: ignore[no-untyped-def]
                    return self

                def all(self):  # type: ignore[no-untyped-def]
                    return []

            return _R()

    import asyncio

    asyncio.run(claims_service.list_claims(_Spy(), "u1"))  # type: ignore[arg-type]
    paths = [str(opt.path) for opt in captured["stmt"]._with_options]
    assert any("policy" in p for p in paths), paths


def test_list_claims_returns_policy_summary(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    policy = _policy(
        a, policy_number="POL-1", insurer_name="Acme Health", policy_type="health"
    )
    store.seed(policy)
    claim = Claim(
        user_id=a.id, policy_id=policy.id, claim_number="CLM-A",
        status="submitted", timeline=[],
    )
    store.seed(claim)
    claim.policy = policy  # as selectinload(Claim.policy) would
    signin(db_client, "a@quramail.io")
    data = db_client.get("/api/client/claims").json()["data"]
    assert data[0]["policy"] == {
        "policy_number": "POL-1",
        "insurer_name": "Acme Health",
        "policy_type": "health",
    }


# --- 9. dashboard counts ------------------------------------------------------


def test_dashboard_counts_pending_claims_and_open_tickets(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    for status in ("submitted", "documents_pending", "in_review", "approved",
                   "rejected", "settled"):
        store.seed(Claim(user_id=a.id, claim_number=f"C-{status}", status=status,
                         timeline=[]))
    for status in ("open", "in_progress", "resolved", "closed"):
        store.seed(SupportTicket(user_id=a.id, subject=status, status=status,
                                 category="general", priority="low"))
    signin(db_client, "a@quramail.io")
    stats = db_client.get("/api/client/dashboard").json()["data"]["stats"]
    assert stats["pendingClaims"] == 3
    assert stats["openTickets"] == 2


def test_dashboard_renewal_window_is_30_days(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    today = datetime.now(UTC).date()
    store.seed(_policy(a, end_date=today + timedelta(days=29),
                       coverage_amount=Decimal("1")))
    store.seed(_policy(a, end_date=today + timedelta(days=45),
                       coverage_amount=Decimal("1")))
    signin(db_client, "a@quramail.io")
    stats = db_client.get("/api/client/dashboard").json()["data"]["stats"]
    assert stats["upcomingRenewals"] == 1


# --- 10. session bootstrap includes the KYC summary ---------------------------


def test_session_includes_kyc_documents(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    store.seed(KycDocument(user_id=a.id, doc_type="pan", original_name="pan.pdf",
                           content_type="application/pdf", status="pending"))
    signin(db_client, "a@quramail.io")
    user = db_client.get("/api/client/auth/session").json()["data"]["user"]
    assert user["preferences"]["kyc_documents"] == {
        "pan": {"name": "pan.pdf", "status": "pending"}
    }


# --- 11. avatar URL is loadable from the frontend origin ----------------------


def test_public_photo_url_rewrites_legacy_path() -> None:
    assert avatar_url("/api/client") == "/api/client/user/avatar"
    assert public_photo_url("/user/avatar", "/api/client") == "/api/client/user/avatar"
    assert public_photo_url("https://x/y.png", "/api/client") == "https://x/y.png"
    assert public_photo_url(None, "/api/client") is None


def test_legacy_photo_url_is_exposed_with_api_prefix(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    a.photo_url = "/user/avatar"
    signin(db_client, "a@quramail.io")
    user = db_client.get("/api/client/auth/session").json()["data"]["user"]
    assert user["photo_url"] == "/api/client/user/avatar"


@pytest.fixture
def storage_client(tmp_path, store) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    from app.db.session import get_session

    from tests.fakes import FakeSession

    settings = Settings(  # type: ignore[call-arg]
        environment=Environment.TEST,
        database_url=None,
        session_secret="qura-dev-secret-change-me",
        cors_allow_origins=[],
        log_json=False,
        storage_dir=str(tmp_path / "storage"),
    )
    app = create_app(settings)

    async def _override():  # type: ignore[no-untyped-def]
        yield FakeSession(store)

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as client:
        yield client


def test_avatar_upload_returns_prefixed_url_served_by_cookie(
    storage_client, store, monkeypatch
) -> None:
    # The fake result has no ``.first()``; resolve the avatar row from the store.
    from app.db.models.files import StoredFile
    from app.modules.profile import uploads

    async def _owned(session, user_id):  # type: ignore[no-untyped-def]
        rows = [
            f for f in store.data[StoredFile]
            if str(f.owner_user_id) == str(user_id) and f.purpose == "avatar"
        ]
        return rows[0] if rows else None

    monkeypatch.setattr(uploads, "_owned_avatar_file", _owned)
    a = seed_user(store, "a@quramail.io")
    csrf = signin(storage_client, "a@quramail.io")
    resp = storage_client.post(
        "/api/client/user/avatar",
        files={"file": ("me.png", _PNG, "image/png")},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200, resp.text
    url = resp.json()["data"]["fileUrl"]
    assert url == "/api/client/user/avatar"
    assert a.photo_url == url
    # The URL resolves to the cookie-authenticated GET route.
    got = storage_client.get(url)
    assert got.status_code == 200
    assert got.content == _PNG
    storage_client.cookies.clear()
    assert storage_client.get(url).status_code == 401


# --- FileClaim local-date picker: the server must accept the local "today" ----


def test_claim_incident_date_allows_local_today_ahead_of_utc(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    policy = _policy(a, policy_number="POL-1", policy_type="health")
    store.seed(policy)
    csrf = signin(db_client, "a@quramail.io")
    # The furthest-ahead local calendar date (UTC+14) is "today" somewhere.
    local_today = (datetime.now(UTC) + timedelta(hours=14)).date()
    form = {
        "policy_id": str(policy.id),
        "description": "Hospitalised after a fall at home",
        "claim_amount": "1000",
    }
    ok = db_client.post(
        "/api/client/claims",
        data={**form, "submission_date": local_today.isoformat()},
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status_code in (200, 201), ok.text
    future = db_client.post(
        "/api/client/claims",
        data={**form, "submission_date": (local_today + timedelta(days=1)).isoformat()},
        headers={"X-CSRF-Token": csrf},
    )
    assert future.status_code == 422
