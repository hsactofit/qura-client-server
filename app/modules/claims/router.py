"""Claim routes.

  GET  /claims          list the user's claims
  POST /claims          intimate a claim on an owned policy (multipart, documents[])
  GET  /claims/{id}     one claim with its documents, ownership-enforced
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.envelope import success
from app.core.errors import ApiError
from app.core.security import CurrentUser, enforce_csrf, require_authenticated
from app.core.uploads import enforce_size, sniff_document
from app.db.session import get_session
from app.modules.claims import service
from app.modules.claims.mappers import claim_to_dict

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("")
async def list_claims(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    claims = await service.list_claims(session, user.id)
    return success([claim_to_dict(c) for c in claims])


_MAX_CLAIM_DOCUMENTS = 10


@router.post("")
async def file_claim(
    policy_id: Annotated[str, Form()],
    description: Annotated[str, Form(min_length=10, max_length=4000)],
    claim_amount: Annotated[str | None, Form()] = None,
    submission_date: Annotated[str | None, Form()] = None,
    documents: Annotated[list[UploadFile] | None, File()] = None,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """File a claim; a Qura advisor picks it up in the CRM."""
    if "<" in description or ">" in description:
        raise ApiError("Description must not contain '<' or '>'", status_code=422)
    amount: float | None = None
    if claim_amount:
        try:
            amount = float(Decimal(claim_amount))
        except (InvalidOperation, ValueError) as exc:
            raise ApiError("Claim amount must be a number", status_code=422) from exc
        if amount < 0:
            raise ApiError("Claim amount cannot be negative", status_code=422)
    incident: date | None = None
    if submission_date:
        try:
            incident = date.fromisoformat(submission_date[:10])
        except ValueError as exc:
            raise ApiError("Incident date must be YYYY-MM-DD", status_code=422) from exc
    files = [f for f in (documents or []) if f.filename]
    if len(files) > _MAX_CLAIM_DOCUMENTS:
        raise ApiError(f"Attach at most {_MAX_CLAIM_DOCUMENTS} documents", status_code=422)
    uploads: list[service.ClaimUpload] = []
    for f in files:
        data = await f.read()
        if not data:
            continue
        enforce_size(data, max_bytes=settings.upload_max_bytes)
        uploads.append(
            service.ClaimUpload(data=data, detected=sniff_document(data), name=f.filename)
        )
    claim = await service.file_claim(
        session,
        settings,
        user.id,
        policy_id=policy_id,
        claim_amount=amount,
        description=description.strip(),
        incident_date=incident,
        documents=uploads,
    )
    return success(claim_to_dict(claim), "Claim submitted. Your Qura advisor will contact you.")


@router.get("/{claim_id}")
async def get_claim(
    claim_id: str,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    claim = await service.get_claim(session, user.id, claim_id)
    return success(claim_to_dict(claim, include_documents=True))
