"""Request/response schemas for authentication.

Field names and aliases match the existing frontend contract exactly:
- signup/signin accept ``email``/``password`` (and ``fullName``/``inviteToken``
  via camelCase aliases on signup).
- the auth payload returns ``{user, csrf_token}``.
- the user object exposes ``date_of_birth``/``pan_number``/``aadhaar_number`` at
  the top level (composed from the user_profiles model) plus a ``preferences``
  object the Profile page reads.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 200


def _reject_markup(value: str | None) -> str | None:
    if value and ("<" in value or ">" in value):
        raise ValueError("must not contain '<' or '>' characters")
    return value


class SignUpRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    email: EmailStr
    password: str = Field(min_length=_MIN_PASSWORD_LENGTH, max_length=_MAX_PASSWORD_LENGTH)
    full_name: str | None = Field(default=None, alias="fullName", max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    invite_token: str | None = Field(default=None, alias="inviteToken")

    _v_name = field_validator("full_name")(_reject_markup)


class SignInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=_MAX_PASSWORD_LENGTH)


class VerifyInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    email: EmailStr
    token: str
    new_password: str = Field(
        alias="newPassword", min_length=_MIN_PASSWORD_LENGTH, max_length=_MAX_PASSWORD_LENGTH
    )


class UserOut(BaseModel):
    """User object the frontend AuthContext consumes."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str | None = None
    phone: str | None = None
    photo_url: str | None = None
    address: str | None = None
    role: str
    date_of_birth: str | None = None
    pan_number: str | None = None
    aadhaar_number: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)


class AuthPayload(BaseModel):
    user: UserOut
    csrf_token: str


class ForgotPasswordData(BaseModel):
    email: str
    # debug_token is only ever populated in development when no mailer exists;
    # never returned otherwise. See the auth service for the strict gating.
    debug_token: str | None = None
