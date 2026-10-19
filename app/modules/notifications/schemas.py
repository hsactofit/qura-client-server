"""Notification request schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] | None = None
