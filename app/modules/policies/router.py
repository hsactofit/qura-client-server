"""Policy routes.

  GET   /policies                 list the user's policies (optional ?status=)
  GET   /policies/{id}            one policy, ownership-enforced
  POST  /policies/extract         AI extract a document for review (no record)
  POST  /policies/upload          extract + merge + persist an uploaded policy
  POST  /policies/track           create a local tracking record for a proposal
  PATCH /policies/confirm         confirm user-reviewed details for a proposal
  POST  /policies/status          live insurer status sync (unavailable here)
  POST  /policies/{id}/request    ask the advisor (renewal, callback, query, claim)
  GET   /policies/{id}/download   stream the owned policy's private document

Reads and writes are scoped to the authenticated user (user_id-filtered, 404 on
not-owned). Mutating routes require the double-submit CSRF check. Identity is
derived only from the validated session, never from request input.

Deliberately NOT provided: unrestricted PUT/PATCH/DELETE on policy records.
Policyholder corrections flow through /upload (self-reported) and /confirm
(user-confirmed); an authoritative insurance contract is not editable or
deletable through this client API.
"""

from __future__ import annotations

import json
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.envelope import success
from app.core.security import CurrentUser, enforce_csrf, require_authenticated
from app.core.uploads import enforce_size, sniff_document
from app.db.session import get_session
from app.modules.policies import service
from app.modules.policies.mappers import policy_to_dict
from app.modules.policies.schemas import (
    ConfirmPolicyRequest,
    PolicyRequest,
    PolicyStatusRequest,
    TrackPolicyRequest,
)
from app.modules.support.mappers import ticket_to_dict

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("")
async def list_policies(
    status: str | None = None,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    policies = await service.list_policies(session, user.id, status=status)
    return success([policy_to_dict(p) for p in policies])


@router.post("/extract")
async def extract_policy(
    document: Annotated[UploadFile, File()],
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Extract fields from a document for the review UI. Creates no record."""
    data = await document.read()
    enforce_size(data, max_bytes=settings.upload_max_bytes)
    detected = sniff_document(data)
    outcome = await service.extract_only(settings, data=data, detected=detected)
    return success(
        {
            "extracted": outcome.extracted,
            "extraction_available": outcome.extraction_available,
            "original_name": document.filename,
        },
        outcome.message,
    )


@router.post("/upload")
async def upload_policy(
    document: Annotated[UploadFile | None, File()] = None,
    policy_number: Annotated[str | None, Form()] = None,
    policy_type: Annotated[str | None, Form()] = None,
    insurer_name: Annotated[str | None, Form()] = None,
    coverage_amount: Annotated[str | None, Form()] = None,
    premium_amount: Annotated[str | None, Form()] = None,
    premium_frequency: Annotated[str | None, Form()] = None,
    start_date: Annotated[str | None, Form()] = None,
    end_date: Annotated[str | None, Form()] = None,
    nominee_name: Annotated[str | None, Form()] = None,
    nominee_relationship: Annotated[str | None, Form()] = None,
    extracted: Annotated[str | None, Form()] = None,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Upload and save a policy (optionally extracting from the document).

    User-supplied form fields take precedence over extracted values. The record
    is associated with the authenticated user only; no client-supplied owner id
    is accepted.
    """
    data: bytes | None = None
    detected = None
    original_name: str | None = None
    if document is not None:
        data = await document.read()
        if data:
            enforce_size(data, max_bytes=settings.upload_max_bytes)
            detected = sniff_document(data)
            original_name = document.filename
        else:
            data = None  # empty upload field: treat as no document

    manual = {
        "policy_number": policy_number,
        "policy_type": policy_type,
        "insurer_name": insurer_name,
        "coverage_amount": coverage_amount,
        "premium_amount": premium_amount,
        "premium_frequency": premium_frequency,
        "start_date": start_date,
        "end_date": end_date,
        "nominee_name": nominee_name,
        "nominee_relationship": nominee_relationship,
    }
    reviewed: dict | None = None
    if extracted:
        # JSON from a prior /extract call (reviewed in the UI). Bad JSON is
        # ignored: the server then extracts again rather than failing.
        try:
            parsed = json.loads(extracted)
        except ValueError:
            parsed = None
        reviewed = parsed if isinstance(parsed, dict) else None
    outcome = await service.upload_policy(
        session,
        settings,
        user.id,
        manual=manual,
        document=data,
        detected=detected,
        original_name=original_name,
        reviewed=reviewed,
    )
    return success(
        {
            "policy": policy_to_dict(outcome.policy),
            "extraction_used": outcome.extraction_used,
            "duplicate": outcome.duplicate,
        },
        outcome.message,
    )


@router.post("/track")
async def track_policy(
    body: TrackPolicyRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    policy = await service.track_policy(session, user.id, body)
    return success(policy_to_dict(policy), "Policy tracked")


@router.patch("/confirm")
async def confirm_policy(
    body: ConfirmPolicyRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    policy = await service.confirm_policy(session, user.id, body)
    return success(policy_to_dict(policy), "Policy confirmed")


@router.post("/status")
async def policy_status(
    body: PolicyStatusRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Raises 404 if not owned, 501 if no insurer integration is configured.
    await service.sync_policy_status(session, user.id, body)
    return success(None)  # unreachable today; kept for when sync is supported


@router.post("/{policy_id}/request")
async def request_help(
    policy_id: str,
    body: PolicyRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ask the advisor for a renewal quote, a callback, or help with this policy."""
    ticket = await service.create_policy_request(session, user.id, policy_id, body)
    return success(ticket_to_dict(ticket), "Request sent to your Qura advisor")


@router.get("/{policy_id}")
async def get_policy(
    policy_id: str,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    policy = await service.get_policy(session, user.id, policy_id)
    return success(policy_to_dict(policy))


@router.get("/{policy_id}/download")
async def download_policy(
    policy_id: str,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Stream the owned policy's document from private storage.

    Returns the file as an attachment. Ownership is enforced and the path is
    resolved inside the private storage root (no public exposure, no traversal).
    """
    doc = await service.get_policy_document(session, settings, user.id, policy_id)
    if doc.data is not None:
        safe_name = quote(doc.filename)
        return Response(
            content=doc.data,
            media_type=doc.content_type,
            headers={
                "Content-Disposition": f"attachment; filename*=utf-8''{safe_name}"
            },
        )
    return FileResponse(
        path=doc.path,
        media_type=doc.content_type,
        filename=doc.filename,
    )
