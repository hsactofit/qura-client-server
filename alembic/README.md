# Alembic migrations (Qura)

Alembic is the **sole** schema authority for the Qura database. The FastAPI app
never creates or migrates the schema at startup, and there is no auto-seeding.

The database URL comes from `QURA_DATABASE_URL` (read by `alembic/env.py` from
Qura settings), not from `alembic.ini`. Every command verifies the target with
the Qura database guard (`app/db/guard.py`): it must use the
`postgresql+asyncpg://` driver and a database name starting with `qura_`.

## Prerequisites

- A dedicated, disposable Qura PostgreSQL database (never a shared or production DB).
- `QURA_DATABASE_URL=postgresql+asyncpg://USER:PASS@HOST:5432/qura_client` in your `.env`.

## Everyday commands

Run from `qura-client-server/` with the project venv active.

```bash
# Inspect the current state
alembic current            # applied revision in the target DB
alembic heads              # must print exactly ONE head
alembic history --verbose  # full revision history

# Create a new revision from model changes (ALWAYS review the output)
alembic revision --autogenerate -m "describe change"

# Apply / roll back
alembic upgrade head       # apply all pending migrations
alembic downgrade -1       # roll back the most recent migration
alembic downgrade base     # roll back everything (empty schema)

# Generate SQL without connecting (offline), for review
alembic upgrade head --sql
```

## Reviewing a migration before applying it

Autogenerate is a starting point, not the final answer. Before committing or
applying any revision:

1. Open the generated file in `alembic/versions/` and read `upgrade()` and
   `downgrade()` in full.
2. Confirm every intended table, column, FK, index, unique and check constraint
   is present and named via the project naming convention.
3. Confirm `downgrade()` actually reverses `upgrade()`.
4. Check for accidental drops or type changes you did not intend.
5. Verify a single head: `alembic heads`.
6. Prefer `alembic upgrade head --sql` to eyeball the DDL.

## Testing the lifecycle on a disposable database

```bash
alembic upgrade head      # create schema
alembic downgrade base    # tear it back down
alembic upgrade head      # re-create (proves both directions)
```

Never point these commands at an unknown or production database. The guard
blocks non-`qura_` targets, but you are responsible for choosing a disposable one.
