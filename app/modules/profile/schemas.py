"""Profile and settings request schemas.

The update schema lists ONLY client-updatable fields; ``extra="forbid"`` rejects
unknown keys so mass-assignment of protected fields (role, status, is_deleted,
id, email) fails loudly rather than being silently applied. The frontend sends
``annualIncome``/``occupation``/``lifestyle`` at the top level and reads them
back under ``preferences`` — the response mapping handles that.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _reject_markup(value: str | None) -> str | None:
    if value and ("<" in value or ">" in value):
        raise ValueError("must not contain '<' or '>' characters")
    return value


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=1000)
    photo_url: str | None = Field(default=None, max_length=2000)
    date_of_birth: str | None = None
    pan_number: str | None = Field(default=None, max_length=10)
    aadhaar_number: str | None = Field(default=None, max_length=12)
    annual_income: float | str | None = Field(default=None, alias="annualIncome")
    occupation: str | None = Field(default=None, max_length=120)
    lifestyle: dict[str, Any] | None = None

    _v_name = field_validator("full_name")(_reject_markup)
    _v_address = field_validator("address")(_reject_markup)


class UpdateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: str | None = Field(default=None, max_length=16)
    notifications: bool | None = None
    dashboard_config: dict[str, Any] | None = None
