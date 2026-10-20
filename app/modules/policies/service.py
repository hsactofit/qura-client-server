"""Policy queries and operations, always scoped to the authenticated user.

Ownership is enforced in every query by filtering on ``user_id``; a policy that
does not exist or belongs to another user returns 404 (no existence disclosure,
IDOR-safe). Document storage goes through the private storage backend and is
referenced via ``stored_files``; downloads are authorized and streamed, never
exposed through a public URL.

Field precedence for uploads (documented): user-supplied form values WIN over
AI-extracted values. Extraction only fills a field the user left blank. Nothing
is ever fabricated — a field unknown to both the user and the model stays null.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.uploads import DetectedFile
from app.db.models.files import StoredFile
from app.db.models.policies import Policy
from app.modules.policies import extraction
from app.modules.policies.schemas import (
    ConfirmPolicyRequest,
    PolicyStatusRequest,
    TrackPolicyRequest,
)

logger = logging.getLogger("qura.policies")


# --- Reads -----------------------------------------------------------------


async def list_policies(
    session: AsyncSession, user_id: str, *, status: str | None = None
) -> list[Policy]:
    stmt = select(Policy).where(Policy.user_id == user_id)
    if status and status != "all":
        stmt = stmt.where(Policy.status == status)
    stmt = stmt.order_by(Policy.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_policy(session: AsyncSession, user_id: str, policy_id: str) -> Policy:
    """Fetch one policy owned by the user, or 404 (no existence disclosure)."""
    result = await session.execute(
        select(Policy).where(Policy.id == policy_id, Policy.user_id == user_id)
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise ApiError("Policy not found", status_code=404)
    return policy


# --- Coercion helpers ------------------------------------------------------


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# --- Extraction (review only; no persistence) ------------------------------


@dataclass
class ExtractionOutcome:
    """Result of an extract-only request for the review UI."""

    extracted: dict[str, Any]
    extraction_available: bool
    message: str


async def extract_only(
    settings: Settings, *, data: bytes, detected: DetectedFile
) -> ExtractionOutcome:
    """Run extraction for review. Does NOT create any policy record.

    When extraction is unavailable or fails, returns an all-null field set with
    an honest message instead of raising — the UI lets the user fill fields
    manually either way. Document bytes are not persisted here.
    """
    if not extraction.is_configured(settings):
        return ExtractionOutcome(
            extracted=extraction.empty_result(),
            extraction_available=False,
            message=(
                "Automatic extraction is not configured. "
                "Enter the policy details manually."
            ),
        )
    try:
        fields = await extraction.extract_policy(settings, data=data, detected=detected)
    except extraction.ExtractionError as exc:
        return ExtractionOutcome(
            extracted=extraction.empty_result(),
            extraction_available=True,
            message=str(exc),
        )
    return ExtractionOutcome(
        extracted=fields,
        extraction_available=True,
        message="Details extracted. Review and correct before saving.",
    )


# --- Upload (extract + merge + persist) ------------------------------------


# Documented precedence: user form value first, then extracted value.
def _merge_field(manual: Any, extracted: Any) -> Any:
    manual_clean = manual if manual not in (None, "") else None
    return manual_clean if manual_clean is not None else extracted


async def _find_duplicate(
    session: AsyncSession, user_id: str, *, sha256: str | None, policy_number: str | None
) -> Policy | None:
    """Detect an existing owned policy for idempotency.

    Two signals, strongest first: the same stored document (sha256) already
    linked to one of the user's policies, or the same policy_number owned by
    the user. Prevents accidental duplicate records on resubmission.
    """
    if sha256:
        # Find the user's stored policy documents with this content hash, then
        # the policy that references one of them. Two scoped lookups instead of
        # a join keeps this compatible with the row-level ownership model.
        files = await session.execute(
            select(StoredFile).where(
                StoredFile.owner_user_id == user_id,
                StoredFile.sha256 == sha256,
                StoredFile.purpose == "policy",
            )
        )
        for stored in files.scalars().all():
            match = await session.execute(
                select(Policy).where(
                    Policy.user_id == user_id,
                    Policy.document_file_id == stored.id,
                )
            )
            existing = match.scalar_one_or_none()
            if existing is not None:
                return existing
    if policy_number:
        result = await session.execute(
            select(Policy).where(
                Policy.user_id == user_id, Policy.policy_number == policy_number
            )
        )
        return result.scalar_one_or_none()
    return None


@dataclass
class UploadOutcome:
    policy: Policy
    extraction_used: bool
    duplicate: bool
    message: str


async def upload_policy(
    session: AsyncSession,
    settings: Settings,
    user_id: str,
    *,
    manual: dict[str, Any],
    document: bytes | None,
    detected: DetectedFile | None,
    original_name: str | None,
) -> UploadOutcome:
    """Extract (if a document is present), merge, validate and persist.

    Storage and the DB row are kept consistent: if persistence fails after the
    document is written, the stored file is removed (compensation). Duplicate
    resubmissions return the existing record instead of creating another.

    A manually uploaded document is explicitly NOT treated as insurer proof: the
    record is saved as ``verification_status = self_reported``.
    """
    extracted: dict[str, Any] = extraction.empty_result()
    extraction_used = False

    if (
        document is not None
        and detected is not None
        and extraction.is_configured(settings)
    ):
        try:
            extracted = await extraction.extract_policy(
                settings, data=document, detected=detected
            )
            extraction_used = any(v is not None for v in extracted.values())
        except extraction.ExtractionError as exc:
            # Honest degradation: proceed with the user's fields only.
            logger.info("Upload extraction skipped: %s", type(exc).__name__)

    # Merge with user precedence.
    merged = {
        field: _merge_field(manual.get(field), extracted.get(field))
        for field in extraction.EXTRACTION_FIELDS
    }

    policy_number = _clean_str(merged.get("policy_number"))
    coverage_amount = _to_decimal(merged.get("coverage_amount"))
    premium_amount = _to_decimal(merged.get("premium_amount"))
    start_date = _to_date(merged.get("start_date"))
    end_date = _to_date(merged.get("end_date"))

    # Validate required fields and date sanity before any write.
    policy_type = _clean_str(merged.get("policy_type"))
    insurer_name = _clean_str(merged.get("insurer_name"))
    if not policy_type:
        raise ApiError("Policy type is required", status_code=422)
    if not insurer_name:
        raise ApiError("Insurer name is required", status_code=422)
    if start_date and end_date and end_date < start_date:
        raise ApiError("End date cannot be before start date", status_code=422)

    # Store the document first so we can compute its sha256 for dedup.
    stored_file: StoredFile | None = None
    storage_key: str | None = None
    sha256: str | None = None
    if document is not None:
        storage_key, sha256, size = storage.save_bytes(
            settings, purpose="policy", original_name=original_name, data=document
        )

    try:
        duplicate = await _find_duplicate(
            session, user_id, sha256=sha256, policy_number=policy_number
        )
        if duplicate is not None:
            # Idempotent: don't create a second record; drop the just-written file.
            if storage_key is not None:
                storage.delete_quietly(settings, storage_key)
            return UploadOutcome(
                policy=duplicate,
                extraction_used=extraction_used,
                duplicate=True,
                message="This policy document was already uploaded.",
            )

        if document is not None and storage_key is not None:
            stored_file = StoredFile(
                owner_user_id=user_id,
                purpose="policy",
                storage_key=storage_key,
                original_name=original_name,
                content_type=detected.content_type if detected else None,
                size_bytes=size,
                sha256=sha256,
            )
            session.add(stored_file)
            await session.flush()

        policy = Policy(
            user_id=user_id,
            policy_number=policy_number,
            policy_type=policy_type,
            insurer_name=insurer_name,
            coverage_amount=coverage_amount,
            premium_amount=premium_amount,
            premium_frequency=_clean_str(merged.get("premium_frequency")),
            start_date=start_date,
            end_date=end_date,
            status="active",
            nominee_name=_clean_str(merged.get("nominee_name")),
            nominee_relationship=_clean_str(merged.get("nominee_relationship")),
            policy_source="uploaded",
            verification_status="self_reported",
            document_original_name=original_name,
            document_file_id=stored_file.id if stored_file is not None else None,
        )
        session.add(policy)
        await session.flush()
    except Exception:
        # Compensation: the request will roll back the transaction, but the
        # written file lives outside it — remove it so storage doesn't leak.
        if storage_key is not None:
            storage.delete_quietly(settings, storage_key)
        raise

    return UploadOutcome(
        policy=policy,
        extraction_used=extraction_used,
        duplicate=False,
        message="Policy saved",
    )


# --- Track / confirm / status ----------------------------------------------


async def track_policy(
    session: AsyncSession, user_id: str, body: TrackPolicyRequest
) -> Policy:
    """Create a local tracking record for a platform-originated proposal."""
    existing = await session.execute(
        select(Policy).where(
            Policy.user_id == user_id, Policy.proposal_id == body.proposal_id
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found  # idempotent on proposal_id per user

    policy = Policy(
        user_id=user_id,
        proposal_id=body.proposal_id,
        product_enum=body.product_enum,
        policy_type=body.policy_type,
        insurer_name=body.insurer_name,
        premium_amount=_to_decimal(body.premium_amount),
        nominee_name=body.nominee_name,
        nominee_relationship=body.nominee_relationship,
        policy_source="platform",
        status="pending",
        verification_status="self_reported",
    )
    session.add(policy)
    await session.flush()
    return policy


async def confirm_policy(
    session: AsyncSession, user_id: str, body: ConfirmPolicyRequest
) -> Policy:
    """Confirm user-reviewed details for a tracked policy (ownership enforced).

    This marks the policy ``user_confirmed`` — a record that the USER reviewed
    the fields. It never sets ``insurer_verified`` and never invents a status;
    ``status`` only changes to a value the caller explicitly supplies.
    """
    result = await session.execute(
        select(Policy).where(
            Policy.user_id == user_id, Policy.proposal_id == body.proposal_id
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise ApiError("No tracked policy found for that proposal", status_code=404)

    if body.policy_number is not None:
        policy.policy_number = body.policy_number
    if body.status is not None:
        policy.status = body.status
    # Confirmation is a user action, not an insurer attestation.
    if policy.verification_status == "self_reported":
        policy.verification_status = "user_confirmed"
    await session.flush()
    return policy


async def sync_policy_status(
    session: AsyncSession, user_id: str, body: PolicyStatusRequest
) -> None:
    """Live insurer status sync.

    Qura has no configured insurer integration, so synchronising a policy's
    status from an authoritative upstream source is not possible here. We refuse
    honestly rather than inventing a status or faking success. Local status is
    still readable via GET /policies and GET /policies/{id}.
    """
    # Verify ownership so this cannot be used to probe other users' proposals.
    result = await session.execute(
        select(Policy).where(
            Policy.user_id == user_id, Policy.proposal_id == body.proposal_id
        )
    )
    if result.scalar_one_or_none() is None:
        raise ApiError("No tracked policy found for that proposal", status_code=404)
    raise ApiError(
        "Live insurer status sync is not available in this deployment.",
        status_code=501,
    )


# --- Download --------------------------------------------------------------


@dataclass
class PolicyDocument:
    """A policy's stored document, resolved and ownership-verified."""

    path: Any  # pathlib.Path
    filename: str
    content_type: str
    size_bytes: int


