"""Profile and settings persistence logic.

Operates strictly on the user resolved from the session. Only whitelisted fields
are written; account/privilege fields (role, status, is_deleted, email, id) are
never touched here. Account-level fields live on ``users``; PII and soft fields
live on ``user_profiles``; settings live on ``user_settings``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.models.identity import User, UserProfile, UserSetting
from app.modules.profile.schemas import UpdateProfileRequest, UpdateSettingsRequest


async def load_user(session: AsyncSession, user_id: str) -> User:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ApiError("User not found", status_code=404)
    return user


async def load_profile(session: AsyncSession, user_id: str) -> UserProfile | None:
    result = await session.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _get_or_create_profile(session: AsyncSession, user_id: str) -> UserProfile:
    profile = await load_profile(session, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id)
        session.add(profile)
    return profile


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ApiError("Invalid date_of_birth (expected YYYY-MM-DD)", status_code=400) from exc


def _parse_income(value: float | str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ApiError("Invalid annualIncome", status_code=400) from exc


async def update_profile(
    session: AsyncSession, user_id: str, body: UpdateProfileRequest
) -> tuple[User, UserProfile]:
    """Apply whitelisted updates. Only provided fields are changed."""
    user = await load_user(session, user_id)
    profile = await _get_or_create_profile(session, user_id)

    provided = body.model_dump(exclude_unset=True, by_alias=False)

    # Account-level fields on `users`.
    if "full_name" in provided:
        user.full_name = body.full_name
    if "phone" in provided:
        user.phone = body.phone
    if "address" in provided:
        user.address = body.address
    if "photo_url" in provided:
        user.photo_url = body.photo_url

    # PII / soft fields on `user_profiles`.
    if "date_of_birth" in provided:
        profile.date_of_birth = _parse_date(body.date_of_birth)
    if "pan_number" in provided:
        profile.pan_number = body.pan_number
    if "aadhaar_number" in provided:
        profile.aadhaar_number = body.aadhaar_number
    if "annual_income" in provided:
        profile.annual_income = _parse_income(body.annual_income)
    if "occupation" in provided:
        profile.occupation = body.occupation
    if "lifestyle" in provided:
        profile.lifestyle = body.lifestyle

    await session.flush()
    return user, profile


async def get_settings_row(session: AsyncSession, user_id: str) -> UserSetting:
    result = await session.execute(
        select(UserSetting).where(UserSetting.user_id == user_id)
    )
    settings_row = result.scalar_one_or_none()
    if settings_row is None:
        # Set defaults explicitly so the response is correct in the same request
        # without relying on a post-insert DB refresh.
        settings_row = UserSetting(
            user_id=user_id, theme="system", notifications=True
        )
        session.add(settings_row)
        await session.flush()
    return settings_row


async def update_settings(
    session: AsyncSession, user_id: str, body: UpdateSettingsRequest
) -> UserSetting:
    settings_row = await get_settings_row(session, user_id)
    provided = body.model_dump(exclude_unset=True)
    if "theme" in provided and body.theme is not None:
        settings_row.theme = body.theme
    if "notifications" in provided and body.notifications is not None:
        settings_row.notifications = body.notifications
    if "dashboard_config" in provided:
        settings_row.dashboard_config = body.dashboard_config
    await session.flush()
    return settings_row
