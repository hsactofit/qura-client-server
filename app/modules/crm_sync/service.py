"""Pull advisor work from the CRM into the portal.

The portal (``client`` schema) and the CRM (``crm`` schema) share the
``qura_main`` database. Each service writes only its own schema and READS the
other's, so neither can corrupt the other. This module is the portal's half:

- **Policies.** Every CRM policy on an account linked to a portal user
  (``crm.accounts.client_user_id``) is mirrored into ``client.policies``:
  * a policy the client uploaded (``crm.policies.client_policy_id``) is updated
    in place once an advisor verifies it (``advisor_verified``);
  * a policy an advisor added in the CRM appears as ``policy_source='advisor'``,
    with its document downloadable through the CRM's internal endpoint.
- **Advisor replies** to client requests (``crm.activities`` of type
  ``CLIENT_REPLY``) become ticket messages.
- **Request status** follows the CRM task the request turned into.
- **Claims** filed on the portal follow the CRM claim's status (with notes in
  the claim timeline and a notification on each change).

Sync is state-based, not event-based: each run compares ``crm.policies.updated_at``
with ``client.policies.crm_synced_at`` (and message ``external_ref`` ids), so a
missed run, a restart or a crash loses nothing; the next run catches up.
Each item is applied in its own savepoint so one bad row cannot block the rest.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.claims import Claim
from app.db.models.engagement import Notification
from app.db.models.files import StoredFile
from app.db.models.policies import Policy
from app.db.models.support import SupportTicket, TicketMessage
from app.modules.policies.coverage import (
    CATEGORY_TO_TYPE,
    insurer_display_name,
    merge_details,
    normalize_details,
)

logger = logging.getLogger("qura.crm_sync")

# Storage keys for files that live in the CRM, not on this service's disk.
CRM_STORAGE_PREFIX = "crm:"

_BATCH = 200

# CRM PolicyStatus enum -> portal policy status.
_STATUS = {
    "active": "active",
    "expired": "expired",
    "cancelled": "cancelled",
    "lapsed": "lapsed",
    "superseded": "expired",
    "draft": "pending",
    "unknown": "pending",
}

# CRM TaskStatus -> portal ticket status (only forward moves are applied).
_TICKET_STATUS = {
    "IN_PROGRESS": "in_progress",
    "COMPLETED": "resolved",
    "CANCELLED": "closed",
}
_TICKET_ORDER = ("open", "in_progress", "resolved", "closed")


async def crm_schema_ready(session: AsyncSession) -> bool:
    """True when the CRM schema (with the link columns) is readable here."""
    found = await session.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'crm' AND ("
            "(table_name = 'accounts' AND column_name = 'client_user_id') OR "
            "(table_name = 'policies' AND column_name = 'client_policy_id') OR "
            "(table_name = 'claims' AND column_name = 'client_claim_id'))"
        )
    )
    return found.scalar_one() == 3


@dataclass
class SyncResult:
    policies: int = 0
    messages: int = 0
    tickets: int = 0
    claims: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.policies or self.messages or self.tickets or self.claims)


async def sync_once(session: AsyncSession) -> SyncResult:
    """One full pass. The caller commits."""
    result = SyncResult()
    if not await crm_schema_ready(session):
        return result
    result.policies = await _pull_policies(session)
    result.messages = await _pull_replies(session)
    result.tickets = await _pull_ticket_status(session)
    result.claims = await _pull_claims(session)
    return result


# --- Policies ----------------------------------------------------------------

_POLICY_SQL = text(
    """
    SELECT p.id, p.client_policy_id, a.client_user_id AS user_id,
           p.insurer_id, p.category_id, p.policy_number,
           p.start_date, p.expiry_date, p.premium, p.sum_insured,
           p.status::text AS status, p.verified_at, p.details,
           p.updated_at AT TIME ZONE 'UTC' AS updated_at,
           d.id AS document_id, d.classification AS document_name,
           d.mime AS document_mime, d.size_bytes AS document_size,
           d.checksum AS document_sha256
    FROM crm.policies p
    JOIN crm.accounts a ON a.id = p.account_id
    JOIN client.users u ON u.id = a.client_user_id
    LEFT JOIN LATERAL (
        SELECT id, classification, mime, size_bytes, checksum
        FROM crm.documents WHERE policy_id = p.id AND type = 'POLICY_PDF'
        ORDER BY created_at DESC LIMIT 1
    ) d ON true
    WHERE NOT EXISTS (
        SELECT 1 FROM client.policies cp
        WHERE (cp.crm_policy_id = p.id OR cp.id = p.client_policy_id)
          AND cp.crm_synced_at >= p.updated_at AT TIME ZONE 'UTC'
    )
    ORDER BY p.updated_at
    LIMIT :batch
    """
)


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _money(value: Any) -> Decimal | None:
    return Decimal(str(round(float(value), 2))) if value is not None else None


async def _pull_policies(session: AsyncSession) -> int:
    rows = (await session.execute(_POLICY_SQL, {"batch": _BATCH})).mappings().all()
    applied = 0
    for row in rows:
        try:
            async with session.begin_nested():
                await _apply_policy(session, row)
            applied += 1
        except Exception:  # noqa: BLE001 - one bad row must not stop the rest
            logger.exception("crm sync: policy %s failed", row["id"])
    return applied


async def _find_target(session: AsyncSession, row: Any) -> Policy | None:
    if row["client_policy_id"] is not None:
        found = await session.get(Policy, row["client_policy_id"])
        if found is not None:
            return found
    linked = await session.execute(
        select(Policy).where(Policy.crm_policy_id == row["id"])
    )
    found = linked.scalar_one_or_none()
    if found is not None:
        return found
    # The same policy the client uploaded separately: same number, same person.
    if row["policy_number"]:
        same = await session.execute(
            select(Policy).where(
                Policy.user_id == row["user_id"],
                Policy.policy_number == row["policy_number"],
                Policy.crm_policy_id.is_(None),
            )
        )
        return same.scalar_one_or_none()
    return None


async def _policy_number_taken(
    session: AsyncSession, number: str | None, own_id: uuid.UUID | None
) -> bool:
    if not number:
        return False
    stmt = select(Policy.id).where(Policy.policy_number == number)
    if own_id is not None:
        stmt = stmt.where(Policy.id != own_id)
    return (await session.execute(stmt.limit(1))).first() is not None


async def _apply_policy(session: AsyncSession, row: Any) -> None:
    user_id = row["user_id"]
    target = await _find_target(session, row)
    if target is not None and target.user_id != user_id:
        logger.warning("crm sync: policy %s belongs to another user; skipped", row["id"])
        return

    crm_details = row["details"] if isinstance(row["details"], dict) else {}
    coverage = crm_details.get("coverage")
    verified = row["verified_at"] is not None
    fields = {
        "policy_number": row["policy_number"],
        "policy_type": CATEGORY_TO_TYPE.get(row["category_id"] or "", "other"),
        "insurer_name": insurer_display_name(row["insurer_id"]),
        "coverage_amount": _money(row["sum_insured"]),
        "premium_amount": _money(row["premium"]),
        "start_date": _day(row["start_date"]),
        "end_date": _day(row["expiry_date"]),
        "status": _STATUS.get(row["status"], "active"),
    }
    created = False
    if target is None:
        created = True
        target = Policy(
            user_id=user_id,
            policy_source="advisor",
            verification_status="advisor_verified" if verified else "self_reported",
            details=normalize_details(coverage),
            benefits=[],
            exclusions=[],
        )
        session.add(target)

    was_verified = target.verification_status == "advisor_verified"
    client_originated = target.policy_source != "advisor"
    # The client's own upload keeps its values until an advisor verifies it;
    # advisor-added policies always mirror the CRM.
    if created or verified or not client_originated:
        if await _policy_number_taken(session, fields["policy_number"], target.id):
            logger.warning("crm sync: policy number already used; kept the old one")
            fields.pop("policy_number")
        for key, value in fields.items():
            if value is not None or not client_originated:
                setattr(target, key, value)
        if coverage:
            benefits = coverage.get("benefits")
            exclusions = coverage.get("exclusions")
            if isinstance(benefits, list) and benefits:
                target.benefits = benefits
            if isinstance(exclusions, list) and exclusions:
                target.exclusions = exclusions
            target.details = merge_details(target.details, coverage)
    if verified:
        target.verification_status = "advisor_verified"

    target.crm_policy_id = row["id"]
    target.crm_synced_at = row["updated_at"]
    await session.flush()

    if target.document_file_id is None and row["document_id"] is not None:
        stored = StoredFile(
            owner_user_id=user_id,
            purpose="policy",
            storage_key=f"{CRM_STORAGE_PREFIX}{row['document_id']}",
            original_name=row["document_name"],
            content_type=row["document_mime"],
            size_bytes=row["document_size"],
            sha256=row["document_sha256"],
        )
        session.add(stored)
        await session.flush()
        target.document_file_id = stored.id
        target.document_original_name = target.document_original_name or row["document_name"]

    label = f"{target.insurer_name or 'Your'} {target.policy_type or ''} policy".strip()
    if created:
        _notify(
            session,
            user_id,
            "New policy added by your advisor",
            f"{label} is now in your Qura account.",
            "policy",
            target.id,
        )
    elif verified and not was_verified:
        _notify(
            session,
            user_id,
            "Policy verified",
            f"Your Qura advisor checked and verified {label}.",
            "success",
            target.id,
        )


# --- Advisor replies -------------------------------------------------------

_REPLY_SQL = text(
    """
    SELECT act.id, act.related_id AS ticket_id, act.summary,
           act.occurred_at AT TIME ZONE 'UTC' AS occurred_at,
           u.name AS advisor_name, t.user_id
    FROM crm.activities act
    JOIN client.support_tickets t ON t.id = act.related_id
    LEFT JOIN crm.users u ON u.id = act.actor_user_id
    WHERE act.type = 'CLIENT_REPLY' AND act.related_type = 'CLIENT_TICKET'
      AND NOT EXISTS (
          SELECT 1 FROM client.ticket_messages m WHERE m.external_ref = act.id::text
      )
    ORDER BY act.occurred_at
    LIMIT :batch
    """
)


async def _pull_replies(session: AsyncSession) -> int:
    rows = (await session.execute(_REPLY_SQL, {"batch": _BATCH})).mappings().all()
    for row in rows:
        name = row["advisor_name"] or "Qura"
        session.add(
            TicketMessage(
                ticket_id=row["ticket_id"],
                sender_id=None,
                sender_name=f"{name} (Qura advisor)",
                external_ref=str(row["id"]),
                message=row["summary"],
                created_at=row["occurred_at"],
            )
        )
        _notify(
            session,
            row["user_id"],
            "Your advisor replied",
            row["summary"][:200],
            "message",
            row["ticket_id"],
        )
    await session.flush()
    return len(rows)


# --- Request status ----------------------------------------------------------

_TICKET_SQL = text(
    """
    SELECT DISTINCT ON (t.id) t.id, t.status, tk.status::text AS task_status,
           -- The client acted after the advisor's last change (reopened the request, or wrote
           -- again before this pull ran): leave it open for the CRM's follow-up task.
           -- crm timestamps are naive UTC, so convert before comparing with timestamptz.
           (t.updated_at > tk.updated_at AT TIME ZONE 'UTC'
            OR EXISTS (SELECT 1 FROM client.ticket_messages m
                       WHERE m.ticket_id = t.id AND m.sender_id IS NOT NULL
                         AND m.created_at > tk.updated_at AT TIME ZONE 'UTC')) AS client_acted_since
    FROM crm.tasks tk
    JOIN client.support_tickets t ON t.id = tk.related_id
    WHERE tk.related_type = 'CLIENT_TICKET'
    ORDER BY t.id, tk.updated_at DESC
    """
)


async def _pull_ticket_status(session: AsyncSession) -> int:
    rows = (await session.execute(_TICKET_SQL)).mappings().all()
    changed = 0
    for row in rows:
        wanted = _TICKET_STATUS.get(row["task_status"])
        if wanted is None or row["status"] not in _TICKET_ORDER:
            continue
        if _TICKET_ORDER.index(wanted) <= _TICKET_ORDER.index(row["status"]):
            continue  # never move a request backwards
        if row["client_acted_since"]:
            continue  # the client came back after the advisor's last action
        ticket = await session.get(SupportTicket, row["id"])
        if ticket is None:
            continue
        ticket.status = wanted
        changed += 1
        if wanted == "resolved":
            _notify(
                session,
                ticket.user_id,
                "Request resolved",
                f"Your request \"{ticket.subject or 'Support request'}\" was resolved.",
                "success",
                ticket.id,
            )
    await session.flush()
    return changed


# --- Claims ------------------------------------------------------------------

# CRM ClaimStatus -> (portal status, words for the client).
_CLAIM_STATUS = {
    "INTIMATED": ("submitted", "Claim received by your advisor"),
    "DOCUMENTS_PENDING": ("documents_pending", "More documents needed"),
    "SURVEYOR_ASSIGNED": ("in_review", "Surveyor assigned"),
    "SUBMITTED_TO_INSURER": ("in_review", "Submitted to the insurer"),
    "UNDER_REVIEW": ("in_review", "Under review by the insurer"),
    "APPROVED": ("approved", "Claim approved"),
    "REJECTED": ("rejected", "Claim rejected"),
    "SETTLED": ("settled", "Claim settled"),
}

_CLAIM_SQL = text(
    """
    SELECT c.id AS crm_id, c.client_claim_id, c.status::text AS status,
           c.approved_amount, c.remarks, c.surveyor_name,
           c.updated_at AT TIME ZONE 'UTC' AS updated_at
    FROM crm.claims c
    JOIN client.claims cc ON cc.id = c.client_claim_id
    WHERE cc.crm_synced_at IS NULL OR cc.crm_synced_at < c.updated_at AT TIME ZONE 'UTC'
    ORDER BY c.updated_at
    LIMIT :batch
    """
)


async def _pull_claims(session: AsyncSession) -> int:
    rows = (await session.execute(_CLAIM_SQL, {"batch": _BATCH})).mappings().all()
    for row in rows:
        claim = await session.get(Claim, row["client_claim_id"])
        if claim is None:
            continue
        status, label = _CLAIM_STATUS.get(row["status"], ("in_review", "Claim updated"))
        first_link = claim.crm_claim_id is None
        claim.crm_claim_id = row["crm_id"]
        claim.crm_synced_at = row["updated_at"]
        if row["approved_amount"] is not None:
            claim.approved_amount = _money(row["approved_amount"])
        if status == claim.status and not first_link:
            continue
        if status != claim.status:
            claim.status = status
            if status == "settled":
                claim.settled_date = datetime.now(UTC).date()
            note = label
            if row["remarks"] and status != "submitted":
                note = f"{label}: {row['remarks']}"
            elif row["surveyor_name"] and status == "in_review":
                note = f"{label} ({row['surveyor_name']})"
            claim.timeline = [
                *(claim.timeline or []),
                {"status": status, "date": datetime.now(UTC).date().isoformat(), "note": note},
            ]
            _notify(
                session,
                claim.user_id,
                "Claim update",
                f"{claim.claim_number}: {note}",
                "claim",
                claim.id,
            )
    await session.flush()
    return len(rows)


def _notify(
    session: AsyncSession,
    user_id: Any,
    title: str,
    message: str,
    kind: str,
    reference: Any,
) -> None:
    session.add(
        Notification(
            user_id=user_id,
            title=title,
            message=message,
            type=kind,
            reference_id=str(reference) if reference is not None else None,
        )
    )
