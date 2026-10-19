"""Session and CSRF token utilities.

Session model (documented trade-off)
-------------------------------------
Phase 2 ships no ``sessions`` table and Phase 3 forbids schema changes, so this
module does NOT implement per-session server-side records. Instead a session is
an opaque, HMAC-signed, URL-safe token carrying ``user_id`` and an ``issued_at``
timestamp, delivered in an HttpOnly/Secure cookie. The token is signed with the
Qura ``session_secret`` (never a client secret), and the signature is verified
in constant time.

Revocation is real and durable, using the EXISTING ``users.token_invalidated_at``
column: any session whose ``issued_at`` is at or before a user's
``token_invalidated_at`` is rejected. Logout, password reset, and (future)
deactivation bump that column, invalidating every outstanding session for that
user. This survives process restarts because both the secret and the column are
persistent.

Limitation vs. a session table: revocation is USER-LEVEL (all of a user's
sessions at once), not per-session. Per-device/per-session revocation,
server-side listing, and idle-timeout tracking require a dedicated ``sessions``
table added via an Alembic migration (documented in the README as a follow-up).
This is intentionally NOT a plain JWT used as an auth bearer: it is an opaque
cookie value with no client-readable claims contract, and revocation is enforced
against the database on every request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

_SEP = "."


@dataclass(frozen=True)
class SessionToken:
    user_id: str
    issued_at: int  # unix seconds


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    return _b64e(digest.digest())


def issue_session_token(user_id: str, secret: str, *, now: int | None = None) -> str:
    """Create a signed opaque session token for ``user_id``."""
    issued_at = int(now if now is not None else time.time())
    payload = f"{_b64e(user_id.encode('utf-8'))}{_SEP}{issued_at}"
    signature = _sign(payload, secret)
    return f"{payload}{_SEP}{signature}"


def parse_session_token(token: str, secret: str) -> SessionToken | None:
    """Validate the signature and structure; return the claims or None.

    Does NOT check expiry or revocation — the caller does that against the user
    record. Signature comparison is constant-time.
    """
    try:
        user_b64, issued_raw, signature = token.split(_SEP)
    except ValueError:
        return None
    payload = f"{user_b64}{_SEP}{issued_raw}"
    expected = _sign(payload, secret)
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        user_id = _b64d(user_b64).decode("utf-8")
        issued_at = int(issued_raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return SessionToken(user_id=user_id, issued_at=issued_at)


def generate_csrf_token() -> str:
    """A fresh, cryptographically random CSRF token (double-submit value)."""
    return secrets.token_urlsafe(32)


def constant_time_equals(a: str, b: str) -> bool:
    """Constant-time string comparison for CSRF header/cookie checks."""
    return hmac.compare_digest(a, b)
