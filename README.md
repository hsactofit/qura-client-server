# qura-client-server

Backend for the Qura Insurance Client Portal.

**Stack:** Python 3.12, FastAPI, PostgreSQL, SQLAlchemy 2.x (async + `asyncpg`),
Alembic, Pydantic. This is a dedicated Qura service with its own configuration,
database, and secrets. It is independent of the `arham-secure-server` reference
backend and never connects to an Arham database.

## Status: Phase 4 — Core Client APIs

Phases 1–4 are implemented. Phase 4 adds the read/write client APIs the portal
needs (dashboard, policies, assets, family, claims, transactions, notifications,
support, reference data). Still deferred: frontend integration and
marketplace/quotes/KYC/proposal/payment/insurer features (out of scope).

### Phase 4 endpoints (all under `/api/client`, all require an authenticated session)

| Method | Path | Purpose | CSRF |
|---|---|---|---|
| GET | `/dashboard` | Stats, recent policies/transactions, coverage summary | — |
| GET | `/policies` | List own policies (optional `?status=`) | — |
| GET | `/policies/{id}` | One policy (ownership-enforced) | — |
| GET | `/assets` | List own assets (optional `?asset_type=`) | — |
| POST | `/assets` | Create asset | yes |
| PUT | `/assets/{id}` | Update own asset | yes |
| DELETE | `/assets/{id}` | Delete own asset | yes |
| GET | `/family` | List own family members | — |
| POST | `/family` | Create family member | yes |
| PUT | `/family/{id}` | Update own family member | yes |
| DELETE | `/family/{id}` | Delete own family member | yes |
| GET | `/claims` | List own claims | — |
| GET | `/claims/{id}` | One claim + documents (ownership-enforced) | — |
| GET | `/transactions` | Paginated history + stats (`?page=&limit=&type=&status=&search=`) | — |
| GET | `/notifications` | Own notifications + active announcements + unread count | — |
| GET | `/notifications/unread-count` | Unread count | — |
| POST | `/notifications/{id}/read` | Mark one read (ownership-enforced) | yes |
| POST | `/notifications/read-all` | Mark all read | yes |
| POST | `/notifications/clear` | Delete given ids (or all) | yes |
| DELETE | `/notifications/{id}` | Delete one (ownership-enforced) | yes |
| GET | `/support/tickets` | List own tickets | — |
| GET | `/support/tickets/{id}` | One ticket (ownership-enforced) | — |
| GET | `/support/tickets/{id}/messages` | Messages (ownership-enforced) | — |
| POST | `/support/tickets/create` | Create ticket | yes |
| POST | `/support/tickets/{id}/messages` | Post message to own ticket | yes |
| GET | `/master-data` | Reference lookups (`?category=`) → `[{label, value}]` | — |
| GET | `/faqs` | FAQ rows (`category='FAQ'`) | — |

All responses use the `{success, message, data}` envelope. Collection fields and
nested shapes match the frontend's TypeScript types; a few frontend-only fields
are mapped safely (`Policy.name` derived from `policy_type`) or returned as
documented empty defaults (`Policy.covered_members`, `Policy.fees`), never
fabricated. Ownership is enforced on every resource: another user's id returns
`404` (no existence disclosure). Mutations reuse the Phase 3 double-submit CSRF.

### Phase 4 limitations and deferred work (no schema change was made)

- **Coverage analysis is partial.** `/dashboard` returns a real
  `totalCurrentCoverage` (sum of active-policy coverage) but marks
  `coverageAnalysis.status = "unavailable"` with empty recommendations: the
  reference backend's coverage/plan engine and plans catalog are not part of the
  Qura schema or this phase.
- **Claims are read-only.** Claim submission and document upload need a secure
  file-upload pipeline (the `stored_files`/`claim_documents` tables exist, but
  upload handling does not). Deferred.
- **Transaction invoices** (`/transactions/{id}/invoice`) are deferred (need an
  invoice generator); the list + stats are implemented.
- **Policy download / status / track** and all marketplace endpoints are out of
  scope (insurer + file integrations).
- **Support RM/assigned-tickets view and WebSocket live updates** are deferred;
  the frontend already falls back to polling. `sender_profile` on messages is
  returned as `null` pending a user-join enrichment.
- **Reference data is not seeded.** `/master-data` and `/faqs` return whatever
  rows exist; an empty table yields an empty list. Seeding reference/FAQ rows is
  a later, explicitly-approved step (CLI/data migration), not done here.
- **No live database / browser integration was exercised.** The API test suite
  runs entirely against the in-memory fake DB layer (`tests/fakes.py`).

### Phase 4 verified behaviour change (justified)

