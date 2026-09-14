"""DB-DSN resolution, redaction, and health-endpoint behavior.

These tests need **no** live Postgres: DSN resolution is pure, and the DB
reachability of /health and /health/db is exercised by monkeypatching
``app.db.session.db_ping``. So the suite stays green in any environment,
including CI without a database.
"""
import os

import pytest
from fastapi.testclient import TestClient

from app.config import database_url, DEFAULT_DATABASE_URL
from app.db.session import redact_dsn


# --------------------------------------------------------------------------- #
# DSN resolution (pure)
# --------------------------------------------------------------------------- #
def test_database_url_defaults_to_credential_free(tmp_path, monkeypatch):
    # Ensure the env var is cleared so we observe the code default.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url() == DEFAULT_DATABASE_URL


def test_database_url_respects_env_override(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    assert database_url() == "postgresql+asyncpg://u:p@h/db"


def test_env_var_wins_over_dotenv(tmp_path, monkeypatch):
    """A real env var must take precedence over a .env file (override=False)."""
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgresql+asyncpg://fromenv@h/db\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://realenv@h/db")
    # Load the .env against a throwaway path: real env must win.
    from app.config import load_env

    load_env(str(env_file))
    assert database_url() == "postgresql+asyncpg://realenv@h/db"


# --------------------------------------------------------------------------- #
# DSN redaction (pure) — passwords must never reach logs/health payloads
# --------------------------------------------------------------------------- #
def test_redact_dsn_masks_user_and_password():
    out = redact_dsn("postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform")
    assert "postgres:postgres" not in out
    assert out.endswith("localhost:5432/ai_agent_platform")
    assert "*****" in out


def test_redact_dsn_masks_user_only():
    out = redact_dsn("postgresql+asyncpg://postgres@localhost/db")
    assert "postgres@localhost" not in out
    assert "*****@localhost/db" in out


def test_redact_dsn_passthrough_unparseable():
    assert redact_dsn("not a url") == "not a url"
    assert redact_dsn("") == ""
    assert redact_dsn(None) == ""


# --------------------------------------------------------------------------- #
# /api/v1/health + /api/v1/health/db behavior (DB mocked, no live PG needed)
# --------------------------------------------------------------------------- #
def _patch_ping(monkeypatch, ok: bool, detail: str = "ok"):
    import app.db.session as session

    async def fake_ping(timeout=5.0):
        return ok, detail

    monkeypatch.setattr(session, "db_ping", fake_ping)
    return session


def test_health_reports_db_reachable_true(monkeypatch):
    session = _patch_ping(monkeypatch, ok=True)
    from app.main import app

    # Force a known DSN so the redacted field is deterministic.
    monkeypatch.setattr(session, "DATABASE_URL", "postgresql+asyncpg://u:secret@h/db")
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database_reachable"] is True
    assert body["database"]["reachable"] is True
    # No password leaks:
    assert "secret" not in r.text
    assert "u:secret" not in r.text


def test_health_reports_db_reachable_false_but_still_200(monkeypatch):
    _patch_ping(monkeypatch, ok=False, detail="ConnectionDoesNotExistError: boom")
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/v1/health")
    # Process is up -> 200, DB down is just a field, not a 500.
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database_reachable"] is False
    assert "ConnectionDoesNotExistError" in body["database"]["detail"]


def test_health_db_strict_200_when_reachable(monkeypatch):
    _patch_ping(monkeypatch, ok=True)
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/v1/health/db")
    assert r.status_code == 200
    assert r.json()["reachable"] is True


def test_health_db_strict_503_when_down(monkeypatch):
    _patch_ping(monkeypatch, ok=False, detail="TimeoutError: no route to PG")
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/v1/health/db")
    assert r.status_code == 503
    body = r.json()
    assert body["reachable"] is False
    assert "no route to PG" in body["detail"]
