"""Reference / master data.

Backs the frontend's ``/master-data`` (relationship, gender lists) and ``/faqs``
(category == 'FAQ', where ``label`` is the question and ``value`` the answer).
A single flexible table keyed by ``category`` matches the verified reference
schema. ``metadata`` is JSONB for category-specific extras.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class MasterData(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "master_data"

    category: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    sort_order: Mapped[int] = mapped_column(
        "order", Integer, nullable=False, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    __table_args__ = (Index("ix_master_data_category", "category"),)
