"""Centralised error handling.

All failures are rendered through the same ``{success, message, error}`` envelope
so the frontend sees one consistent error shape. Unhandled exceptions never leak
internals: the client gets a generic message while the detail is logged server-side.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.envelope import error

logger = logging.getLogger("qura.error")


class ApiError(Exception):
    """Application error that maps to an envelope response.

    Raise this from services/routers instead of returning ad-hoc shapes.
    """

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        detail: object | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail


async def _api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error(exc.message, exc.detail),
    )


async def _http_exception_handler(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(status_code=exc.status_code, content=error(message))


def _safe_errors(raw: object) -> list[dict[str, object]]:
    """Make pydantic's error list JSON-serialisable and secret-free.

    A custom ``field_validator`` that raises ``ValueError`` puts the exception
    object in ``ctx['error']``, which is not JSON-serialisable; and ``input``
    can echo submitted values (potentially sensitive). Keep only the safe,
    stringified fields the frontend needs.
    """
    cleaned: list[dict[str, object]] = []
    for err in raw if isinstance(raw, list) else []:
        loc = err.get("loc", ()) if isinstance(err, dict) else ()
        cleaned.append(
            {
                "type": err.get("type") if isinstance(err, dict) else None,
                "loc": [str(part) for part in loc],
                "msg": str(err.get("msg", "")) if isinstance(err, dict) else "",
            }
        )
    return cleaned


async def _validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    # Field-level detail is sanitised: no raw inputs (possible PII) and no
    # non-serialisable ctx objects from custom validators.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error("Invalid request", _safe_errors(exc.errors())),
    )


async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.exception(
        "Unhandled exception processing %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error("Internal server error"),
    )


_Handler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def register_error_handlers(app: FastAPI) -> None:
    # Starlette types handlers against the base Exception; our handlers accept
    # the specific subclass they are registered for, so cast at registration.
    app.add_exception_handler(ApiError, cast(_Handler, _api_error_handler))
    app.add_exception_handler(
        StarletteHTTPException, cast(_Handler, _http_exception_handler)
    )
    app.add_exception_handler(
        RequestValidationError, cast(_Handler, _validation_exception_handler)
    )
    app.add_exception_handler(Exception, cast(_Handler, _unhandled_exception_handler))
