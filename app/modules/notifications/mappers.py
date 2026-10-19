"""ORM -> frontend mapping for notifications and announcements."""

from __future__ import annotations

from typing import Any

from app.db.models.engagement import Announcement, Notification


def notification_to_dict(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "user_id": str(n.user_id),
        "title": n.title,
        "message": n.message,
        "type": n.type,
        "is_read": n.is_read,
        "reference_id": n.reference_id,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def announcement_to_dict(a: Announcement) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "title": a.title,
        "message": a.message,
        "type": a.type,
        "start_date": a.start_date.isoformat() if a.start_date else None,
        "end_date": a.end_date.isoformat() if a.end_date else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
