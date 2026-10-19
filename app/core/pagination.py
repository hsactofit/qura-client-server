"""Shared pagination helpers.

A small, validated page/limit parser used by collection endpoints. Bounds are
enforced so a client cannot request an unbounded or negative page.
"""

from __future__ import annotations

from dataclasses import dataclass

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 100


@dataclass(frozen=True)
class Page:
    page: int
    limit: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


def parse_page(page: int = 1, limit: int = _DEFAULT_LIMIT) -> Page:
    """Clamp page/limit to safe bounds (page >= 1, 1 <= limit <= 100)."""
    safe_page = page if page >= 1 else 1
    safe_limit = limit
    if safe_limit < 1:
        safe_limit = _DEFAULT_LIMIT
    if safe_limit > _MAX_LIMIT:
        safe_limit = _MAX_LIMIT
    return Page(page=safe_page, limit=safe_limit)
