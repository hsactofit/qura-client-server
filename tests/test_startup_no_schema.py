"""Startup must not create or migrate the schema (Alembic is the only authority)."""

from __future__ import annotations

import app.db.session as session_mod


def test_startup_does_not_build_engine_or_create_schema(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Fail loudly if anything tries to create the engine or run create_all
    # during request handling / startup in Phase 2.
    def _boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("engine must not be built during startup")

    monkeypatch.setattr(session_mod, "_build_engine", _boom)

    # A health call exercises startup + a request without a database.
    assert client.get("/api/client/health").status_code == 200


def test_app_module_import_has_no_create_all() -> None:
    # Guard against reintroducing a startup schema creator.
    import inspect

    import app.main as main_mod

    source = inspect.getsource(main_mod)
    assert "create_all" not in source
    assert "run_migrations" not in source
