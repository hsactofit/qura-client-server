"""Claims, scoped to the authenticated user.

A client intimates a claim on the portal (with supporting documents in private
storage). The CRM picks it up through the shared database, a Qura advisor works
it with the insurer, and status changes flow back (app.modules.crm_sync).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import storage
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.uploads import DetectedFile
from app.db.models.claims import Claim, ClaimDocument
from app.db.models.files import StoredFile
from app.modules.policies.service import get_policy


async def list_claims(session: AsyncSession, user_id: str) -> list[Claim]:
    result = await session.execute(
        select(Claim)
        .where(Claim.user_id == user_id)
        .order_by(Claim.created_at.desc())
    )
    return list(result.scalars().all())


async def get_claim(session: AsyncSession, user_id: str, claim_id: str) -> Claim:
    result = await session.execute(
        select(Claim)
        .where(Claim.id == claim_id, Claim.user_id == user_id)
        .options(selectinload(Claim.documents))
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        raise ApiError("Claim not found", status_code=404)
    return claim


@dataclass
class ClaimUpload:
    data: bytes
    detected: DetectedFile
    name: str | None


def _claim_number() -> str:
    return f"QC-{datetime.now(UTC):%y%m%d}-{secrets.token_hex(3).upper()}"


async def file_claim(
    session: AsyncSession,
    settings: Settings,
    user_id: str,
    *,
    policy_id: str,
    claim_amount: float | None,
    description: str,
    incident_date: date | None,
    documents: list[ClaimUpload],
) -> Claim:
    """Intimate a claim on one of the user's own policies."""
    policy = await get_policy(session, user_id, policy_id)  # 404 if not owned
    if policy.status not in ("active", "expired"):
        raise ApiError("Claims can only be filed on an active policy", status_code=422)
    if incident_date and incident_date > datetime.now(UTC).date():
        raise ApiError("The incident date cannot be in the future", status_code=422)

    today = datetime.now(UTC).date().isoformat()
    claim = Claim(
        user_id=user_id,
        policy_id=policy.id,
        claim_number=_claim_number(),
        claim_amount=claim_amount,
        description=description,
        status="submitted",
        submission_date=incident_date,
        timeline=[
            {"status": "submitted", "date": today, "note": "Claim intimated on the Qura portal"}
        ],
    )
    session.add(claim)
    await session.flush()

    written: list[str] = []
    try:
        for doc in documents:
            key, sha256, size = storage.save_bytes(
                settings, purpose="claim", original_name=doc.name, data=doc.data
            )
            written.append(key)
            stored = StoredFile(
                owner_user_id=user_id,
                purpose="claim",
                storage_key=key,
                original_name=doc.name,
                content_type=doc.detected.content_type,
                size_bytes=size,
                sha256=sha256,
            )
            session.add(stored)
            await session.flush()
            session.add(
                ClaimDocument(
                    claim_id=claim.id,
                    file_id=stored.id,
                    name=doc.name,
                    content_type=doc.detected.content_type,
                )
            )
        await session.flush()
    except Exception:
        for key in written:
            storage.delete_quietly(settings, key)
        raise
    return claim
