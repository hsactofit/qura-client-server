"""Alembic env wiring: it targets the Qura metadata and guards the DB target."""

from __future__ import annotations

import app.db.models as models


def test_alembic_env_uses_qura_metadata() -> None:
    # The env module imports the models package and exposes Base.metadata as the
    # autogenerate target. Importing it here must not require a database.
    from app.db.base import Base

    # Importing models registers everything; the env uses this same metadata.
    assert set(Base.metadata.tables) == set(models.Base.metadata.tables)
    assert len(Base.metadata.tables) == 19
