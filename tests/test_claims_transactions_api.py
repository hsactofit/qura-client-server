"""Claims and transactions API tests (in-memory fake DB)."""

from __future__ import annotations

from decimal import Decimal

from app.db.models.claims import Claim, ClaimDocument
from app.db.models.transactions import Transaction

from tests.phase4_helpers import seed_user, signin

# --- claims ---------------------------------------------------------------


def test_claims_requires_auth(db_client) -> None:
    assert db_client.get("/api/client/claims").status_code == 401


def test_list_claims_only_own(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    b = seed_user(store, "b@quramail.io")
    store.seed(Claim(user_id=a.id, claim_number="CLM-A", status="submitted", timeline=[]))
    store.seed(Claim(user_id=b.id, claim_number="CLM-B", status="submitted", timeline=[]))
    signin(db_client, "a@quramail.io")
    data = db_client.get("/api/client/claims").json()["data"]
    assert [c["claim_number"] for c in data] == ["CLM-A"]


def test_get_claim_with_documents(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    claim = Claim(user_id=a.id, claim_number="CLM-A", status="in_review", timeline=[])
    store.seed(claim)
    doc = ClaimDocument(claim_id=claim.id, name="report.pdf", content_type="application/pdf")
    store.seed(doc)
    # Attach the loaded relationship as the eager loader would.
    claim.documents = [doc]
    signin(db_client, "a@quramail.io")
    resp = db_client.get(f"/api/client/claims/{claim.id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["claim_number"] == "CLM-A"
    assert data["documents"] == [{"name": "report.pdf", "content_type": "application/pdf"}]


def test_get_other_users_claim_is_404(db_client, store) -> None:
    seed_user(store, "a@quramail.io")
    b = seed_user(store, "b@quramail.io")
    claim_b = Claim(user_id=b.id, claim_number="CLM-B", status="submitted", timeline=[])
    store.seed(claim_b)
    signin(db_client, "a@quramail.io")
    assert db_client.get(f"/api/client/claims/{claim_b.id}").status_code == 404


def test_claim_nullable_amounts_serialize(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    store.seed(
        Claim(
            user_id=a.id, claim_number="CLM-A", status="submitted",
            claim_amount=None, approved_amount=None, timeline=[],
        )
    )
    signin(db_client, "a@quramail.io")
    data = db_client.get("/api/client/claims").json()["data"]
    assert data[0]["claim_amount"] is None
    assert data[0]["approved_amount"] is None
    assert data[0]["policy"] is None


# --- transactions ---------------------------------------------------------


def _seed_txn(store, user, **kw):  # type: ignore[no-untyped-def]
    defaults = {
        "user_id": user.id,
        "transaction_type": "purchase",
        "amount": Decimal("100"),
        "status": "success",
        "reference_id": None,
        "description": "desc",
    }
    defaults.update(kw)
    txn = Transaction(**defaults)
    store.seed(txn)
    return txn


def test_transactions_requires_auth(db_client) -> None:
    assert db_client.get("/api/client/transactions").status_code == 401


def test_transactions_list_shape_and_stats(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    _seed_txn(store, a, transaction_type="purchase", amount=Decimal("1000"), status="success")
    _seed_txn(store, a, transaction_type="renewal", amount=Decimal("500"), status="success")
    _seed_txn(store, a, transaction_type="payout", amount=Decimal("300"), status="success")
    _seed_txn(store, a, transaction_type="purchase", amount=Decimal("999"), status="failed")
    signin(db_client, "a@quramail.io")
    body = db_client.get("/api/client/transactions").json()["data"]
    assert "data" in body and "pagination" in body and "stats" in body
    # Paid = 1000 + 500 (success purchase+renewal); received = 300; net = -1200.
    assert body["stats"]["totalPaid"] == 1500.0
    assert body["stats"]["totalReceived"] == 300.0
    assert body["stats"]["netAmount"] == -1200.0
    assert body["pagination"]["total"] == 4
    # amount serialised as string.
    assert isinstance(body["data"][0]["amount"], str)


def test_transactions_only_own(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    b = seed_user(store, "b@quramail.io")
    _seed_txn(store, a, reference_id="A-TXN")
    _seed_txn(store, b, reference_id="B-TXN")
    signin(db_client, "a@quramail.io")
    body = db_client.get("/api/client/transactions").json()["data"]
    assert body["pagination"]["total"] == 1
    assert body["data"][0]["reference_id"] == "A-TXN"


def test_transactions_pagination_bounds(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    for i in range(5):
        _seed_txn(store, a, reference_id=f"T{i}")
    signin(db_client, "a@quramail.io")
    # Negative/oversized values are clamped, not errors.
    body = db_client.get("/api/client/transactions?page=-3&limit=2").json()["data"]
    assert body["pagination"]["page"] == 1
    assert body["pagination"]["limit"] == 2
    assert len(body["data"]) == 2


def test_transactions_type_filter(db_client, store) -> None:
    a = seed_user(store, "a@quramail.io")
    _seed_txn(store, a, transaction_type="purchase", reference_id="P")
    _seed_txn(store, a, transaction_type="refund", reference_id="R")
    signin(db_client, "a@quramail.io")
    body = db_client.get("/api/client/transactions?type=refund").json()["data"]
    assert [t["reference_id"] for t in body["data"]] == ["R"]
