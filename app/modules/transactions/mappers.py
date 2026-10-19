"""ORM -> frontend mapping for transactions.

Frontend ``Transaction`` type: id, reference_id, description, policy_number?,
insurer_name?, transaction_type, amount (string), payment_mode?, status,
created_at. ``amount`` is emitted as a string (the frontend treats the decimal as
a string). ``policy_number``/``insurer_name`` come from the linked policy only
when already loaded; otherwise null (never fabricated).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sa_inspect

from app.db.models.transactions import Transaction


def _loaded_policy(txn: Transaction) -> Any:
    if "policy" in txn.__dict__:
        return txn.policy
    if "policy" in sa_inspect(txn).unloaded:
        return None
    return txn.policy


def transaction_to_dict(txn: Transaction) -> dict[str, Any]:
    policy = _loaded_policy(txn)
    return {
        "id": str(txn.id),
        "reference_id": txn.reference_id,
        "description": txn.description,
        "policy_number": policy.policy_number if policy else None,
        "insurer_name": policy.insurer_name if policy else None,
        "transaction_type": txn.transaction_type,
        "amount": str(txn.amount) if txn.amount is not None else None,
        "payment_mode": txn.payment_mode,
        "status": txn.status,
        "created_at": txn.created_at.isoformat() if txn.created_at else None,
    }
