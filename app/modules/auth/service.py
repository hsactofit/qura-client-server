"""Authentication business logic (no FastAPI/HTTP concerns here).

Separated from routing so it can be unit-tested with a mocked/overridden async
session. Enforces: email normalisation, invite-only registration, Argon2id
hashing, generic auth errors, single-use reset tokens stored hashed, and
user-level session revocation via ``users.token_invalidated_at``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.passwords import hash_password, verify_password
from app.core.tokens import generate_raw_token, hash_token
from app.db.models.identity import Invite, PasswordResetToken, User, UserProfile

logger = logging.getLogger("qura.auth")

_GENERIC_AUTH_ERROR = "Invalid email or password"


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def _load_profile(session: AsyncSession, user_id) -> UserProfile | None:  # type: ignore[no-untyped-def]
    result = await session.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def verify_invite(session: AsyncSession, raw_token: str) -> Invite:
    """Return a valid, unused, unexpired invite or raise ApiError(400)."""
    token_hash = hash_token(raw_token)
    result = await session.execute(
        select(Invite).where(Invite.token_hash == token_hash)
    )
    invite = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if invite is None or invite.is_used or invite.expires_at <= now:
        raise ApiError("Invalid or expired invite", status_code=400)
    return invite


def normalize_mobile(raw: str | None) -> str | None:
    """Indian mobile numbers to E.164 (+91XXXXXXXXXX), the CRM's contact format.

    Returns ``None`` for an empty value; raises ApiError(422) for anything that
    is not a valid 10-digit Indian mobile (optionally prefixed 0, 91 or +91).
    """
    if raw is None or not raw.strip():
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise ApiError("Enter a valid 10-digit Indian mobile number", status_code=422)
    return f"+91{digits}"


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str | None,
    invite_token: str | None,
    phone: str | None = None,
) -> User:
    """Register a portal user.

    Anyone may sign up as a client (role ``USER``); that is how policyholders
    join and upload their policies. Staff roles still need an invite, and the
    role is then read from the invite record — never from the request body.
    """
    norm_email = normalize_email(email)
    norm_phone = normalize_mobile(phone)

    invite: Invite | None = None
    if invite_token:
        invite = await verify_invite(session, invite_token)
        if normalize_email(invite.email) != norm_email:
            raise ApiError("Invite email does not match", status_code=400)

    if await get_user_by_email(session, norm_email) is not None:
        raise ApiError("An account with this email already exists", status_code=409)

    user = User(
        email=norm_email,
        password_hash=hash_password(password),
        full_name=full_name,
        phone=norm_phone,
        role=invite.role if invite is not None else "USER",
        status="ACTIVE",
    )
    session.add(user)
    if invite is not None:
        invite.is_used = True
    try:
        await session.flush()
    except IntegrityError as exc:
        # Concurrent duplicate registration, or a mobile already in use.
        await session.rollback()
        raise ApiError(
            "An account with this email or mobile number already exists",
            status_code=409,
        ) from exc

    # Create the empty 1:1 profile row so later profile updates have a target.
    session.add(UserProfile(user_id=user.id))
    await session.flush()
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    """Return the user on valid credentials, else raise a generic 401.

    The same error and comparable work are done whether or not the account
    exists, to avoid account enumeration.
    """
    norm_email = normalize_email(email)
    user = await get_user_by_email(session, norm_email)

    if user is None:
        # Perform a dummy hash verification to equalise timing.
        verify_password(
            "$argon2id$v=19$m=65536,t=3,p=4$"  # structurally valid dummy
            "c29tZXNhbHRzb21lc2FsdA$"
            "0000000000000000000000000000000000000000000",
            password,
        )
        raise ApiError(_GENERIC_AUTH_ERROR, status_code=401)

    if not verify_password(user.password_hash, password):
        raise ApiError(_GENERIC_AUTH_ERROR, status_code=401)

    if user.is_deleted or user.status != "ACTIVE":
        # Do not reveal account state specifics.
        raise ApiError(_GENERIC_AUTH_ERROR, status_code=401)

    return user


async def revoke_all_sessions(session: AsyncSession, user: User) -> None:
    """Bump ``token_invalidated_at`` so all outstanding sessions are rejected."""
    user.token_invalidated_at = datetime.now(UTC)
    await session.flush()


async def create_password_reset(
    session: AsyncSession, settings: Settings, email: str
) -> str | None:
    """Create a reset token for ``email`` if the account exists.

    Returns the RAW token when a user exists (for the caller to deliver), else
    None. The caller must NOT reveal which case occurred to the client.
    """
    user = await get_user_by_email(session, normalize_email(email))
    if user is None:
        return None
    raw = generate_raw_token()
    expires = datetime.now(UTC) + timedelta(seconds=settings.password_reset_ttl_seconds)
    session.add(
        PasswordResetToken(
            user_id=user.id, token_hash=hash_token(raw), expires_at=expires
        )
    )
    await session.flush()
    return raw


async def reset_password(
    session: AsyncSession, *, email: str, raw_token: str, new_password: str
) -> None:
    """Consume a single-use reset token and set the new password atomically."""
    user = await get_user_by_email(session, normalize_email(email))
    if user is None:
        raise ApiError("Invalid or expired reset token", status_code=400)

    token_hash = hash_token(raw_token)
    result = await session.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.user_id == user.id,
        )
    )
    token = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise ApiError("Invalid or expired reset token", status_code=400)

    token.used_at = now
    user.password_hash = hash_password(new_password)
    # End all existing sessions on password change.
    user.token_invalidated_at = now
    await session.flush()
