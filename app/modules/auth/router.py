"""Authentication routes.

Paths match the EXISTING frontend contract (src/constants/apiRoutes.ts):
  POST /auth/signup, /auth/signin, /auth/signout
  GET  /auth/session                      (session bootstrap)
  POST /auth/invite/verify
  POST /auth/forgot-password, /auth/reset-password

CSRF policy: signup/signin/forgot/reset/invite-verify are public bootstrap
endpoints that establish or do not require a session, so the double-submit CSRF
check does not apply (the session cookie is only issued on success). signout is
cookie-authenticated and therefore CSRF-protected. On every successful auth the
server issues a fresh session cookie AND a fresh CSRF cookie, and returns the
CSRF token in the JSON so the SPA can echo it immediately.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.cookies import clear_auth_cookies, set_csrf_cookie, set_session_cookie
from app.core.envelope import success
from app.core.security import CurrentUser, enforce_csrf, require_authenticated
from app.core.sessions import generate_csrf_token, issue_session_token
from app.db.session import get_session
from app.modules.auth import service
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    SignInRequest,
    SignUpRequest,
    VerifyInviteRequest,
)
from app.modules.auth.service import _load_profile
from app.modules.users_mapping import user_to_dict

logger = logging.getLogger("qura.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


async def _issue_auth(response: Response, settings: Settings, user) -> dict:  # type: ignore[no-untyped-def]
    """Issue session + CSRF cookies and build the {user, csrf_token} payload."""
    token = issue_session_token(str(user.id), settings.session_secret)
    csrf = generate_csrf_token()
    set_session_cookie(response, settings, token)
    set_csrf_cookie(response, settings, csrf)
    return {"user": user, "csrf_token": csrf}


@router.post("/signup")
async def signup(
    body: SignUpRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = await service.register_user(
        session,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        invite_token=body.invite_token,
        phone=body.phone,
    )
    profile = await _load_profile(session, user.id)
    payload = await _issue_auth(response, settings, user)
    return success(
        {"user": user_to_dict(user, profile), "csrf_token": payload["csrf_token"]},
        "Account created",
    )


@router.post("/signin")
async def signin(
    body: SignInRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = await service.authenticate(session, body.email, body.password)
    profile = await _load_profile(session, user.id)
    payload = await _issue_auth(response, settings, user)
    return success(
        {"user": user_to_dict(user, profile), "csrf_token": payload["csrf_token"]},
        "Signed in",
    )


@router.get("/session")
async def get_session_bootstrap(
    response: Response,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    # Rotate the CSRF cookie on bootstrap so the SPA always has a fresh token;
    # the session cookie is left as-is (no silent re-issue / sliding renewal).
    from app.core.errors import ApiError
    from app.modules.auth.service import get_user_by_email  # local import avoids cycle

    db_user = await get_user_by_email(session, user.email)
    if db_user is None:  # session valid but user vanished; treat as expired
        raise ApiError("Invalid or expired token", status_code=401)
    profile = await _load_profile(session, db_user.id)
    csrf = generate_csrf_token()
    set_csrf_cookie(response, settings, csrf)
    return success(
        {"user": user_to_dict(db_user, profile), "csrf_token": csrf},
        "Session active",
    )


@router.post("/signout")
async def signout(
    response: Response,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    db_user = await service.get_user_by_email(session, user.email)
    if db_user is not None:
        await service.revoke_all_sessions(session, db_user)
    clear_auth_cookies(response, settings)
    return success(None, "Signed out")


@router.post("/invite/verify")
async def verify_invite_route(
    body: VerifyInviteRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    invite = await service.verify_invite(session, body.token)
    return success({"valid": True, "email": invite.email}, "Invite valid")


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    raw = await service.create_password_reset(session, settings, body.email)
    # Generic response regardless of whether the account exists (no enumeration).
    data: dict = {"email": body.email}
    # Only surface the token in development, where no mailer is configured, so a
    # developer can complete the flow. Never in staging/production, never logged.
    if raw is not None and settings.environment.value == "development":
        data["debug_token"] = raw
    return success(data, "If the account exists, a reset link has been sent")


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await service.reset_password(
        session, email=body.email, raw_token=body.token, new_password=body.new_password
    )
    return success(None, "Password has been reset")
