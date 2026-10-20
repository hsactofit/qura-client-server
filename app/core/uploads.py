"""Upload validation for policy documents.

Security posture: the client-supplied filename and ``Content-Type`` are treated
as untrusted hints only. The real format decision is made by sniffing the file's
leading bytes (magic numbers). Only an explicit allow-list of document formats
is accepted, and a hard size cap is enforced on the bytes actually read.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ApiError

# Allowed document kinds -> canonical content type. PDF is the primary format;
# common image formats are accepted because policy schedules are often scanned
# or photographed. No other format is accepted.
_PDF = "application/pdf"
_JPEG = "image/jpeg"
_PNG = "image/png"
_WEBP = "image/webp"

ALLOWED_CONTENT_TYPES = frozenset({_PDF, _JPEG, _PNG, _WEBP})


@dataclass(frozen=True)
class DetectedFile:
    """Result of sniffing an uploaded file."""

    content_type: str
    extension: str


def _looks_like_pdf(data: bytes) -> bool:
    # A PDF must start with "%PDF-" (optionally after a small BOM/whitespace).
    head = data[:1024].lstrip(b"\x00\r\n\t ")
    return head.startswith(b"%PDF-")


def _looks_like_jpeg(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff"


def _looks_like_png(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n"


def _looks_like_webp(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def sniff_document(data: bytes) -> DetectedFile:
    """Identify an allowed document by content, or raise ``ApiError`` (415).

    Never trusts the declared filename/MIME. An empty file is rejected as a
    bad request (400) rather than an unsupported type.
    """
    if not data:
        raise ApiError("Uploaded document is empty", status_code=400)
    if _looks_like_pdf(data):
        return DetectedFile(_PDF, ".pdf")
    if _looks_like_jpeg(data):
        return DetectedFile(_JPEG, ".jpg")
    if _looks_like_png(data):
        return DetectedFile(_PNG, ".png")
    if _looks_like_webp(data):
        return DetectedFile(_WEBP, ".webp")
    raise ApiError(
        "Unsupported document format. Upload a PDF, JPG, PNG, or WEBP file.",
        status_code=415,
    )


_IMAGE_CONTENT_TYPES = frozenset({_JPEG, _PNG, _WEBP})


def sniff_image(data: bytes) -> DetectedFile:
    """Identify an allowed raster image by content, or raise ``ApiError``.

    Used for profile pictures, which must be an image (never a PDF). Like
    :func:`sniff_document` it ignores the declared filename/MIME and decides by
    the file's leading bytes. An empty file is a 400; a non-image is a 415.
    """
    detected = sniff_document(data)
    if detected.content_type not in _IMAGE_CONTENT_TYPES:
        raise ApiError(
            "Unsupported image format. Upload a JPG, PNG, or WEBP image.",
            status_code=415,
        )
    return detected


def enforce_size(data: bytes, *, max_bytes: int) -> None:
    """Reject documents larger than the configured cap (413)."""
    if len(data) > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise ApiError(
            f"Document too large. Maximum size is {mb} MB.",
            status_code=413,
        )
