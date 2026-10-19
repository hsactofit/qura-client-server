"""Notification + announcement queries/mutations, scoped to the user.

Mark-read and delete operate only on the authenticated user's own notifications
(a 404 is returned for another user's id, which also avoids disclosure). The
read-time archive/delete side effect from the reference backend is intentionally
NOT reproduced; listing is pure-read.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.models.engagement import Announcement, Notification


async def list_notifications(
    session: AsyncSession, user_id: str
) -> list[Notification]:
    result = await session.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
    )
    return list(result.scalars().all())


async def active_announcements(session: AsyncSession) -> list[Announcement]:
    now = datetime.now(UTC)
    result = await session.execute(
        select(Announcement)
        .where(
            or_(Announcement.start_date.is_(None), Announcement.start_date <= now),
            or_(Announcement.end_date.is_(None), Announcement.end_date >= now),
        )
        .order_by(Announcement.created_at.desc())
    )
    return list(result.scalars().all())


async def unread_count(session: AsyncSession, user_id: str) -> int:
    result = await session.execute(
        select(Notification).where(
            and_(Notification.user_id == user_id, Notification.is_read.is_(False))
        )
    )
    return len(list(result.scalars().all()))


async def _get_owned(
    session: AsyncSession, user_id: str, notification_id: str
) -> Notification:
    result = await session.execute(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        raise ApiError("Notification not found", status_code=404)
    return notification


async def mark_read(
    session: AsyncSession, user_id: str, notification_id: str
) -> Notification:
    notification = await _get_owned(session, user_id, notification_id)
    notification.is_read = True
    await session.flush()
    return notification


async def mark_all_read(session: AsyncSession, user_id: str) -> int:
    result = await session.execute(
        select(Notification).where(
            and_(Notification.user_id == user_id, Notification.is_read.is_(False))
        )
    )
    rows = list(result.scalars().all())
    for row in rows:
        row.is_read = True
    await session.flush()
    return len(rows)


async def delete_notification(
    session: AsyncSession, user_id: str, notification_id: str
) -> None:
    notification = await _get_owned(session, user_id, notification_id)
    await session.delete(notification)
    await session.flush()


async def clear(session: AsyncSession, user_id: str, ids: list[str] | None) -> int:
    """Delete the given notifications (owned), or all of the user's if ids is None."""
    stmt = select(Notification).where(Notification.user_id == user_id)
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    if ids is not None:
        id_set = set(ids)
        rows = [r for r in rows if str(r.id) in id_set]
    for row in rows:
        await session.delete(row)
    await session.flush()
    return len(rows)
