"""Calls to the CRM's internal API (private Docker network, shared token)."""

from __future__ import annotations

import logging

import httpx

from app.core.config import Settings
from app.core.errors import ApiError

logger = logging.getLogger("qura.crm_sync")

_MAX_BYTES = 30 * 1024 * 1024


async def fetch_document(settings: Settings, document_id: str) -> tuple[bytes, str | None]:
    """Return ``(bytes, content_type)`` of a CRM document, or raise ApiError(404/503)."""
    if not settings.crm_internal_url or not settings.internal_token:
        raise ApiError(
            "This document is held by your advisor and is not reachable right now.",
            status_code=503,
        )
    url = f"{settings.crm_internal_url.rstrip('/')}/internal/documents/{document_id}/content"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers={"X-Internal-Token": settings.internal_token})
    except httpx.HTTPError as exc:
        logger.warning("CRM document fetch failed: %s", type(exc).__name__)
        raise ApiError("Could not fetch the document. Please try again.", status_code=503) from exc
    if resp.status_code == 404:
        raise ApiError("No document is available for this policy", status_code=404)
    if not resp.is_success or len(resp.content) > _MAX_BYTES:
        logger.warning("CRM document fetch HTTP %s", resp.status_code)
        raise ApiError("Could not fetch the document. Please try again.", status_code=503)
    return resp.content, resp.headers.get("content-type")
