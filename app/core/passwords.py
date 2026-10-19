"""Password hashing using Argon2id.

Uses argon2-cffi with its secure defaults (Argon2id). Only the encoded hash is
ever stored; plaintext passwords and hashes are never logged. ``verify_password``
returns a boolean and never raises on a wrong password, and reports whether the
stored hash should be re-hashed with current parameters.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Argon2id with library defaults (a sensible, memory-hard configuration).
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an encoded Argon2id hash for ``password``."""
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Verify ``password`` against ``stored_hash``.

    Returns False for a missing hash or any mismatch; never raises for a wrong
    password. A malformed stored hash is treated as a non-match.
    """
    if not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the stored hash was made with outdated parameters."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except Exception:
        return False
