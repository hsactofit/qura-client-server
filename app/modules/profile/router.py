"""Profile and settings routes.

Paths match the existing frontend contract:
  GET  /user/profile
  PUT  /user/profile/update
  GET  /user/settings
  PUT  /user/settings

The current user is taken only from the validated session (never a body/query
user id). Mutating routes require the double-submit CSRF check. Protected fields
(role, status, id, email, ownership) are not accepted by the update schema.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import success
from app.core.security import CurrentUser, enforce_csrf, require_authenticated
from app.db.session import get_session
from app.modules.profile import service
from app.modules.profile.schemas import UpdateProfileRequest, UpdateSettingsRequest
from app.modules.users_mapping import user_to_dict

router = APIRouter(prefix="/user", tags=["profile"])


@router.get("/profile")
async def get_profile(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    db_user = await service.load_user(session, user.id)
    profile = await service.load_profile(session, user.id)
    return success(user_to_dict(db_user, profile))


@router.put("/profile/update")
async def update_profile(
    body: UpdateProfileRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    db_user, profile = await service.update_profile(session, user.id, body)
    return success(user_to_dict(db_user, profile), "Profile updated")


@router.get("/settings")
async def get_settings_route(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await service.get_settings_row(session, user.id)
    return success(
        {
            "theme": row.theme,
            "notifications": row.notifications,
            "dashboard_config": row.dashboard_config,
        }
    )


@router.put("/settings")
async def update_settings_route(
    body: UpdateSettingsRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await service.update_settings(session, user.id, body)
    return success(
        {
            "theme": row.theme,
            "notifications": row.notifications,
            "dashboard_config": row.dashboard_config,
        },
        "Settings updated",
    )
