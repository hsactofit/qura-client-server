"""ORM -> frontend mapping for policies.

The frontend ``Policy`` type reads camel/snake fields directly from the row plus
a derived ``name``. ``name`` is NOT a column; the frontend comment acknowledges
it is derived from ``policy_type``. ``covered_members`` and ``fees`` are read by
the UI but have no backing column — they are returned as safe empty defaults and
documented as a schema gap, never fabricated.
"""

from __future__ import annotations

from typing import Any

from app.db.models.policies import Policy


def _num(value: Any) -> Any:
    # Numeric(14,2) serialises as Decimal; the frontend treats amounts loosely.
    return float(value) if value is not None else None


def policy_to_dict(policy: Policy) -> dict[str, Any]:
    return {
        "id": str(policy.id),
        "policy_number": policy.policy_number,
        # Derived display name (frontend expects `name`); no invented data.
        "name": policy.policy_type,
        "policy_type": policy.policy_type,
        "insurer_name": policy.insurer_name,
        "coverage_amount": _num(policy.coverage_amount),
        "premium_amount": _num(policy.premium_amount),
        "premium_frequency": policy.premium_frequency,
        "start_date": policy.start_date.isoformat() if policy.start_date else None,
        "end_date": policy.end_date.isoformat() if policy.end_date else None,
        "status": policy.status,
        "nominee_name": policy.nominee_name,
        "nominee_relationship": policy.nominee_relationship,
        "benefits": policy.benefits or [],
        "exclusions": policy.exclusions or [],
        "policy_source": policy.policy_source,
        "proposal_id": policy.proposal_id,
        "external_policy_id": policy.external_policy_id,
        "product_enum": policy.product_enum,
        "document_original_name": policy.document_original_name,
        # Read by the UI but unbacked by the schema; safe empty defaults.
        "covered_members": [],
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
    }
