"""Family-member request schemas.

Fields from the frontend family CRUD contract: name, relationship, dob, gender,
phone?, email?. ``relationship`` is the wire name; it maps to the model's
``relation`` attribute (which avoids the SQLAlchemy ``relationship`` clash).
``extra="forbid"`` blocks server-owned fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class FamilyMemberCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    relationship: str | None = Field(default=None, max_length=50)
    dob: str | None = None
    gender: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None


class FamilyMemberUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    relationship: str | None = Field(default=None, max_length=50)
    dob: str | None = None
    gender: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
