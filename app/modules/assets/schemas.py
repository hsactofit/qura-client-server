"""Asset request schemas (create/update).

Fields and the ``asset_type`` set come from the frontend ``AssetCreateRequest``
type. ``extra="forbid"`` blocks mass-assignment of server-owned fields
(user_id, id, timestamps, current_policy_id).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AssetTypeLiteral = Literal["car", "two_wheeler", "home", "shop", "other"]


class AssetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_type: AssetTypeLiteral
    name: str | None = Field(default=None, max_length=200)
    registration_no: str | None = Field(default=None, max_length=32)
    make: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    year: int | None = Field(default=None, ge=1900, le=2200)
    fuel_type: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=40)
    chassis_no: str | None = Field(default=None, max_length=64)
    engine_no: str | None = Field(default=None, max_length=64)
    property_address: str | None = Field(default=None, max_length=1000)
    property_type: str | None = Field(default=None, max_length=40)
    property_area_sqft: float | None = Field(default=None, ge=0)


class AssetUpdateRequest(AssetCreateRequest):
    # Same shape; all fields optional for a partial update except asset_type,
    # which the frontend always sends. Kept required for consistency with create.
    pass
