"""Tests for the policy operations: extract, upload, track, confirm, status,
download, ownership isolation, validation, and the response envelope.

These use the in-memory fake DB (no live Postgres) and a temporary private
storage dir via an isolated Settings. Extraction is unconfigured by default, so
tests assert the honest "unavailable" / no-fabrication behaviour; the merge and
persistence paths are exercised with user-supplied fields.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.core.config import Environment, Settings
from app.main import create_app
from fastapi.testclient import TestClient

from tests.phase4_helpers import seed_user, signin

# A minimal valid single-page PDF (starts with %PDF-, has an EOF).
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n"
    b"trailer<</Root 1 0 R/Size 4>>\n%%EOF\n"
)
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_NOT_A_DOC = b"this is just plain text, not a supported document format"


def build_settings(tmp_path, **overrides) -> Settings:  # type: ignore[no-untyped-def]
    defaults: dict[str, object] = {
        "environment": Environment.TEST,
        "database_url": None,
        "session_secret": "qura-dev-secret-change-me",
        "cors_allow_origins": [],
        "log_json": False,
        "storage_dir": str(tmp_path / "storage"),
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def store():  # type: ignore[no-untyped-def]
    from tests.fakes import FakeStore

    return FakeStore()


@pytest.fixture
def db_client(tmp_path, store) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    from app.db.session import get_session

    from tests.fakes import FakeSession

    settings = build_settings(tmp_path)
    app = create_app(settings)

    async def _override_get_session():  # type: ignore[no-untyped-def]
        yield FakeSession(store)

    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as client:
        yield client


def _auth(db_client, store, email="a@quramail.io"):  # type: ignore[no-untyped-def]
    seed_user(store, email)
    token = signin(db_client, email)
    return {"X-CSRF-Token": token}


# --- Extract ---------------------------------------------------------------


def test_extract_requires_auth(db_client) -> None:
    resp = db_client.post(
        "/api/client/policies/extract",
        files={"document": ("p.pdf", _MINIMAL_PDF, "application/pdf")},
    )
    assert resp.status_code == 401


def test_extract_unconfigured_returns_null_fields_not_fabricated(
    db_client, store
) -> None:
    headers = _auth(db_client, store)
    resp = db_client.post(
        "/api/client/policies/extract",
        files={"document": ("p.pdf", _MINIMAL_PDF, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["extraction_available"] is False
    # No fabrication: every field is null when extraction is unavailable.
    assert all(v is None for v in data["extracted"].values())


def test_extract_rejects_unsupported_type(db_client, store) -> None:
    headers = _auth(db_client, store)
    # Declared as PDF but content is plain text -> sniffing rejects it (415).
    resp = db_client.post(
        "/api/client/policies/extract",
        files={"document": ("p.pdf", _NOT_A_DOC, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 415


def test_extract_rejects_empty_file(db_client, store) -> None:
    headers = _auth(db_client, store)
    resp = db_client.post(
        "/api/client/policies/extract",
        files={"document": ("p.pdf", b"", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 400


def test_extract_rejects_oversized_file(db_client, store, tmp_path) -> None:
    # Rebuild a client with a tiny upload cap to exercise the 413 path.
    from app.db.session import get_session

    from tests.fakes import FakeSession

    settings = build_settings(tmp_path, upload_max_bytes=16)
    app = create_app(settings)

    async def _override():  # type: ignore[no-untyped-def]
        yield FakeSession(store)

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as client:
        seed_user(store, "a@quramail.io")
        token = signin(client, "a@quramail.io")
        big = _MINIMAL_PDF  # larger than 16 bytes
        resp = client.post(
            "/api/client/policies/extract",
            files={"document": ("p.pdf", big, "application/pdf")},
            headers={"X-CSRF-Token": token},
        )
        assert resp.status_code == 413


def test_extract_does_not_create_a_policy(db_client, store) -> None:
    from app.db.models.policies import Policy

    headers = _auth(db_client, store)
    db_client.post(
        "/api/client/policies/extract",
        files={"document": ("p.png", _PNG_BYTES, "image/png")},
        headers=headers,
    )
    assert store.data.get(Policy, []) == []


# --- Upload ----------------------------------------------------------------


def test_upload_requires_auth(db_client) -> None:
    resp = db_client.post(
        "/api/client/policies/upload",
        data={"policy_type": "health", "insurer_name": "Acme"},
    )
    assert resp.status_code == 401


def test_upload_persists_user_owned_record_with_document(db_client, store) -> None:
    from app.db.models.policies import Policy

    headers = _auth(db_client, store)
    resp = db_client.post(
        "/api/client/policies/upload",
        data={
            "policy_number": "USER-123",
            "policy_type": "health",
            "insurer_name": "Acme",
            "coverage_amount": "1000000",
            "premium_amount": "12000",
            "start_date": "2026-01-01",
            "end_date": "2027-01-01",
        },
        files={"document": ("p.pdf", _MINIMAL_PDF, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    policy = data["policy"]
    assert policy["policy_number"] == "USER-123"
    assert policy["policy_source"] == "uploaded"
    # A self-uploaded doc is never insurer-verified.
    assert policy["verification_status"] == "self_reported"
    assert policy["has_document"] is True
    assert data["duplicate"] is False

    # Exactly one policy persisted, owned by the authenticated user.
    from app.db.models.identity import User

    stored = store.data.get(Policy, [])
    assert len(stored) == 1
    user = store.data[User][0]
    assert str(stored[0].user_id) == str(user.id)


def test_upload_requires_policy_type_and_insurer(db_client, store) -> None:
    headers = _auth(db_client, store)
    # Missing insurer_name -> validation error (422).
    resp = db_client.post(
        "/api/client/policies/upload",
        data={"policy_type": "health"},
        headers=headers,
    )
    assert resp.status_code == 422


def test_upload_rejects_end_before_start(db_client, store) -> None:
    headers = _auth(db_client, store)
    resp = db_client.post(
        "/api/client/policies/upload",
        data={
            "policy_type": "health",
            "insurer_name": "Acme",
            "start_date": "2027-01-01",
            "end_date": "2026-01-01",
        },
        headers=headers,
    )
    assert resp.status_code == 422


def test_upload_without_document_persists_manual_fields(db_client, store) -> None:
    headers = _auth(db_client, store)
    resp = db_client.post(
        "/api/client/policies/upload",
        data={"policy_type": "life", "insurer_name": "LIC"},
        headers=headers,
    )
    assert resp.status_code == 200
    policy = resp.json()["data"]["policy"]
    assert policy["has_document"] is False
    assert policy["policy_type"] == "life"


def test_upload_duplicate_document_is_idempotent(db_client, store) -> None:
    from app.db.models.policies import Policy

    headers = _auth(db_client, store)
    payload = {
        "data": {"policy_type": "health", "insurer_name": "Acme"},
        "files": {"document": ("p.pdf", _MINIMAL_PDF, "application/pdf")},
        "headers": headers,
    }
    first = db_client.post("/api/client/policies/upload", **payload)
    assert first.status_code == 200
    assert first.json()["data"]["duplicate"] is False
    second = db_client.post("/api/client/policies/upload", **payload)
    assert second.status_code == 200
    assert second.json()["data"]["duplicate"] is True
    # Only one record exists despite two submissions.
    assert len(store.data.get(Policy, [])) == 1


def test_upload_rejects_unsupported_document(db_client, store) -> None:
    headers = _auth(db_client, store)
    resp = db_client.post(
        "/api/client/policies/upload",
        data={"policy_type": "health", "insurer_name": "Acme"},
        files={"document": ("x.pdf", _NOT_A_DOC, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 415


# --- Track / confirm / status ----------------------------------------------


def test_track_creates_pending_platform_record(db_client, store) -> None:
    headers = _auth(db_client, store)
    resp = db_client.post(
        "/api/client/policies/track",
        json={"proposal_id": "PROP-1", "insurer_name": "Acme"},
        headers=headers,
    )
    assert resp.status_code == 200
    policy = resp.json()["data"]
    assert policy["policy_source"] == "platform"
    assert policy["status"] == "pending"
    assert policy["proposal_id"] == "PROP-1"


def test_track_is_idempotent_per_proposal(db_client, store) -> None:
    from app.db.models.policies import Policy

    headers = _auth(db_client, store)
    body = {"proposal_id": "PROP-9"}
    db_client.post("/api/client/policies/track", json=body, headers=headers)
    db_client.post("/api/client/policies/track", json=body, headers=headers)
    assert len(store.data.get(Policy, [])) == 1


def test_confirm_marks_user_confirmed(db_client, store) -> None:
    headers = _auth(db_client, store)
    db_client.post(
        "/api/client/policies/track",
        json={"proposal_id": "PROP-2"},
        headers=headers,
    )
    resp = db_client.patch(
        "/api/client/policies/confirm",
        json={"proposal_id": "PROP-2", "policy_number": "POL-XYZ"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["policy_number"] == "POL-XYZ"
    # Confirmation is a user action, not insurer verification.
    assert data["verification_status"] == "user_confirmed"


def test_confirm_unknown_proposal_is_404(db_client, store) -> None:
    headers = _auth(db_client, store)
    resp = db_client.patch(
        "/api/client/policies/confirm",
        json={"proposal_id": "NOPE"},
        headers=headers,
    )
    assert resp.status_code == 404


def test_status_sync_unavailable_is_501(db_client, store) -> None:
    headers = _auth(db_client, store)
    db_client.post(
        "/api/client/policies/track",
        json={"proposal_id": "PROP-3"},
        headers=headers,
    )
    resp = db_client.post(
        "/api/client/policies/status",
        json={"proposal_id": "PROP-3"},
        headers=headers,
    )
    # No insurer integration -> honest unsupported response, not fake success.
    assert resp.status_code == 501
    assert resp.json()["success"] is False


def test_status_unknown_proposal_is_404(db_client, store) -> None:
    headers = _auth(db_client, store)
    resp = db_client.post(
        "/api/client/policies/status",
        json={"proposal_id": "GHOST"},
        headers=headers,
    )
    assert resp.status_code == 404


# --- CSRF ------------------------------------------------------------------


def test_upload_without_csrf_is_rejected(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    signin(db_client, "a@quramail.io")  # sets session cookie, omit CSRF header
    resp = db_client.post(
        "/api/client/policies/upload",
        data={"policy_type": "health", "insurer_name": "Acme"},
    )
    assert resp.status_code == 403


# --- Download ---------------------------------------------------------------


def test_download_streams_owned_document(db_client, store) -> None:
    headers = _auth(db_client, store)
    up = db_client.post(
        "/api/client/policies/upload",
        data={"policy_type": "health", "insurer_name": "Acme"},
        files={"document": ("mypolicy.pdf", _MINIMAL_PDF, "application/pdf")},
        headers=headers,
    )
    policy_id = up.json()["data"]["policy"]["id"]
    resp = db_client.get(f"/api/client/policies/{policy_id}/download")
    assert resp.status_code == 200
    assert resp.content == _MINIMAL_PDF
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_download_other_users_policy_is_404(db_client, store) -> None:
    # User B uploads; user A must not download it.
    seed_user(store, "b@quramail.io")
    token_b = signin(db_client, "b@quramail.io")
    up = db_client.post(
        "/api/client/policies/upload",
        data={"policy_type": "health", "insurer_name": "Acme"},
        files={"document": ("b.pdf", _MINIMAL_PDF, "application/pdf")},
        headers={"X-CSRF-Token": token_b},
    )
    policy_id = up.json()["data"]["policy"]["id"]
    db_client.cookies.clear()
    seed_user(store, "a@quramail.io")
    signin(db_client, "a@quramail.io")
    resp = db_client.get(f"/api/client/policies/{policy_id}/download")
    assert resp.status_code == 404


def test_download_without_document_is_404(db_client, store) -> None:
    headers = _auth(db_client, store)
    up = db_client.post(
        "/api/client/policies/upload",
        data={"policy_type": "life", "insurer_name": "LIC"},
        headers=headers,
    )
    policy_id = up.json()["data"]["policy"]["id"]
    resp = db_client.get(f"/api/client/policies/{policy_id}/download")
    assert resp.status_code == 404


def test_download_requires_auth(db_client, store) -> None:
    resp = db_client.get("/api/client/policies/some-id/download")
    assert resp.status_code == 401