async def get_policy_document(
    session: AsyncSession, settings: Settings, user_id: str, policy_id: str
) -> PolicyDocument:
    """Resolve the owned policy's document for secure streaming.

    Enforces ownership (404 for not-owned/not-found), requires a linked stored
    file (404 when none), and resolves the private path with a traversal guard.
    The returned path is always inside the configured storage root.
    """
    policy = await get_policy(session, user_id, policy_id)
    if policy.document_file_id is None:
        raise ApiError("No document is available for this policy", status_code=404)

    result = await session.execute(
        select(StoredFile).where(
            StoredFile.id == policy.document_file_id,
            StoredFile.owner_user_id == user_id,
        )
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise ApiError("No document is available for this policy", status_code=404)

    try:
        path = storage.resolve_path(settings, stored.storage_key)
    except storage.StorageError as exc:
        # A traversal/escape should never happen for keys we generated; treat
        # it as missing rather than exposing any detail.
        raise ApiError(
            "No document is available for this policy", status_code=404
        ) from exc
    if not path.is_file():
        raise ApiError("No document is available for this policy", status_code=404)

    filename = stored.original_name or f"policy-{policy_id}{path.suffix}"
    return PolicyDocument(
        path=path,
        filename=filename,
        content_type=stored.content_type or "application/octet-stream",
        size_bytes=stored.size_bytes or path.stat().st_size,
    )
