"""Call-back requests: the one way a client asks their advisor for something.

The client picks what it is about (a fixed list, not free text), the policy or
insurance type it concerns, and when they want the call. The CRM turns each
request into a task for the advisor, due at that time.

Duplicates: a client can have only one open request per topic and policy (per
insurance type for quotations). A second one is refused with 409 and the id of
the open request, so the client is pointed at it instead of filing it again.
Endorsement uploads are the exception: a different endorsement copy for the
same policy is a new request; the same file again is a duplicate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.uploads import DetectedFile
from app.db.models.files import StoredFile
from app.db.models.policies import Policy
from app.db.models.support import SupportTicket, TicketMessage

OPEN_STATUSES = ("open", "in_progress")

INDIA = ZoneInfo("Asia/Kolkata")
# Advisors call Monday to Saturday, 09:00 to 19:00 India time. The last slot
# starts at 18:30 so the call fits inside working hours.
CALL_DAYS = frozenset(range(0, 6))  # Monday=0 .. Saturday=5
CALL_START = time(9, 0)
CALL_LAST_SLOT = time(18, 30)
MIN_NOTICE = timedelta(minutes=30)
MAX_AHEAD = timedelta(days=30)


@dataclass(frozen=True)
class RequestKind:
    label: str
    needs_policy: bool
    priority: str


# Feedback-defined categories. "payment" and "general" reuse existing values.
REQUEST_KINDS: dict[str, RequestKind] = {
    "quotation": RequestKind("Quotation request", needs_policy=False, priority="medium"),
    "policy_correction": RequestKind("Policy correction", needs_policy=True, priority="high"),
    "endorsement": RequestKind("Endorsement", needs_policy=True, priority="high"),
    "renewal": RequestKind("Renewal", needs_policy=True, priority="high"),
    "payment": RequestKind("Payment-related query", needs_policy=False, priority="medium"),
    "general": RequestKind("Other", needs_policy=False, priority="medium"),
}

INSURANCE_TYPES = {
    "motor": "Motor",
    "health": "Health",
    "life": "Life",
    "travel": "Travel",
    "home": "Home",
    "accident": "Personal accident",
    "business": "Business",
    "other": "Other",
}


def validate_callback_time(value: datetime, *, now: datetime | None = None) -> datetime:
    """Reject times outside working hours, too soon, or too far ahead (422)."""
    if value.tzinfo is None:
        raise ApiError("Preferred call-back time must include a timezone", status_code=422)
    now = now or datetime.now(UTC)
    if value < now + MIN_NOTICE:
        raise ApiError(
            "Choose a call-back time at least 30 minutes from now", status_code=422
        )
    if value > now + MAX_AHEAD:
        raise ApiError(
            "Choose a call-back time within the next 30 days", status_code=422
        )
    local = value.astimezone(INDIA)
    if local.weekday() not in CALL_DAYS:
        raise ApiError(
            "Advisors call Monday to Saturday. Choose another day.", status_code=422
        )
    if not (CALL_START <= local.time() <= CALL_LAST_SLOT):
        raise ApiError(
            "Choose a time between 9:00 AM and 6:30 PM (India time)", status_code=422
        )
    return value.astimezone(UTC)


async def lock_user_requests(session: AsyncSession, user_id: str) -> None:
    """Serialise request creation per client so a double submit can't slip past
    the duplicate check. Postgres only; the transaction releases the lock."""
    bind = getattr(session, "bind", None)
    if bind is None or bind.dialect.name != "postgresql":
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"support-request:{user_id}"},
    )


def duplicate_error(existing: SupportTicket, label: str) -> ApiError:
    return ApiError(
        f"You already have an open {label.lower()} request. "
        "Your advisor will call you about it; add any details to that request.",
        status_code=409,
        detail={"code": "DUPLICATE_REQUEST", "ticket_id": str(existing.id)},
    )


async def _open_tickets(
    session: AsyncSession, user_id: str, category: str
) -> list[SupportTicket]:
    result = await session.execute(
        select(SupportTicket).where(
            SupportTicket.user_id == user_id,
            SupportTicket.category == category,
            SupportTicket.status.in_(OPEN_STATUSES),
        )
    )
    return list(result.scalars().all())


async def _file_sha(session: AsyncSession, file_id: object) -> str | None:
    if file_id is None:
        return None
    result = await session.execute(select(StoredFile).where(StoredFile.id == file_id))
    stored = result.scalar_one_or_none()
    return stored.sha256 if stored is not None else None


async def create_request(
    session: AsyncSession,
    settings: Settings,
    user_id: str,
    *,
    kind: str,
    preferred_callback_at: datetime,
    policy_id: str | None,
    insurance_type: str | None,
    message: str | None,
    document: bytes | None = None,
    detected: DetectedFile | None = None,
    original_name: str | None = None,
) -> SupportTicket:
    spec = REQUEST_KINDS.get(kind)
    if spec is None:
        raise ApiError("Choose what the call back is about", status_code=422)
    when = validate_callback_time(preferred_callback_at)

    policy: Policy | None = None
    if policy_id:
        result = await session.execute(
            select(Policy).where(Policy.id == policy_id, Policy.user_id == user_id)
        )
        policy = result.scalar_one_or_none()
        if policy is None:
            raise ApiError("Policy not found", status_code=404)
    elif spec.needs_policy:
        raise ApiError(f"Choose the policy this {spec.label.lower()} is about", status_code=422)

    if kind == "quotation":
        if insurance_type not in INSURANCE_TYPES:
            raise ApiError("Choose the type of insurance you want a quote for", status_code=422)
    else:
        insurance_type = None
    if kind == "general" and not message:
        raise ApiError("Tell us briefly what the call back is about", status_code=422)
    if document is not None and kind != "endorsement":
        raise ApiError("Only endorsement requests take a document", status_code=422)

    await lock_user_requests(session, user_id)
    sha = storage.sha256_hex(document) if document is not None else None
    for existing in await _open_tickets(session, user_id, kind):
        same_subject = (
            str(existing.insurance_type) == str(insurance_type)
            if kind == "quotation"
            else str(existing.policy_id) == str(policy.id if policy else None)
        )
        if not same_subject:
            continue
        # A different endorsement copy for the same policy is new work.
        if (
            kind == "endorsement"
            and sha is not None
            and await _file_sha(session, existing.document_file_id) != sha
        ):
            continue
        raise duplicate_error(existing, spec.label)

    stored_file: StoredFile | None = None
    storage_key: str | None = None
    if document is not None:
        storage_key, sha, size = storage.save_bytes(
            settings, purpose="endorsement", original_name=original_name, data=document
        )
    try:
        if storage_key is not None:
            stored_file = StoredFile(
                owner_user_id=user_id,
                purpose="endorsement",
                storage_key=storage_key,
                original_name=original_name,
                content_type=detected.content_type if detected else None,
                size_bytes=size,
                sha256=sha,
            )
            session.add(stored_file)
            await session.flush()

        about = (
            INSURANCE_TYPES[insurance_type]
            if insurance_type
            else " ".join(p for p in (policy.insurer_name, policy.policy_number) if p)
            if policy
            else ""
        )
        ticket = SupportTicket(
            user_id=user_id,
            policy_id=policy.id if policy else None,
            subject=(f"{spec.label}: {about}" if about else spec.label)[:200],
            category=kind,
            priority=spec.priority,
            status="open",
            preferred_callback_at=when,
            insurance_type=insurance_type,
            document_file_id=stored_file.id if stored_file else None,
        )
        session.add(ticket)
        await session.flush()
        if message:
            session.add(TicketMessage(ticket_id=ticket.id, sender_id=user_id, message=message))
            await session.flush()
    except Exception:
        if storage_key is not None:
            storage.delete_quietly(settings, storage_key)
        raise
    return ticket
