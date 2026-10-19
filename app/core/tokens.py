"""Opaque single-use tokens (password reset, invites).

Raw tokens are generated with the OS CSPRNG and shown to the user exactly once
(e.g. in a reset link). Only the SHA-256 hash of a raw token is persisted, so a
database read never reveals a usable token. Lookups hash the presented token and
compare against stored hashes.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_raw_token(num_bytes: int = 32) -> str:
    """A URL-safe random token to embed in a link. Never stored as-is."""
    return secrets.token_urlsafe(num_bytes)


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest of a raw token, for storage and lookup."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
