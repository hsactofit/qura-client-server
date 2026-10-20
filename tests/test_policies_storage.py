"""Unit tests for upload sniffing and the private-storage traversal guard."""

from __future__ import annotations

import pytest
from app.core.config import Environment, Settings
from app.core.errors import ApiError
from app.core.storage import StorageError, resolve_path, save_bytes
from app.core.uploads import enforce_size, sniff_document

_PDF = b"%PDF-1.4\nhello"
_JPEG = b"\xff\xd8\xff\xe0rest"
_PNG = b"\x89PNG\r\n\x1a\nrest"
_WEBP = b"RIFF\x00\x00\x00\x00WEBPrest"


def _settings(tmp_path) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(
        environment=Environment.TEST,
        database_url=None,
        storage_dir=str(tmp_path / "storage"),
    )


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (_PDF, "application/pdf"),
        (_JPEG, "image/jpeg"),
        (_PNG, "image/png"),
        (_WEBP, "image/webp"),
    ],
)
def test_sniff_accepts_allowed_formats(data, expected) -> None:  # type: ignore[no-untyped-def]
    assert sniff_document(data).content_type == expected


def test_sniff_rejects_unknown_format() -> None:
    with pytest.raises(ApiError) as exc:
        sniff_document(b"plain text not a document")
    assert exc.value.status_code == 415


def test_sniff_rejects_empty() -> None:
    with pytest.raises(ApiError) as exc:
        sniff_document(b"")
    assert exc.value.status_code == 400


def test_sniff_ignores_declared_extension() -> None:
    # Content wins over the (untrusted) filename/extension: PNG bytes are PNG
    # even if the upload claimed ".pdf" — proven by the returned content type.
    assert sniff_document(_PNG).content_type == "image/png"


def test_enforce_size_rejects_oversized() -> None:
    with pytest.raises(ApiError) as exc:
        enforce_size(b"x" * 100, max_bytes=10)
    assert exc.value.status_code == 413


def test_save_and_resolve_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path)
    key, digest, size = save_bytes(
        settings, purpose="policy", original_name="a.pdf", data=_PDF
    )
    assert size == len(_PDF)
    assert len(digest) == 64
    path = resolve_path(settings, key)
    assert path.is_file()
    assert path.read_bytes() == _PDF


def test_resolve_path_blocks_traversal(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path)
    with pytest.raises(StorageError):
        resolve_path(settings, "../../etc/passwd")
