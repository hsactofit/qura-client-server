"""Notification routes.

  GET    /notifications                 {notifications, announcements}
  POST   /notifications/{id}/read       mark one read (ownership-enforced)
  POST   /notifications/read-all        mark all read
  POST   /notifications/clear           delete given ids (or all)
  DELETE /notifications/{id}            delete one (ownership-enforced)

Creating notifications/announcements is an admin capability and is NOT exposed
here (it was unauthenticated and abusable in the reference backend).
Mutations require CSRF.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import success
from app.core.security import CurrentUser, enforce_csrf, require_authenticated
from app.db.session import get_session
from app.modules.notifications import service
from app.modules.notifications.mappers import (
    announcement_to_dict,
    notification_to_dict,
)
from app.modules.notifications.schemas import ClearRequest

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    notifications = await service.list_notifications(session, user.id)
    announcements = await service.active_announcements(session)
    return success(
        {
            "notifications": [notification_to_dict(n) for n in notifications],
            "announcements": [announcement_to_dict(a) for a in announcements],
            "unread_count": sum(1 for n in notifications if not n.is_read),
        }
    )


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    notification = await service.mark_read(session, user.id, notification_id)
    return success(notification_to_dict(notification), "Marked as read")


@router.post("/read-all")
async def mark_all_read(
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    count = await service.mark_all_read(session, user.id)
    return success({"updated": count}, "All notifications marked read")


@router.post("/clear")
async def clear(
    body: ClearRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    count = await service.clear(session, user.id, body.ids)
    return success({"cleared": count}, "Notifications cleared")


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await service.delete_notification(session, user.id, notification_id)
    return success(None, "Notification deleted")


@router.get("/unread-count")
async def unread_count(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    count = await service.unread_count(session, user.id)
    return success({"unread_count": count})
