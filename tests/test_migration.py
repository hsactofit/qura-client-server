"""Alembic configuration and the initial migration (no live database).

Verifies:
- Exactly one migration head.
- The initial revision is the base (no down_revision).
- The migration's upgrade() creates the same table set the models declare, and
  downgrade() drops them all — collected by executing the migration against a
  recording stub in place of alembic.op (so no database is needed).
- Alembic's ScriptDirectory loads from the project config.
"""

from __future__ import annotations

from pathlib import Path

import app.db.models as models
from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.test_models_metadata import EXPECTED_TABLES, TABLES_IN_INITIAL_MIGRATION

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return cfg


def test_single_head() -> None:
    script = ScriptDirectory.from_config(_alembic_config())
    heads = script.get_heads()
    assert len(heads) == 1, f"expected one Alembic head, found {heads}"


def test_initial_revision_is_base() -> None:
    script = ScriptDirectory.from_config(_alembic_config())
    base_revs = list(script.get_bases())
    assert base_revs == ["0001_initial"]
    rev = script.get_revision("0001_initial")
    assert rev.down_revision is None


def test_migration_chain_is_linear() -> None:
    """The migrations form a single unbroken 0001 -> ... -> head chain."""
    script = ScriptDirectory.from_config(_alembic_config())
    revs = list(script.walk_revisions())  # head-first
    # Each revision's down_revision must point at the next one in the walk.
    for newer, older in zip(revs, revs[1:], strict=False):
        assert newer.down_revision == older.revision
    assert revs[-1].revision == "0001_initial"


class _RecordingOp:
    """Captures create_table/drop_table calls from a migration module.

    For create_table it records the column names from the sa.Column() args so the
    migration's columns can be compared to the model columns without a database.
    """

    def __init__(self) -> None:
        self.created: list[str] = []
        self.dropped: list[str] = []
        self.columns: dict[str, set[str]] = {}

    def create_table(self, name, *args, **kwargs):  # type: ignore[no-untyped-def]
        import sqlalchemy as sa

        self.created.append(name)
        self.columns[name] = {
            arg.name for arg in args if isinstance(arg, sa.Column)
        }

    def drop_table(self, name, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.dropped.append(name)

    def create_index(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        pass

    def drop_index(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        pass

    def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        pass


def _load_migration_module(filename: str, mod_name: str):  # type: ignore[no-untyped-def]
    import importlib.util

    path = PROJECT_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_initial_module():  # type: ignore[no-untyped-def]
    return _load_migration_module(
        "20261020_0001_0001_initial_schema.py", "qura_initial_migration"
    )


# (filename, module name) for every create_table migration, in apply order.
# Backfill-only migrations (e.g. 0002) create no tables and are omitted here.
_TABLE_MIGRATIONS = [
    ("20261020_0001_0001_initial_schema.py", "qura_migration_0001"),
    ("20261020_0003_0003_kyc_documents.py", "qura_migration_0003"),
]


def _collect_created(monkeypatch) -> _RecordingOp:  # type: ignore[no-untyped-def]
    """Run every table-creating migration's upgrade() against the recorder."""
    recorder = _RecordingOp()
    for filename, mod_name in _TABLE_MIGRATIONS:
        module = _load_migration_module(filename, mod_name)
        monkeypatch.setattr(module, "op", recorder)
        module.upgrade()
    return recorder


def test_initial_upgrade_creates_initial_tables(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    module = _load_initial_module()
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.upgrade()

    assert set(recorder.created) == TABLES_IN_INITIAL_MIGRATION


def test_all_migrations_create_all_model_tables(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Across every migration, the created tables equal the model table set."""
    recorder = _collect_created(monkeypatch)
    assert set(recorder.created) == EXPECTED_TABLES
    assert set(recorder.created) == set(models.Base.metadata.tables)


def test_migration_columns_match_models(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Every model column exists in the migrations, and vice versa (offline)."""
    recorder = _collect_created(monkeypatch)

    for table_name, table in models.Base.metadata.tables.items():
        model_cols = {c.name for c in table.columns}
        migration_cols = recorder.columns[table_name]
        assert migration_cols == model_cols, (
            f"column mismatch for {table_name}: "
            f"model-only={model_cols - migration_cols}, "
            f"migration-only={migration_cols - model_cols}"
        )


def test_downgrade_drops_all_model_tables(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    module = _load_initial_module()
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.downgrade()

    assert set(recorder.dropped) == TABLES_IN_INITIAL_MIGRATION


def test_downgrade_is_reverse_dependency_order(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A dependent table must be created after, and dropped before, its parent."""
    module = _load_initial_module()
    rec = _RecordingOp()
    monkeypatch.setattr(module, "op", rec)
    module.upgrade()
    module.downgrade()

    # users is created first and dropped last.
    assert rec.created[0] == "users"
    assert rec.dropped[-1] == "users"
    # claim_documents depends on claims: created after, dropped before.
    assert rec.created.index("claim_documents") > rec.created.index("claims")
    assert rec.dropped.index("claim_documents") < rec.dropped.index("claims")
