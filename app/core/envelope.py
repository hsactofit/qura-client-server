"""The ``{success, message, data}`` response envelope.

This matches the contract the existing Qura frontend already consumes, so the
backend stays drop-in compatible without any frontend redesign.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Success envelope returned by every endpoint."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool = True
    message: str = "Success"
    data: T


class ErrorResponse(BaseModel):
    """Error envelope. ``error`` carries optional structured detail."""

    success: bool = False
    message: str
    error: Any = None


def success(data: Any = None, message: str = "Success") -> dict[str, Any]:
    """Build a success envelope as a plain dict for JSONResponse."""
    return {"success": True, "message": message, "data": data}


def error(message: str, detail: Any = None) -> dict[str, Any]:
    """Build an error envelope as a plain dict for JSONResponse."""
    return {"success": False, "message": message, "error": detail}