The Phase 3 validation-error handler returned pydantic's raw `errors()`, which
for a custom `field_validator` raising `ValueError` included a non-serialisable
exception in `ctx` — producing a 500 instead of 422 (and potentially echoing
submitted input). `app/core/errors.py` now sanitises validation errors to
`{type, loc, msg}` only. This fixes a real defect and removes input echoing
(a small security improvement); no auth/session/CSRF/password behaviour changed.

## Status: Phase 3 — Authentication and Profile APIs

Phases 1 (foundation), 2 (schema) and 3 (auth + profile) are implemented.

Phase 1 recap: FastAPI app factory, `QURA_`-prefixed settings with a weak-secret
guard, lazy async SQLAlchemy wiring, the `{success, message, data}` envelope and
central error handling, health/readiness endpoints, CORS and security headers,
redacting logger, default-deny authorization scaffolding, Docker, and CI.
Phase 2 recap: SQLAlchemy models, Alembic (sole schema authority), DB guard.

### Phase 3 endpoints (match the existing frontend contract)

| Method | Path | Purpose | Auth / CSRF |
|---|---|---|---|
| POST | `/api/client/auth/signup` | Invite-only registration | public bootstrap |
| POST | `/api/client/auth/signin` | Email + password login | public bootstrap |
| GET | `/api/client/auth/session` | Session bootstrap for the SPA | session cookie |
| POST | `/api/client/auth/signout` | Logout (revokes sessions) | session + CSRF |
| POST | `/api/client/auth/invite/verify` | Validate an invite token | public |
| POST | `/api/client/auth/forgot-password` | Request a reset (no enumeration) | public |
| POST | `/api/client/auth/reset-password` | Consume a reset token | public |
| GET | `/api/client/user/profile` | Current user's profile | session cookie |
| PUT | `/api/client/user/profile/update` | Update allowed profile fields | session + CSRF |
| GET | `/api/client/user/settings` | Read settings | session cookie |
| PUT | `/api/client/user/settings` | Update settings | session + CSRF |

All responses use the `{success, message, data}` envelope. The auth payload is
`{user, csrf_token}`; the `user` object exposes `date_of_birth`, `pan_number`
and `aadhaar_number` at the top level and `annualIncome`/`occupation`/`lifestyle`
under `preferences` — composed from the `users` + `user_profiles` split.

### Security controls (Phase 3)

- **Passwords:** Argon2id via `argon2-cffi`; only the encoded hash is stored;
  plaintext and hashes are never logged.
- **Sessions:** opaque, HMAC-signed cookie `qura_client_session`
  (HttpOnly, SameSite=Lax, `Secure` outside dev/test), signed with
  `QURA_SESSION_SECRET`. The current user is derived only from the validated
  session, never a client-supplied id.
- **Revocation:** real and durable via the existing `users.token_invalidated_at`
  column — logout and password reset bump it, rejecting all outstanding
  sessions. **Trade-off / limitation:** this is *user-level* revocation, not
  per-session. Per-device revocation, server-side session listing, and idle
  timeout need a dedicated `sessions` table (future Alembic migration). This is
  **not** a stateless JWT used as a bearer: the cookie is opaque and revocation
  is checked against the database on every request.
- **CSRF:** double-submit. Cookie `qura_client_csrf` (JS-readable) is echoed as
  the `X-CSRF-Token` header and compared in constant time on cookie-authenticated
  mutations (`signout`, profile/settings updates). Public bootstrap endpoints
  (signin/signup/forgot/reset/invite-verify) are exempt; the session cookie is
  only issued on success.
- **Reset tokens:** cryptographically random, stored only as a SHA-256 hash,
  single-use (consumed atomically), time-limited (`QURA_PASSWORD_RESET_TTL_SECONDS`).
- **Enumeration resistance:** signin and forgot-password return generic results
  regardless of whether the account exists.
- **Mass-assignment:** update schemas use `extra="forbid"`; role, status,
  is_deleted, id and email cannot be set through profile endpoints, and the
  registration role comes only from the invite.

### Known blockers / limitations (Phase 3)

- **No `sessions` table** (Phase 2 did not define one, and Phase 3 forbids schema
  changes). Sessions use the signed-cookie + `token_invalidated_at` model above.
  A `sessions` table is the documented follow-up for per-session control.
- **Invite creation is not implemented** (admin phase). Registration validates
  against existing `invites` rows but nothing creates them yet, so end-to-end
  signup needs an invite seeded by a future admin/CLI path.
- **No email delivery is configured.** forgot-password runs the full safe token
  lifecycle but does not send mail. In **development only**, the response
  includes `debug_token` so a developer can complete the flow; it is never
  returned in test/staging/production and never logged. Email delivery is a
  documented follow-up.
