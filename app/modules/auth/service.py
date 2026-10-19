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


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str | None,
    invite_token: str | None,
) -> User:
    """Register a user via a valid invite. Role comes from the invite only.

    A client-supplied role is impossible here: the role is read from the invite
    record, never from the request body.
    """
    norm_email = normalize_email(email)

    if not invite_token:
        raise ApiError("A valid invite is required to register", status_code=400)
    invite = await verify_invite(session, invite_token)
    if normalize_email(invite.email) != norm_email:
        raise ApiError("Invite email does not match", status_code=400)

    user = User(
        email=norm_email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=invite.role,  # authoritative: never from the client body
        status="ACTIVE",
    )
    session.add(user)
    invite.is_used = True
    try:
        await session.flush()
    except IntegrityError as exc:
        # Concurrent duplicate registration: the unique email constraint fires.
        await session.rollback()
        raise ApiError("An account with this email already exists", status_code=409) from exc

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
