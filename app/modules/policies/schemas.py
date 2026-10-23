"""Policy request schemas.

``extra="forbid"`` blocks mass-assignment of server-owned fields (user_id, id,
timestamps, verification_status, document_file_id). The ``user_id`` / ownership
is ALWAYS derived from the authenticated session, never from request input.

Note: ``POST /policies/extract`` and ``POST /policies/upload`` accept
``multipart/form-data`` (a file plus flat form fields), so their inputs are
declared as ``Form`` parameters on the router rather than a JSON body model.
The models below cover the JSON endpoints (track / confirm / status).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PolicyTypeLiteral = Literal[
    "health", "motor", "life", "travel", "home", "accident", "business", "other"
]
PremiumFrequencyLiteral = Literal[
    "annual", "semi-annual", "quarterly", "monthly", "one-time"
]


class TrackPolicyRequest(BaseModel):
    """Create a local tracking record for a platform-originated proposal."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=100)
    product_enum: str | None = Field(default=None, max_length=100)
    policy_type: str | None = Field(default=None, max_length=50)
    insurer_name: str | None = Field(default=None, max_length=200)
    premium_amount: float | None = Field(default=None, ge=0)
    nominee_name: str | None = Field(default=None, max_length=200)
    nominee_relationship: str | None = Field(default=None, max_length=50)


class ConfirmPolicyRequest(BaseModel):
    """Finalise user-reviewed details for a tracked policy.

    Confirmation records that the USER reviewed the fields; it moves a policy to
    ``verification_status = user_confirmed``. It does NOT assert the insurer
    issued or verified anything.
    """

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=100)
    policy_number: str | None = Field(default=None, max_length=100)
    status: Literal["active", "expired", "lapsed", "pending", "cancelled"] | None = (
        None
    )


class PolicyStatusRequest(BaseModel):
    """Request a live insurer status sync for a tracked policy."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=100)
    external_proposal_id: str | None = Field(default=None, max_length=100)


PolicyRequestType = Literal["renewal", "callback", "policy_query", "claim_help"]


class PolicyRequest(BaseModel):
    """A client asking their advisor for help with one policy."""

    model_config = ConfigDict(extra="forbid")

    type: PolicyRequestType
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("message")
    @classmethod
    def _no_markup(cls, value: str | None) -> str | None:
        if value and ("<" in value or ">" in value):
            raise ValueError("must not contain '<' or '>' characters")
        return value.strip() if value else None
