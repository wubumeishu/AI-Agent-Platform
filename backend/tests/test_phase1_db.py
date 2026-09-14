"""Phase 1 数据库迁移与初始化 — 验收测试.

Verifies the Phase-1 resource layer (docs/PHASE1-DB-SCHEMA.sql) is fully
represented in the Alembic chain and (when Postgres is reachable) actually
present in the live database.

Two layers:
  * Offline / structural tests (always run): assert the DDL for the required
    tables, indexes, triggers, function, and seed platforms is present across
    the migration files, so a fresh ``alembic upgrade head`` would create the
    full Phase-1 schema. These never need a live DB.
  * Live integration tests (skipped when Postgres is unreachable): connect to
    the real database and confirm the objects exist and the updated_at trigger
    fires.

Run:
    pytest tests/test_phase1_db.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Required Phase-1 surface (from docs/PHASE1-DB-SCHEMA.sql)
# ---------------------------------------------------------------------------
REQUIRED_MAIN_TABLES = [
    "agent", "persona", "account", "platform",
    "browser_profile", "proxy",
]
# 9 main tables total; the other 3 (agent, persona, ... ) are all listed here.
# The "9 main tables" count in the card = agent, persona, account, platform,
# browser_profile, proxy + the 3 binding tables are counted separately below.
REQUIRED_BINDING_TABLES = [
    "agent_persona_binding",
    "account_browser_binding",
    "account_proxy_binding",
]
REQUIRED_INDEXES = [
    "idx_agent_status",
    "idx_agent_name",
    "idx_persona_version",
    "idx_account_platform",
    "idx_account_status",
    "idx_browser_profile_provider",
    "idx_proxy_status",
]
REQUIRED_TRIGGERS = [
    "update_agent_updated_at",
    "update_persona_updated_at",
    "update_account_updated_at",
    "update_browser_profile_updated_at",
    "update_proxy_updated_at",
]
REQUIRED_TRIGGER_FUNCTION = "update_updated_at_column"
REQUIRED_PLATFORM_SEEDS = ["wechat", "douyin", "xiaohongshu"]

BACKEND_DIR = Path(__file__).resolve().parent.parent
VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"


def _migration_sources() -> str:
    """Concatenated text of every .py migration (the DDL that upgrade runs)."""
    chunks = []
    for p in sorted(VERSIONS_DIR.glob("*.py")):
        chunks.append(p.read_text(encoding="utf-8"))
    return "\n".join(chunks)


_MIGRATIONS = _migration_sources()

# Connection target — matches alembic.ini / .env defaults.
PG_DSN = dict(
    host="localhost",
    port=5432,
    user="postgres",
    password="postgres",
    dbname="ai_agent_platform",
)


def _pg_available() -> bool:
    try:
        import psycopg2

        conn = psycopg2.connect(**PG_DSN, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


requires_pg = pytest.mark.skipif(
    not _pg_available(), reason="Postgres not reachable — live integration checks skipped"
)


# ---------------------------------------------------------------------------
# Offline / structural tests (deterministic, always run)
# ---------------------------------------------------------------------------
class TestMigrationChainStructural:
    """Assert the migration files carry the full Phase-1 DDL."""

    def test_every_required_table_has_create_table(self):
        for table in REQUIRED_MAIN_TABLES + REQUIRED_BINDING_TABLES:
            # op.create_table('<name>', ...) appears across the chain.
            assert re.search(
                rf"create_table\(\s*['\"]{re.escape(table)}['\"]", _MIGRATIONS
            ), f"no create_table for {table} in the migration chain"

    def test_every_required_index_is_created(self):
        for idx in REQUIRED_INDEXES:
            assert re.search(
                rf"['\"]{re.escape(idx)}['\"]", _MIGRATIONS
            ), f"index {idx} not found in the migration chain"

    def test_trigger_function_and_all_five_triggers(self):
        assert REQUIRED_TRIGGER_FUNCTION in _MIGRATIONS, "trigger function missing"
        for trig in REQUIRED_TRIGGERS:
            # Triggers are created either via an f-string loop (002) or an
            # explicit CREATE TRIGGER (021 for persona). Match the name token.
            assert re.search(
                rf"{re.escape(trig)}", _MIGRATIONS
            ), f"trigger {trig} not referenced in the migration chain"

    def test_platform_seed_rows_present(self):
        for code in REQUIRED_PLATFORM_SEEDS:
            assert re.search(rf"['\"]{re.escape(code)}['\"]", _MIGRATIONS), (
                f"platform seed '{code}' not found in the migration chain"
            )

    def test_uuid_extension_enabled(self):
        assert re.search(r"uuid-ossp", _MIGRATIONS, re.IGNORECASE), (
            "uuid-ossp extension is never enabled in the chain"
        )


# ---------------------------------------------------------------------------
# Live integration tests (only when Postgres is reachable)
# ---------------------------------------------------------------------------
@requires_pg
class TestLiveDatabase:
    """Confirm the migrated live database actually has the Phase-1 objects."""

    def _connect(self):
        import psycopg2

        return psycopg2.connect(**PG_DSN)

    def test_tables_exist(self):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        )
        tnames = {r[0] for r in cur.fetchall()}
        conn.close()
        for table in REQUIRED_MAIN_TABLES + REQUIRED_BINDING_TABLES:
            assert table in tnames, f"table {table} missing from live DB"

    def test_indexes_exist(self):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public'"
        )
        inames = {r[0] for r in cur.fetchall()}
        conn.close()
        for idx in REQUIRED_INDEXES:
            assert idx in inames, f"index {idx} missing from live DB"

    def test_triggers_exist(self):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT t.tgname FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            WHERE c.relnamespace = 'public'::regnamespace
              AND NOT t.tgisinternal
            """
        )
        tnames = {r[0] for r in cur.fetchall()}
        conn.close()
        for trig in REQUIRED_TRIGGERS:
            assert trig in tnames, f"trigger {trig} missing from live DB"

    def test_platform_seeds_present(self):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("SELECT code FROM platform WHERE is_deleted = FALSE")
        codes = {r[0] for r in cur.fetchall()}
        conn.close()
        for code in REQUIRED_PLATFORM_SEEDS:
            assert code in codes, f"platform seed '{code}' missing from live DB"

    def test_updated_at_trigger_fires(self):
        """Insert a row, UPDATE it, assert updated_at advanced (autocommit)."""
        import time
        import uuid

        conn = self._connect()
        conn.autocommit = True
        cur = conn.cursor()
        rid = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO agent (id, name, status) VALUES (%s, %s, 'stopped') "
            "RETURNING updated_at",
            (rid, "phase1_trigger_probe"),
        )
        before = cur.fetchone()[0]
        time.sleep(0.3)
        cur.execute("UPDATE agent SET description = 'probe' WHERE id = %s", (rid,))
        cur.execute("SELECT updated_at FROM agent WHERE id = %s", (rid,))
        after = cur.fetchone()[0]
        cur.execute("DELETE FROM agent WHERE id = %s", (rid,))
        conn.close()
        assert after > before, (
            f"updated_at did not advance on agent update "
            f"({before} -> {after}); update_agent_updated_at trigger not firing"
        )
