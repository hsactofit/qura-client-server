"""Authentication and authorization dependencies.

``resolve_current_user`` reads the opaque session cookie, verifies its signature,
checks revocation against ``users.token_invalidated_at`` and session age, loads
the user from the database, and returns a ``CurrentUser`` (or ``None``).

``require_authenticated`` is the default-deny guard: any route depending on it
returns 401 unless a valid session resolved. ``require_roles`` adds role gating.
``enforce_csrf`` implements the double-submit CSRF check for cookie-authenticated
mutating requests.

Identity is derived EXCLUSIVELY from the validated session — never from a
client-supplied user id.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.sessions import constant_time_equals, parse_session_token
from app.db.models.identity import User
from app.db.session import get_session

_CSRF_PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated principal, derived only from a validated session."""

    id: str
    email: str
    role: str
    status: str


def _dt_to_epoch(value) -> int | None:  # type: ignore[no-untyped-def]
    if value is None:
        return None
    return int(value.timestamp())


async def resolve_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CurrentUser | None:
    """Resolve the principal from the session cookie, or None.

    Validation order: cookie present -> signature valid -> session not older
    than the configured lifetime -> user exists, active, not deleted -> session
    issued after any ``token_invalidated_at`` (revocation).
    """
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        return None

    parsed = parse_session_token(raw, settings.session_secret)
    if parsed is None:
        return None

    # Reject sessions older than the configured lifetime.
    if parsed.issued_at + settings.session_max_age_seconds < int(time.time()):
        return None

    result = await session.execute(select(User).where(User.id == parsed.user_id))
    user = result.scalar_one_or_none()
    if user is None or user.is_deleted or user.status != "ACTIVE":
        return None

    invalidated = _dt_to_epoch(user.token_invalidated_at)
    if invalidated is not None and parsed.issued_at <= invalidated:
        return None

    return CurrentUser(
        id=str(user.id), email=user.email, role=user.role, status=user.status
    )


async def require_authenticated(
    user: CurrentUser | None = Depends(resolve_current_user),
) -> CurrentUser:
    """Default-deny guard: 401 unless a valid session resolved."""
    if user is None:
        raise ApiError("Invalid or expired token", status_code=401)
    return user


def require_roles(*allowed: str):  # type: ignore[no-untyped-def]
    """Dependency requiring one of ``allowed`` roles (authenticated first)."""
    allowed_roles: Sequence[str] = allowed

    async def _guard(
        user: CurrentUser = Depends(require_authenticated),
    ) -> CurrentUser:
        if user.role not in allowed_roles:
            raise ApiError("Insufficient permissions", status_code=403)
        return user

    return _guard


async def enforce_csrf(
    request: Request, settings: Settings = Depends(get_settings)
) -> None:
    """Double-submit CSRF check for cookie-authenticated mutating requests.

    Skipped when a request is not state-changing. When the session cookie is
    present on a mutating request, the ``X-CSRF-Token`` header must equal the
    ``qura_client_csrf`` cookie (constant-time compare). Requests authenticated
    some other way (none in Phase 3) are unaffected.
    """
    if request.method not in _CSRF_PROTECTED_METHODS:
        return
    if settings.session_cookie_name not in request.cookies:
        # No session cookie -> not a cookie-authenticated mutation; the endpoint
        # itself enforces auth. CSRF double-submit does not apply.
        return
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get("x-csrf-token")
    if (
        not cookie_token
        or not header_token
        or not constant_time_equals(cookie_token, header_token)
    ):
        raise ApiError("CSRF validation failed", status_code=403)
