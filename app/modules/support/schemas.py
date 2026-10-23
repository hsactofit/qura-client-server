"""Support request schemas with the reference contract's allowed values."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TicketCategory = Literal[
    "claim",
    "payment",
    "policy_change",
    "login",
    "general",
    "renewal",
    "callback",
    "policy_query",
    "claim_help",
]
TicketPriority = Literal["low", "medium", "high", "urgent"]


def _reject_markup(value: str) -> str:
    if "<" in value or ">" in value:
        raise ValueError("must not contain '<' or '>' characters")
    return value


class CreateTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=200)
    category: TicketCategory = "general"
    priority: TicketPriority = "medium"

    _v_subject = field_validator("subject")(_reject_markup)


class CreateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=5000)

    _v_message = field_validator("message")(_reject_markup)
