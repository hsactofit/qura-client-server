"""ORM -> frontend mapping for claims.

Frontend ``Claim`` type: claim_number, claim_amount, approved_amount, status,
description, submission_date, created_at, nested ``policy`` summary, and
``documents[{name, file_url}]`` (Downloads page). The policy summary and the
documents are included only when already loaded on the instance (the list view
eager-loads ``policy``; the detail view eager-loads documents).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sa_inspect

from app.db.models.claims import Claim


def _num(value: Any) -> Any:
    return float(value) if value is not None else None


def _is_loaded(obj: Any, attr: str) -> bool:
    """True if a relationship is safe to read without a sync lazy load.

    Reads the value already present in ``__dict__`` (set by eager load or by a
    test fixture) and treats an unloaded mapped relationship as absent.
    """
    if attr in obj.__dict__:
        return True
    return attr not in sa_inspect(obj).unloaded


def _policy_summary(claim: Claim) -> dict[str, Any] | None:
    if not _is_loaded(claim, "policy"):
        return None
    policy = claim.policy
    if policy is None:
        return None
    return {
        "policy_number": policy.policy_number,
        "insurer_name": policy.insurer_name,
        "policy_type": policy.policy_type,
    }


def _documents(claim: Claim) -> list[dict[str, Any]]:
    if not _is_loaded(claim, "documents"):
        return []
    return [
        {"name": doc.name, "content_type": doc.content_type}
        for doc in claim.documents
    ]


def claim_to_dict(claim: Claim, *, include_documents: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(claim.id),
        "claim_number": claim.claim_number,
        "claim_amount": _num(claim.claim_amount),
        "approved_amount": _num(claim.approved_amount),
        "status": claim.status,
        "description": claim.description,
        "submission_date": (
            claim.submission_date.isoformat() if claim.submission_date else None
        ),
        "settled_date": claim.settled_date.isoformat() if claim.settled_date else None,
        "timeline": claim.timeline or [],
        "policy": _policy_summary(claim),
        "created_at": claim.created_at.isoformat() if claim.created_at else None,
    }
    if include_documents:
        data["documents"] = _documents(claim)
    return data
