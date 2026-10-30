"""Call-back requests: categories, preferred time, endorsement copies, duplicates.

In-memory fake DB and a temporary storage dir, as in the policy tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta

import pytest
from app.core.errors import ApiError
from app.db.models.policies import Policy
from app.db.models.support import SupportTicket, TicketMessage
from app.main import create_app
from app.modules.support.requests import INDIA, validate_callback_time
from fastapi.testclient import TestClient

from tests.phase4_helpers import seed_user, signin
from tests.test_policies_operations import _MINIMAL_PDF, _PNG_BYTES, build_settings

URL = "/api/client/support/requests"


@pytest.fixture
def store():  # type: ignore[no-untyped-def]
    from tests.fakes import FakeStore

    return FakeStore()


@pytest.fixture
def db_client(tmp_path, store) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    from app.db.session import get_session

    from tests.fakes import FakeSession

    app = create_app(build_settings(tmp_path))

    async def _override_get_session():  # type: ignore[no-untyped-def]
        yield FakeSession(store)

    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as client:
        yield client


def _slot(days: int = 2, at: time = time(11, 0)) -> datetime:
    """A working-day slot ``days`` from now (skipping Sunday), India time."""
    day = datetime.now(INDIA).date() + timedelta(days=days)
    if day.weekday() == 6:
        day += timedelta(days=1)
    return datetime.combine(day, at, tzinfo=INDIA)


def _sunday() -> datetime:
    day = datetime.now(INDIA).date() + timedelta(days=1)
    while day.weekday() != 6:
        day += timedelta(days=1)
    return datetime.combine(day, time(11, 0), tzinfo=INDIA)


def _auth(db_client, store, email="a@quramail.io"):  # type: ignore[no-untyped-def]
    user = seed_user(store, email)
    return user, {"X-CSRF-Token": signin(db_client, email)}


def _policy(store, user, **kw):  # type: ignore[no-untyped-def]
    policy = Policy(
        user_id=user.id, policy_type="motor", insurer_name="ICICI Lombard",
        policy_number=kw.pop("number", "P-1"), status="active",
        policy_source="uploaded", verification_status="self_reported", **kw,
    )
    store.seed(policy)
    return policy


def _post(db_client, headers, files=None, **form):  # type: ignore[no-untyped-def]
    form.setdefault("preferred_callback_at", _slot().isoformat())
    return db_client.post(URL, headers=headers, data=form, files=files)


# --- time rules -------------------------------------------------------------


def test_callback_time_rules() -> None:
    now = datetime(2026, 11, 2, 4, 0, tzinfo=UTC)  # Monday 09:30 IST
    ok = datetime(2026, 11, 3, 11, 0, tzinfo=INDIA)
    assert validate_callback_time(ok, now=now) == ok.astimezone(UTC)
    bad = [
        datetime(2026, 11, 2, 4, 10, tzinfo=UTC),  # under 30 minutes away
        datetime(2026, 11, 8, 11, 0, tzinfo=INDIA),  # Sunday
        datetime(2026, 11, 3, 8, 30, tzinfo=INDIA),  # before 9:00
        datetime(2026, 11, 3, 18, 45, tzinfo=INDIA),  # after the last slot
        datetime(2026, 12, 15, 11, 0, tzinfo=INDIA),  # more than 30 days ahead
        datetime(2026, 11, 3, 11, 0),  # no timezone
    ]
    for value in bad:
        with pytest.raises(ApiError):
            validate_callback_time(value, now=now)


# --- creating requests ----------------------------------------------------------


def test_requires_auth_and_csrf(db_client, store) -> None:
    assert db_client.post(URL, data={"kind": "general"}).status_code in (401, 403)
    _auth(db_client, store)
    assert _post(db_client, {"X-CSRF-Token": ""}, kind="general", message="hi").status_code == 403


def test_quotation_request_saves_type_and_time(db_client, store) -> None:
    _, headers = _auth(db_client, store)
    when = _slot()
    resp = _post(
        db_client, headers, kind="quotation", insurance_type="health",
        preferred_callback_at=when.isoformat(), message="Family floater for 4",
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["category"] == "quotation"
    assert data["insurance_type"] == "health"
    assert data["subject"] == "Quotation request: Health"
    assert datetime.fromisoformat(data["preferred_callback_at"]) == when
    ticket = store.data[SupportTicket][0]
    assert ticket.priority == "medium"  # set by the topic, not chosen by the client
    assert [m.message for m in store.data[TicketMessage]] == ["Family floater for 4"]


def test_quotation_needs_insurance_type(db_client, store) -> None:
    _, headers = _auth(db_client, store)
    assert _post(db_client, headers, kind="quotation").status_code == 422
    assert _post(db_client, headers, kind="quotation", insurance_type="pets").status_code == 422


def test_unknown_kind_and_bad_time_rejected(db_client, store) -> None:
    _, headers = _auth(db_client, store)
    assert _post(db_client, headers, kind="claim", message="x").status_code == 422
    sunday = _sunday().isoformat()
    resp = _post(db_client, headers, kind="general", message="x", preferred_callback_at=sunday)
    assert resp.status_code == 422
    resp = _post(db_client, headers, kind="general", message="x", preferred_callback_at="soon")
    assert resp.status_code == 422
    assert store.data[SupportTicket] == []


def test_policy_topics_need_an_owned_policy(db_client, store) -> None:
    user, headers = _auth(db_client, store)
    other = seed_user(store, "b@quramail.io")
    theirs = _policy(store, other, number="THEIRS")
    for kind in ("policy_correction", "endorsement", "renewal"):
        assert _post(db_client, headers, kind=kind).status_code == 422
    resp = _post(db_client, headers, kind="renewal", policy_id=str(theirs.id))
    assert resp.status_code == 404
    mine = _policy(store, user)
    resp = _post(db_client, headers, kind="policy_correction", policy_id=str(mine.id))
    assert resp.status_code == 200
    assert resp.json()["data"]["subject"] == "Policy correction: ICICI Lombard P-1"
    assert store.data[SupportTicket][0].priority == "high"


def test_other_needs_a_message(db_client, store) -> None:
    _, headers = _auth(db_client, store)
    assert _post(db_client, headers, kind="general").status_code == 422
    assert _post(db_client, headers, kind="general", message="<b>").status_code == 422
    assert _post(db_client, headers, kind="general", message="Nominee query").status_code == 200


# --- duplicates -------------------------------------------------------------------


def test_duplicate_open_request_is_refused(db_client, store) -> None:
    user, headers = _auth(db_client, store)
    policy = _policy(store, user)
    first = _post(db_client, headers, kind="renewal", policy_id=str(policy.id))
    assert first.status_code == 200
    again = _post(db_client, headers, kind="renewal", policy_id=str(policy.id))
    assert again.status_code == 409
    assert again.json()["error"]["ticket_id"] == first.json()["data"]["id"]
    assert len(store.data[SupportTicket]) == 1
    # A different topic, or another policy, is new work.
    other = _policy(store, user, number="P-2")
    assert _post(db_client, headers, kind="renewal", policy_id=str(other.id)).status_code == 200
    assert _post(db_client, headers, kind="payment", policy_id=str(policy.id)).status_code == 200
    # Once the first one is resolved the client can ask again.
    store.data[SupportTicket][0].status = "resolved"
    assert _post(db_client, headers, kind="renewal", policy_id=str(policy.id)).status_code == 200


def test_duplicate_quotation_is_per_insurance_type(db_client, store) -> None:
    _, headers = _auth(db_client, store)
    assert _post(db_client, headers, kind="quotation", insurance_type="motor").status_code == 200
    assert _post(db_client, headers, kind="quotation", insurance_type="motor").status_code == 409
    assert _post(db_client, headers, kind="quotation", insurance_type="life").status_code == 200


def test_legacy_ticket_create_blocks_duplicates_and_saves_message(db_client, store) -> None:
    _, headers = _auth(db_client, store)
    body = {"subject": "Cannot log in", "category": "login", "message": "Reset fails"}
    url = "/api/client/support/tickets/create"
    assert db_client.post(url, headers=headers, json=body).status_code == 200
    assert [m.message for m in store.data[TicketMessage]] == ["Reset fails"]
    dup = db_client.post(url, headers=headers, json={**body, "subject": "  cannot LOG in "})
    assert dup.status_code == 409
    assert len(store.data[SupportTicket]) == 1


# --- endorsement copies -------------------------------------------------------------


def test_endorsement_copy_upload(db_client, store) -> None:
    from app.db.models.files import StoredFile

    user, headers = _auth(db_client, store)
    policy = _policy(store, user)
    doc = {"document": ("endorsement.pdf", _MINIMAL_PDF, "application/pdf")}
    resp = _post(db_client, headers, files=doc, kind="endorsement", policy_id=str(policy.id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["has_document"] is True
    stored = store.data[StoredFile][0]
    assert stored.purpose == "endorsement"
    assert store.data[SupportTicket][0].document_file_id == stored.id

    # The same file again is a duplicate; a different endorsement copy is new.
    pid = str(policy.id)
    again = _post(db_client, headers, files=doc, kind="endorsement", policy_id=pid)
    assert again.status_code == 409
    other = {"document": ("second.png", _PNG_BYTES, "image/png")}
    second = _post(db_client, headers, files=other, kind="endorsement", policy_id=pid)
    assert second.status_code == 200


def test_document_only_for_endorsements(db_client, store) -> None:
    user, headers = _auth(db_client, store)
    policy = _policy(store, user)
    doc = {"document": ("x.pdf", _MINIMAL_PDF, "application/pdf")}
    resp = _post(db_client, headers, files=doc, kind="renewal", policy_id=str(policy.id))
    assert resp.status_code == 422
    bad = {"document": ("x.txt", b"plain text", "text/plain")}
    resp = _post(db_client, headers, files=bad, kind="endorsement", policy_id=str(policy.id))
    assert resp.status_code == 415


def test_message_on_resolved_request_reopens_it(db_client, store) -> None:
    user, headers = _auth(db_client, store)
    ticket = SupportTicket(
        user_id=user.id, subject="Renewal", category="renewal", status="resolved"
    )
    store.seed(ticket)
    url = f"/api/client/support/tickets/{ticket.id}/messages"
    resp = db_client.post(url, headers=headers, json={"message": "Still not renewed"})
    assert resp.status_code == 200
    assert ticket.status == "open"


# --- status pulled back from the CRM -------------------------------------------------


class _StatusSession:
    """Stub for _pull_ticket_status: returns prepared rows, records notifications."""

    def __init__(self, rows, tickets):  # type: ignore[no-untyped-def]
        self.rows, self.tickets, self.added = rows, tickets, []

    async def execute(self, _statement):  # type: ignore[no-untyped-def]
        rows = self.rows

        class _R:
            def mappings(self):  # type: ignore[no-untyped-def]
                return self

            def all(self):  # type: ignore[no-untyped-def]
                return rows

        return _R()

    async def get(self, _model, ticket_id):  # type: ignore[no-untyped-def]
        return self.tickets.get(ticket_id)

    def add(self, obj) -> None:  # type: ignore[no-untyped-def]
        self.added.append(obj)

    async def flush(self) -> None:
        return None


async def test_status_pull_resolves_unless_client_came_back() -> None:
    from app.modules.crm_sync.service import _pull_ticket_status

    done = SupportTicket(id="t1", user_id="u1", subject="Renewal", status="open")
    back = SupportTicket(id="t2", user_id="u1", subject="Renewal", status="open")
    rows = [
        {"id": "t1", "status": "open", "task_status": "COMPLETED", "client_acted_since": False},
        {"id": "t2", "status": "open", "task_status": "COMPLETED", "client_acted_since": True},
    ]
    session = _StatusSession(rows, {"t1": done, "t2": back})
    assert await _pull_ticket_status(session) == 1  # type: ignore[arg-type]
    assert done.status == "resolved"
    assert back.status == "open"  # the CRM opens a follow-up task instead
    assert len(session.added) == 1  # one "resolved" notification
