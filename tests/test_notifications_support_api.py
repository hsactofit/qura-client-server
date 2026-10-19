"""Notifications, support, dashboard, reference API tests (in-memory fake DB)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models.engagement import Announcement, Notification
from app.db.models.policies import Policy
from app.db.models.reference import MasterData
from app.db.models.support import SupportTicket, TicketMessage

from tests.phase4_helpers import seed_user, signin

# --- notifications --------------------------------------------------------


def test_notifications_requires_auth(db_client) -> None:
    assert db_client.get("/api/client/notifications").status_code == 401


def test_list_notifications_and_announcements(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    store.seed(Notification(user_id=a.id, title="Hi", message="m", type="info", is_read=False))
    store.seed(
        Announcement(
            title="News", message="m", type="info",
            start_date=datetime.now(UTC) - timedelta(days=1),
            end_date=datetime.now(UTC) + timedelta(days=1),
        )
    )
    signin(db_client, "a@quramail.io")
    data = db_client.get("/api/client/notifications").json()["data"]
    assert len(data["notifications"]) == 1
    assert len(data["announcements"]) == 1
    assert data["unread_count"] == 1


def test_mark_read_only_own(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    b = seed_user(store, "b@quramail.io")
    n_b = Notification(user_id=b.id, title="B", message="m", type="info", is_read=False)
    store.seed(n_b)
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.post(
        f"/api/client/notifications/{n_b.id}/read", headers={"X-CSRF-Token": csrf}
    )
    assert resp.status_code == 404
    assert n_b.is_read is False  # untouched


def test_mark_read_requires_csrf(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    n = Notification(user_id=a.id, title="A", message="m", type="info", is_read=False)
    store.seed(n)
    signin(db_client, "a@quramail.io")
    resp = db_client.post(
        f"/api/client/notifications/{n.id}/read", headers={"X-CSRF-Token": ""}
    )
    assert resp.status_code == 403


def test_mark_all_read(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    store.seed(Notification(user_id=a.id, title="1", message="m", type="info", is_read=False))
    store.seed(Notification(user_id=a.id, title="2", message="m", type="info", is_read=False))
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.post("/api/client/notifications/read-all", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert db_client.get("/api/client/notifications").json()["data"]["unread_count"] == 0


def test_unread_count_endpoint(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    store.seed(Notification(user_id=a.id, title="1", message="m", type="info", is_read=False))
    signin(db_client, "a@quramail.io")
    resp = db_client.get("/api/client/notifications/unread-count")
    assert resp.json()["data"]["unread_count"] == 1


# --- support --------------------------------------------------------------


def test_tickets_requires_auth(db_client) -> None:
    assert db_client.get("/api/client/support/tickets").status_code == 401


def test_create_list_ticket(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.post(
        "/api/client/support/tickets/create",
        headers={"X-CSRF-Token": csrf},
        json={"subject": "Help", "category": "general", "priority": "low"},
    )
    assert resp.status_code == 200
    listed = db_client.get("/api/client/support/tickets").json()["data"]
    assert len(listed) == 1
    assert listed[0]["subject"] == "Help"


def test_ticket_messages_blocked_for_other_user(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    b = seed_user(store, "b@quramail.io")
    ticket_b = SupportTicket(user_id=b.id, subject="B ticket", status="open")
    store.seed(ticket_b)
    store.seed(TicketMessage(ticket_id=ticket_b.id, sender_id=b.id, message="secret"))
    signin(db_client, "a@quramail.io")
    # IDOR: A tries to read B's ticket conversation.
    assert db_client.get(
        f"/api/client/support/tickets/{ticket_b.id}/messages"
    ).status_code == 404


def test_post_message_to_own_ticket(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    ticket = SupportTicket(user_id=a.id, subject="Mine", status="open")
    store.seed(ticket)
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.post(
        f"/api/client/support/tickets/{ticket.id}/messages",
        headers={"X-CSRF-Token": csrf},
        json={"message": "Hello there"},
    )
    assert resp.status_code == 200
    msgs = db_client.get(f"/api/client/support/tickets/{ticket.id}/messages").json()["data"]
    assert len(msgs) == 1
    assert msgs[0]["message"] == "Hello there"


def test_create_ticket_rejects_markup(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    csrf = signin(db_client, "a@quramail.io")
    resp = db_client.post(
        "/api/client/support/tickets/create",
        headers={"X-CSRF-Token": csrf},
        json={"subject": "<script>", "category": "general", "priority": "low"},
    )
    assert resp.status_code == 422


# --- dashboard ------------------------------------------------------------


def test_dashboard_requires_auth(db_client) -> None:
    assert db_client.get("/api/client/dashboard").status_code == 401


def test_dashboard_uses_only_own_records(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    b = seed_user(store, "b@quramail.io")
    store.seed(Policy(user_id=a.id, status="active", coverage_amount=Decimal("500000"),
                      benefits=[], exclusions=[], policy_source="uploaded"))
    store.seed(Policy(user_id=b.id, status="active", coverage_amount=Decimal("999999"),
                      benefits=[], exclusions=[], policy_source="uploaded"))
    signin(db_client, "a@quramail.io")
    data = db_client.get("/api/client/dashboard").json()["data"]
    assert data["stats"]["activePolicies"] == 1
    assert data["coverageAnalysis"]["totalCurrentCoverage"] == 500000.0
    assert data["coverageAnalysis"]["status"] == "unavailable"


# --- reference ------------------------------------------------------------


def test_master_data_filter(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    store.seed(
        MasterData(
            category="RELATIONSHIP", label="Spouse", value="SPOUSE",
            sort_order=0, is_active=True,
        )
    )
    store.seed(
        MasterData(
            category="GENDER", label="Male", value="MALE", sort_order=0, is_active=True
        )
    )
    signin(db_client, "a@quramail.io")
    data = db_client.get("/api/client/master-data?category=RELATIONSHIP").json()["data"]
    assert data == [{"label": "Spouse", "value": "SPOUSE"}]


def test_faqs_empty_when_none(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    signin(db_client, "a@quramail.io")
    assert db_client.get("/api/client/faqs").json()["data"] == []


def test_faqs_returns_faq_rows(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    store.seed(MasterData(category="FAQ", label="Q1?", value="A1", sort_order=0, is_active=True))
    signin(db_client, "a@quramail.io")
    data = db_client.get("/api/client/faqs").json()["data"]
    assert data[0]["question"] == "Q1?"
    assert data[0]["answer"] == "A1"
