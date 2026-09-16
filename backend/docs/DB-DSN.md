# Database DSN / Credentials Policy (t_a2b0e658)

## Problem (from t_fc2490b1)
`app/db/session.py` built its engine from a credential-free default DSN:

```
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/ai_agent_platform")
```

Against the local PostgreSQL instance that DSN **cannot authenticate** — it has
no username/password — so a plain `uvicorn app.main:app` or
`python run_server.py` started the HTTP layer but returned 500 on *any*
DB-backed request. The P0 workflow tables (alembic 020) therefore could not be
reached under the default config.

## Policy
Credentials are **never hard-coded in source**. The service resolves its DSN
from a single source — `app.config.database_url()` — in this order:

1. **Real environment variable** `DATABASE_URL` (always wins — CI / containers /
   launch scripts).
2. **`backend/.env`** (local dev, **gitignored**; copied from `.env.example`).
   Loaded at import time by `app/db/session.py` via `python-dotenv` with
   `override=False`, so it can never shadow a real env var.
3. **Credential-free code default** (last resort only — it will not
   authenticate against a typical local Postgres).

A deployment that wants to work out-of-the-box ships a working, credentialed
DSN through (1) or (2). This local repo ships `backend/.env`
(`postgres:postgres` → `localhost:5432/ai_agent_platform`) so it is usable
immediately; that file is not committed.

## Boot-time guardrail
`app/main.py` startup now pings the DB (`SELECT 1`, bounded):
- DB reachable → log INFO with the **redacted** DSN.
- DB unreachable → log a loud WARNING with the redacted DSN + the error.
  - With `DB_REQUIRED_ON_STARTUP=1` (or true/yes), boot **refuses to start**
    (hard-fail) instead of coming up half-working.

## Health endpoints
- `GET /api/v1/health` — process liveness **plus** a live `database.reachable`
  field (and a `dsn` that is password-redacted). The running service still
  reports `status: "ok"` so a down DB is visible without the whole endpoint 500ing.
- `GET /api/v1/health/db` — strict probe: **200** when reachable, **503** when
  not, with a safe-to-expose body (no password). For monitors / load
  balancers / CI.

## Files
- `app/config.py` — `load_env()`, `database_url()`, `db_required_on_startup()`.
- `app/db/session.py` — uses the configured DSN; adds `db_ping()` and
  `redact_dsn()` (password-safe).
- `app/main.py` — boot guard + DB-aware `/health` + `/health/db`.
- `run_server.py` — loads `.env` explicitly before starting uvicorn.
- `.env.example` — template + policy; `.env` (gitignored) — local working config.

## Verification
`tests/test_db_dsn.py` asserts the pure DSN-resolution + redaction behavior
**without** needing Postgres, so it stays green in any environment.

## Timezone convention (ADR-019 — P6AN-17 P2-3)

The DSN's target PostgreSQL instance runs session/role `TimeZone =
Asia/Tokyo (JST)`, **not UTC**. This is load-bearing for every time column:

- **All time columns are aware-UTC `timestamptz`.** ORM columns use
  `DateTime(timezone=True)` with a `datetime.now(timezone.utc)` default.
  `datetime.utcnow()` (naive) is **forbidden** — a naive value written into a
  `timestamptz` column is re-interpreted in the session tz (JST here), a
  silent ±9h drift.
- **Query bounds are aware-UTC and bind directly** to `timestamptz` columns as
  absolute instants. No per-table `_naive_utc` stripping.
- **Column type changes must use `ALTER ... TYPE timestamptz USING
  (col AT TIME ZONE 'UTC')`.** A bare `CAST`/`ALTER TYPE` reinterprets the
  stored naive value in the session tz → −9h drift on this server.

Migration `032_unify_source_time_tz` unified the last six naive source tables
(lead / customer / customer_identity / lifecycle_stage / lifecycle_stage_log
/ tag, 10 columns) and is idempotent / re-runnable (re-type fires only while a
column is still naive). See ADR-019 in `docs/DECISIONS.md`.