- **PII at rest is not encrypted/masked.** `pan_number`, `aadhaar_number` and
  `date_of_birth` are stored as plaintext typed columns (isolated in
  `user_profiles`) and returned only because the existing frontend requires
  them. Column-level encryption/masking is not implemented in this phase.
- **Frontend integration not exercised end-to-end.** The contract (paths,
  payloads, envelope, cookie/CSRF names) is matched and covered by backend tests,
  but the React app was not run against this backend.
- **Live PostgreSQL not exercised.** The test suite uses an in-memory fake of the
  DB layer (clearly labelled). No migration was run and no database was
  connected in this phase.

Phase 2 adds:

- SQLAlchemy 2.x typed models for the client portal (`app/db/models/`).
- A shared `Base` + deterministic naming convention (`app/db/base.py`) and
  reusable `UUIDPrimaryKeyMixin` / `TimestampMixin` (`app/db/mixins.py`).
- A database-target guard (`app/db/guard.py`): refuses any DSN that is not the
  async driver or whose database name does not start with `qura_`.
- Alembic configured to use the Qura metadata and `QURA_DATABASE_URL`
  (`alembic.ini`, `alembic/env.py`), with the initial migration
  `0001_initial` (`alembic/versions/`).
- Tests covering metadata registration, keys, FKs/ondelete, constraints,
  indexes, JSONB fields, the guard, single-head/one-base, and that the
  migration's tables/columns match the models — all without a live database.

### Model / module organization (`app/db/models/`)

| Module | Models | Notes |
|---|---|---|
| `identity.py` | `User`, `UserProfile`, `UserSetting`, `Invite`, `PasswordResetToken` | Account + typed PII split; auth fields present but unused until the auth phase. |
| `policies.py` | `Policy` | Insurance-extension fields; nullable `policy_number` with a partial-unique index. |
| `claims.py` | `Claim`, `ClaimDocument` | `timeline` JSONB; documents normalized into a table. |
| `assets.py` | `Asset` | Vehicle/property; user CASCADE, policy SET NULL. |
| `family.py` | `FamilyMember` | |
| `transactions.py` | `Transaction` | Read-only history; no create/payment workflow. |
| `engagement.py` | `Notification`, `Announcement` | |
| `support.py` | `SupportTicket`, `TicketMessage` | Owner + assigned-RM FKs to `users`. |
| `files.py` | `StoredFile` | Single upload registry (schema only; secure storage later). |
| `reference.py` | `MasterData` | FAQ / relationship / gender lists. |
| `admin.py` | `AuditLog` | Admin action trail. |

### Main entities and relationships

- `User` 1–1 `UserProfile`, 1–1 `UserSetting` (both CASCADE, delete-orphan).
- `User` 1–many `Policy`, `Claim`, `Transaction` (FK `RESTRICT` — history is kept).
- `User` 1–many `Asset`, `FamilyMember`, `Notification`, `StoredFile` (CASCADE).
- `Policy` 1–many `Claim`, `Transaction`, `Asset` (dependent FKs `SET NULL`).
- `Claim` 1–many `ClaimDocument` (CASCADE); documents link to `StoredFile`.
- `SupportTicket` has owner (`user_id`, CASCADE) and `assigned_rm_id` (SET NULL);
  1–many `TicketMessage` (CASCADE; `sender_id` SET NULL).

### JSONB fields (documented structure)

| Table.column | Shape |
|---|---|
| `user_profiles.lifestyle` | `{smoker: bool, alcohol: bool, exercise: str, checkups?: str}` |
| `user_settings.dashboard_config` | flexible UI prefs (notification channels, language, font size, layout) |
| `policies.benefits` / `policies.exclusions` | `string[]` |
| `claims.timeline` | `[{status: str, date: iso8601, note: str}]` |
| `assets.metadata` | free-form asset extras |
| `audit_logs.changes` | `{field: [old, new]}` |
| `master_data.metadata` | category-specific extras |

Derived / mapped (NOT columns): frontend `Policy.name` (from `policy_type`),
`Policy.covered_members`, `Policy.fees`, and `Transaction.policy_number` /
`insurer_name` (joined from the policy). These are composed at the response layer
in a later phase, not stored.

## Requirements

- Python 3.12 (verified locally as 3.12.10). The project pins `requires-python >=3.12,<3.13`.
- Running the app needs no database (health only). Applying migrations requires a
  dedicated Qura PostgreSQL database (see below). The schema uses PostgreSQL
  features (JSONB, `uuid`, `gen_random_uuid()` from the `pgcrypto` extension).

## Local setup

