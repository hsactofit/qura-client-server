"""Private document storage.

Uploaded documents are written under a Qura-owned private directory
(``settings.storage_dir``) and are NEVER served from a public URL. The database
stores an opaque ``storage_key`` (a path relative to the storage root); reads go
through :func:`resolve_path`, which refuses any key that would escape the root
(path-traversal guard). The authenticated, ownership-checked download endpoint
is the only way bytes leave the server.

The backend is deliberately filesystem-based to match the ``stored_files``
schema (``storage_key``, ``sha256``, ``size_bytes``). Swapping in an object
store later only requires reimplementing this module's small surface.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings


class StorageError(RuntimeError):
    """A document could not be stored or located."""


def _storage_root(settings: Settings) -> Path:
    """Absolute, resolved storage root. Created on first use."""
    root = Path(settings.storage_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_suffix(original_name: str | None, fallback: str) -> str:
    """A conservative file suffix derived from the original name.

    Only a short alphanumeric extension is kept; anything unusual falls back to
    ``fallback``. The suffix is cosmetic only — it never influences validation.
    """
    if original_name and "." in original_name:
        ext = original_name.rsplit(".", 1)[-1].lower()
        if ext.isalnum() and 1 <= len(ext) <= 8:
            return f".{ext}"
    return fallback


def build_storage_key(purpose: str, original_name: str | None, suffix: str) -> str:
    """Generate a collision-resistant, non-guessable relative storage key.

    Layout: ``<purpose>/<YYYY>/<MM>/<random>.<ext>``. The random component means
    knowing a key does not let a caller guess another's; authorization is still
    enforced at the row level, this is defence in depth.
    """
    now = datetime.now(UTC)
    token = secrets.token_hex(16)
    safe_purpose = "".join(c for c in purpose if c.isalnum() or c in "-_") or "other"
    return f"{safe_purpose}/{now:%Y}/{now:%m}/{token}{suffix}"


def resolve_path(settings: Settings, storage_key: str) -> Path:
    """Resolve a storage key to an absolute path inside the storage root.

    Raises :class:`StorageError` if the key escapes the root (path traversal).
    """
    root = _storage_root(settings)
    candidate = (root / storage_key).resolve()
    # Must remain inside the root; ``is_relative_to`` rejects ``..`` escapes.
    if not candidate.is_relative_to(root):
        raise StorageError("Resolved path escapes the storage root")
    return candidate


def save_bytes(
    settings: Settings, *, purpose: str, original_name: str | None, data: bytes
) -> tuple[str, str, int]:
    """Persist ``data`` privately and return ``(storage_key, sha256, size)``.

    The sha256 is computed over the exact bytes written and is suitable for
    integrity checks and per-owner duplicate detection.
    """
    suffix = _safe_suffix(original_name, ".bin")
    storage_key = build_storage_key(purpose, original_name, suffix)
    target = resolve_path(settings, storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_bytes(data)
    except OSError as exc:  # pragma: no cover - filesystem failure
        raise StorageError("Failed to write uploaded document") from exc
    digest = hashlib.sha256(data).hexdigest()
    return storage_key, digest, len(data)


def delete_quietly(settings: Settings, storage_key: str) -> None:
    """Best-effort deletion used for compensation when a save half-fails.

    Never raises: cleanup failures must not mask the original error.
    """
    try:
        path = resolve_path(settings, storage_key)
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - compensation must not raise
        return


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
