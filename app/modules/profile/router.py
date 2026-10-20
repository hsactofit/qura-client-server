"""Profile, settings, avatar and KYC routes.

Paths match the existing frontend contract:
  GET   /user/profile
  PUT   /user/profile/update
  GET   /user/settings
  PUT   /user/settings
  POST  /user/avatar                upload/replace the profile picture
  GET   /user/avatar                stream the authenticated user's avatar
  POST  /user/kyc-document          upload/replace a KYC document (by type)
  GET   /user/kyc-documents         list the authenticated user's KYC documents
  GET   /user/kyc-documents/{id}/download   stream an owned KYC document

The current user is taken only from the validated session (never a body/query
user id). Mutating routes require the double-submit CSRF check. Protected fields
(role, status, id, email, ownership) are not accepted by the update schema.
Uploaded files are stored privately and served only through the authenticated,
ownership-checked download routes — never from a public URL.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.envelope import success
from app.core.security import CurrentUser, enforce_csrf, require_authenticated
from app.db.session import get_session
from app.modules.profile import service, uploads
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
    kyc = await uploads.list_kyc_documents(session, user.id)
    return success(user_to_dict(db_user, profile, uploads.kyc_documents_summary(kyc)))


@router.put("/profile/update")
async def update_profile(
    body: UpdateProfileRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    db_user, profile = await service.update_profile(session, user.id, body)
    kyc = await uploads.list_kyc_documents(session, user.id)
    return success(
        user_to_dict(db_user, profile, uploads.kyc_documents_summary(kyc)),
        "Profile updated",
    )


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


# --- Avatar ----------------------------------------------------------------


@router.post("/avatar")
async def upload_avatar(
    file: Annotated[UploadFile, File()],
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    data = await file.read()
    url = await uploads.upload_avatar(
        session, settings, user.id, data=data, original_name=file.filename
    )
    # The frontend reads data.fileUrl and writes it to the profile photo_url.
    return success({"fileUrl": url}, "Profile photo updated")


@router.get("/avatar")
async def download_avatar(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    doc = await uploads.get_avatar_download(session, settings, user.id)
    return FileResponse(
        path=doc.path, media_type=doc.content_type, filename=doc.filename
    )


# --- KYC documents ---------------------------------------------------------


@router.post("/kyc-document")
async def upload_kyc_document(
    file: Annotated[UploadFile, File()],
    document_type: Annotated[str | None, Form()] = None,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    data = await file.read()
    record = await uploads.upload_kyc_document(
        session,
        settings,
        user.id,
        doc_type=document_type,
        data=data,
        original_name=file.filename,
    )
    return success(uploads.kyc_to_dict(record), "Document uploaded for verification")


@router.get("/kyc-documents")
async def list_kyc_documents(
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    records = await uploads.list_kyc_documents(session, user.id)
    return success([uploads.kyc_to_dict(r) for r in records])


@router.get("/kyc-documents/{document_id}/download")
async def download_kyc_document(
    document_id: str,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    doc = await uploads.get_kyc_download(session, settings, user.id, document_id)
    return FileResponse(
        path=doc.path, media_type=doc.content_type, filename=doc.filename
    )
