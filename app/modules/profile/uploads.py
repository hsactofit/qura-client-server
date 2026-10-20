"""Avatar and KYC upload/download logic, scoped to the authenticated user.

Security posture:
- The owner is always the session user; no client-supplied owner id is accepted.
- Bytes are validated by content sniffing (not the declared MIME) and a hard
  size cap before anything is written.
- Files are stored privately via :mod:`app.core.storage`; the DB keeps an opaque
  ``storage_key`` and downloads go only through the authenticated, ownership-
  checked endpoints. No public URL is ever produced.
- Replacing an avatar or re-uploading a KYC document removes the previous
  private file (compensation on failure keeps storage and DB consistent).
- KYC verification is honest: an uploaded document is recorded as ``pending``
  and is never auto-verified. ``user.photo_url`` points at the authenticated
  avatar endpoint, not a public file path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.uploads import DetectedFile, enforce_size, sniff_document, sniff_image
from app.db.models.files import StoredFile
from app.db.models.identity import User
from app.db.models.kyc import KYC_DOC_TYPES, KycDocument

# The path (under the API prefix) at which the authenticated avatar is served.
# Stored in ``users.photo_url`` so the existing frontend <AvatarImage src> loads
# it with credentials; it is NOT a public file location.
_AVATAR_URL = "/user/avatar"


# --- Avatar ----------------------------------------------------------------


async def _load_user(session: AsyncSession, user_id: str) -> User:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ApiError("User not found", status_code=404)
    return user


async def _owned_avatar_file(
    session: AsyncSession, user_id: str
) -> StoredFile | None:
    result = await session.execute(
        select(StoredFile).where(
            StoredFile.owner_user_id == user_id, StoredFile.purpose == "avatar"
        )
    )
    return result.scalars().first()


async def upload_avatar(
    session: AsyncSession,
    settings: Settings,
    user_id: str,
    *,
    data: bytes,
    original_name: str | None,
) -> str:
    """Store (replacing any existing) the user's avatar; return its URL.

    Validates image content and size first. The previous avatar file and row
    are removed so only one avatar exists per user.
    """
    enforce_size(data, max_bytes=settings.upload_max_bytes)
    detected = sniff_image(data)

    storage_key, sha256, size = storage.save_bytes(
        settings, purpose="avatar", original_name=original_name, data=data
    )
    old_file = await _owned_avatar_file(session, user_id)
    old_key = old_file.storage_key if old_file is not None else None
    try:
        if old_file is not None:
            await session.delete(old_file)
            await session.flush()
        stored = StoredFile(
            owner_user_id=user_id,
            purpose="avatar",
            storage_key=storage_key,
            original_name=original_name,
            content_type=detected.content_type,
            size_bytes=size,
            sha256=sha256,
        )
        session.add(stored)
        user = await _load_user(session, user_id)
        user.photo_url = _AVATAR_URL
        await session.flush()
    except Exception:
        storage.delete_quietly(settings, storage_key)
        raise
    # Only after the row swap succeeds do we drop the previous bytes.
    if old_key is not None:
        storage.delete_quietly(settings, old_key)
    return _AVATAR_URL


@dataclass
class StoredFileDownload:
    path: Path
    filename: str
    content_type: str


def _resolve_download(
    settings: Settings, stored: StoredFile, *, fallback_name: str
) -> StoredFileDownload:
    try:
        path = storage.resolve_path(settings, stored.storage_key)
    except storage.StorageError as exc:
        raise ApiError("File not available", status_code=404) from exc
    if not path.is_file():
        raise ApiError("File not available", status_code=404)
    return StoredFileDownload(
        path=path,
        filename=stored.original_name or f"{fallback_name}{path.suffix}",
        content_type=stored.content_type or "application/octet-stream",
    )


async def get_avatar_download(
    session: AsyncSession, settings: Settings, user_id: str
) -> StoredFileDownload:
    stored = await _owned_avatar_file(session, user_id)
    if stored is None:
        raise ApiError("No profile picture uploaded", status_code=404)
    return _resolve_download(settings, stored, fallback_name=f"avatar-{user_id}")


# --- KYC documents ---------------------------------------------------------


def _normalise_doc_type(doc_type: str | None) -> str:
    value = (doc_type or "").strip().lower()
    if value not in KYC_DOC_TYPES:
        allowed = ", ".join(KYC_DOC_TYPES)
        raise ApiError(
            f"Invalid document_type. Allowed: {allowed}.", status_code=422
        )
    return value


async def _owned_kyc(
    session: AsyncSession, user_id: str, doc_type: str
) -> KycDocument | None:
    result = await session.execute(
        select(KycDocument).where(
            KycDocument.user_id == user_id, KycDocument.doc_type == doc_type
        )
    )
    return result.scalar_one_or_none()


async def upload_kyc_document(
    session: AsyncSession,
    settings: Settings,
    user_id: str,
    *,
    doc_type: str | None,
    data: bytes,
    original_name: str | None,
) -> KycDocument:
    """Store (replacing any existing of the same type) a KYC document.

    Accepts PDF or image content (sniffed, not trusted). Records an honest
    ``pending`` status; it never marks the document verified.
    """
    normalised = _normalise_doc_type(doc_type)
    enforce_size(data, max_bytes=settings.upload_max_bytes)
    detected: DetectedFile = sniff_document(data)

    storage_key, sha256, size = storage.save_bytes(
        settings, purpose="kyc", original_name=original_name, data=data
    )
    existing = await _owned_kyc(session, user_id, normalised)
    old_key: str | None = None
    try:
        stored = StoredFile(
            owner_user_id=user_id,
            purpose="kyc",
            storage_key=storage_key,
            original_name=original_name,
            content_type=detected.content_type,
            size_bytes=size,
            sha256=sha256,
        )
        session.add(stored)
        await session.flush()

        if existing is not None:
            # Replace: remember the old private file, repoint the row, reset to
            # pending (a replacement must be re-reviewed, never stays verified).
            if existing.file_id is not None:
                old = await session.execute(
                    select(StoredFile).where(StoredFile.id == existing.file_id)
                )
                old_stored = old.scalar_one_or_none()
                if old_stored is not None:
                    old_key = old_stored.storage_key
                    await session.delete(old_stored)
            existing.file_id = stored.id
            existing.original_name = original_name
            existing.content_type = detected.content_type
            existing.status = "pending"
            record = existing
        else:
            record = KycDocument(
                user_id=user_id,
                file_id=stored.id,
                doc_type=normalised,
                original_name=original_name,
                content_type=detected.content_type,
                status="pending",
            )
            session.add(record)
        await session.flush()
    except Exception:
        storage.delete_quietly(settings, storage_key)
        raise
    if old_key is not None:
        storage.delete_quietly(settings, old_key)
    return record


async def list_kyc_documents(
    session: AsyncSession, user_id: str
) -> list[KycDocument]:
    result = await session.execute(
        select(KycDocument)
        .where(KycDocument.user_id == user_id)
        .order_by(KycDocument.created_at.desc())
    )
    return list(result.scalars().all())


async def get_kyc_document(
    session: AsyncSession, user_id: str, document_id: str
) -> KycDocument:
    result = await session.execute(
        select(KycDocument).where(
            KycDocument.id == document_id, KycDocument.user_id == user_id
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise ApiError("KYC document not found", status_code=404)
    return record


async def get_kyc_download(
    session: AsyncSession, settings: Settings, user_id: str, document_id: str
) -> StoredFileDownload:
    record = await get_kyc_document(session, user_id, document_id)
    if record.file_id is None:
        raise ApiError("File not available", status_code=404)
    result = await session.execute(
        select(StoredFile).where(
            StoredFile.id == record.file_id, StoredFile.owner_user_id == user_id
        )
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise ApiError("File not available", status_code=404)
    return _resolve_download(
        settings, stored, fallback_name=f"kyc-{record.doc_type}"
    )


def kyc_to_dict(record: KycDocument) -> dict[str, Any]:
    """ORM -> frontend mapping for a single KYC document (no storage_key)."""
    return {
        "id": str(record.id),
        "doc_type": record.doc_type,
        "name": record.original_name,
        "content_type": record.content_type,
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def kyc_documents_summary(records: list[KycDocument]) -> dict[str, Any]:
    """The ``preferences.kyc_documents`` view the Profile page reads.

    Shape: ``{<doc_type>: {name, status}}`` — one entry per uploaded type.
    """
    return {
        r.doc_type: {"name": r.original_name, "status": r.status} for r in records
    }
