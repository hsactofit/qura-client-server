"""ORM -> frontend mapping for assets.

Matches the frontend ``Asset`` type. ``policy_number``/``insurer_name``/
``policy_status`` are read from the linked policy only when that relationship is
already loaded (to stay safe on the async session); otherwise null. They are
never fabricated. Eager-loading the link is a later optimisation if needed.
"""

from __future__ import annotations

from typing import Any

from app.db.models.assets import Asset


def _loaded_policy(asset: Asset) -> Any:
    """Return the linked policy ONLY if already loaded, never triggering a lazy
    (sync) load on the async session. Unloaded -> treated as absent."""
    from sqlalchemy import inspect as sa_inspect

    if "current_policy" in asset.__dict__:
        return asset.current_policy
    if "current_policy" in sa_inspect(asset).unloaded:
        return None
    return asset.current_policy


def asset_to_dict(asset: Asset) -> dict[str, Any]:
    linked = _loaded_policy(asset)
    return {
        "id": str(asset.id),
        "user_id": str(asset.user_id),
        "asset_type": asset.asset_type,
        "name": asset.name,
        "registration_no": asset.registration_no,
        "make": asset.make,
        "model": asset.model,
        "year": asset.year,
        "fuel_type": asset.fuel_type,
        "color": asset.color,
        "chassis_no": asset.chassis_no,
        "engine_no": asset.engine_no,
        "property_address": asset.property_address,
        "property_type": asset.property_type,
        "property_area_sqft": (
            float(asset.property_area_sqft)
            if asset.property_area_sqft is not None
            else None
        ),
        "current_policy_id": (
            str(asset.current_policy_id) if asset.current_policy_id else None
        ),
        "policy_number": linked.policy_number if linked else None,
        "insurer_name": linked.insurer_name if linked else None,
        "policy_status": linked.status if linked else None,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }
