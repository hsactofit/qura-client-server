"""Reusable column mixins for Qura models.

- ``UUIDPrimaryKeyMixin``  server-generated uuid primary key (gen_random_uuid()).
- ``TimestampMixin``        created_at / updated_at, both server-managed.

Primary keys use PostgreSQL ``uuid`` with the ``gen_random_uuid()`` default
(pgcrypto/pg13+ built-in). This mirrors the verified reference schema so future
data migration can preserve ids, and keeps ids opaque and non-enumerable.
``updated_at`` is kept current with ``onupdate`` at the ORM layer; the initial
migration also sets a DB-side default so direct SQL writes still populate it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
