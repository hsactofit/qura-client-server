"""Cookie helpers for the session and CSRF cookies.

Cookie policy
-------------
- Session cookie (``qura_client_session``): HttpOnly, SameSite=Lax, path=/,
  ``Secure`` outside development. Invisible to JS.
- CSRF cookie (``qura_client_csrf``): readable by JS (NOT HttpOnly) so the SPA
  can echo it back as the ``X-CSRF-Token`` header (double-submit); same
  ``Secure``/SameSite policy otherwise.

``Secure`` is always set except in the development/test environments, so local
HTTP works without weakening the deployed posture. Max-age matches the session
lifetime from settings.
"""

from __future__ import annotations

from fastapi import Response

from app.core.config import Environment, Settings


def _secure_flag(settings: Settings) -> bool:
    return settings.environment not in (Environment.DEVELOPMENT, Environment.TEST)


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age_seconds,
        path="/",
        httponly=True,
        secure=_secure_flag(settings),
        samesite="lax",
    )


def set_csrf_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        max_age=settings.session_max_age_seconds,
        path="/",
        httponly=False,  # must be readable by the SPA for double-submit
        secure=_secure_flag(settings),
        samesite="lax",
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