```bash
# From qura-client-server/
python -m venv .venv
.venv\Scripts\Activate.ps1       # Windows PowerShell
pip install ".[dev]"             # quote the extras in PowerShell/zsh

cp .env.example .env             # then edit values

# Run the API (health only so far)
uvicorn app.main:app --reload --port 8787
# Liveness:  GET http://127.0.0.1:8787/api/client/health
# Readiness: GET http://127.0.0.1:8787/api/client/health/ready
```

## Database and migrations

Alembic is the **sole** schema authority. The app never creates or migrates the
schema at startup and never auto-seeds. See `alembic/README.md` for the full
workflow; the essentials:

### Initialize a dedicated development database

Use a disposable Qura database whose name starts with `qura_` (the guard rejects
anything else, and never falls back to another project's database). For example,
with Docker:

```bash
docker run --rm -e POSTGRES_USER=qura -e POSTGRES_PASSWORD=quradev \
  -e POSTGRES_DB=qura_client -p 55432:5432 postgres:16-alpine
```

Then set in `.env`:

```
QURA_DATABASE_URL=postgresql+asyncpg://qura:quradev@localhost:55432/qura_client
```

### Inspect, apply, and roll back

```bash
alembic heads                 # must show exactly one head
alembic history --verbose
alembic current               # applied revision in the target DB

alembic upgrade head          # apply migrations (requires a live qura_ DB)
alembic downgrade -1          # roll back one
alembic downgrade base        # roll back to empty

alembic upgrade head --sql    # render DDL offline, no DB connection

# Create a new revision from model changes, then REVIEW it before applying:
alembic revision --autogenerate -m "describe change"
```

> **Always review a generated migration before applying it.** Autogenerate is a
> starting point: read `upgrade()`/`downgrade()`, confirm constraints, indexes
> and FK `ondelete` behavior, verify a single head, and prefer
> `alembic upgrade head --sql` to inspect the DDL.

## Tests

```bash
pytest                         # full suite (Phase 1 + Phase 2)
ruff check app tests alembic
mypy app
```

Which checks need a live PostgreSQL database:

- **No database required:** the entire current test suite. Model metadata, the
  guard, single-head, and the offline migration/model match run against
  metadata; the auth and profile API tests run against an **in-memory fake of
  the database layer** (`tests/fakes.py`, clearly labelled). This fake emulates
  the small slice of the async-session API the services use; it does not verify
  real PostgreSQL behaviour.
- **Requires a live `qura_` database (not run here):** `alembic upgrade head` /
  `downgrade` lifecycle execution, and any real constraint/JSONB/UUID behaviour.
  These remain manual and unverified.

## Environment variables

All variables use the `QURA_` prefix. See `.env.example` for the full list. Key ones:

| Variable | Purpose | Notes |
|---|---|---|
| `QURA_ENVIRONMENT` | `development` / `test` / `staging` / `production` | Controls docs exposure and the secret guard. |
| `QURA_DATABASE_URL` | Qura PostgreSQL DSN | Must start with `postgresql+asyncpg://` and name a `qura_*` database. Optional until migrations are run. |
| `QURA_DATABASE_NAME_PREFIX` | Required DB-name prefix | Defaults to `qura_`; the guard refuses any other database. |
| `QURA_SESSION_SECRET` | Signs the opaque session cookie | Must be strong (>= 32 chars, not a known default) outside development. |
| `QURA_SESSION_COOKIE_NAME` | Session cookie name | Defaults to `qura_client_session`. |
| `QURA_CSRF_COOKIE_NAME` | CSRF cookie name | Defaults to `qura_client_csrf` (the name the frontend already reads). |
| `QURA_SESSION_MAX_AGE_SECONDS` | Session lifetime / cookie max-age | Defaults to 7 days. |
| `QURA_PASSWORD_RESET_TTL_SECONDS` | Reset-token time-to-live | Defaults to 30 minutes. |
| `QURA_CORS_ALLOW_ORIGINS` | Comma-separated allow-list | Empty disables CORS. Same-origin routing is planned. |
| `QURA_LOG_LEVEL` / `QURA_LOG_JSON` | Logging | JSON logs by default; sensitive values are redacted. |

Never commit a real `.env`; only `.env.example` is tracked.

## Docker

```bash
docker build -t qura-client-server .
docker run --rm -p 8787:8787 --env-file .env qura-client-server
```

## Safety notes

- No reference-backend database connection, no raw-SQL shim, and no startup
  migration/seed mechanism.
- Alembic is the sole schema authority; the app never creates or migrates the
  schema at startup.
- The database-target guard refuses any DSN that is not the async driver or whose
  database name does not start with `qura_`, and never falls back to another
  project's database.
- Secrets are redacted from logs and from the startup config summary; the guard's
  error messages do not echo credentials.
- The schema starts empty: no customer records, PII, or uploaded files are seeded
  or migrated in this phase.
