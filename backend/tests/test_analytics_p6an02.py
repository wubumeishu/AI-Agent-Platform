"""P6AN-02 Dashboard overview API: unit + API tests.

Layers (repo convention, cf. test_analytics_p6an01.py / test_analytics_p6an08.py):

1. **Window resolution** — pure, offline.
2. **Cache** — key isolation, TTL memory cache, Redis degrade-to-memory,
   URL redaction.
3. **Service SQL builders ("对拍 SQL")** — a fake session with scripted
   aggregate results; assertions check the emitted SQL text (agent binding
   subquery, P6AN-05 status-based conversion, no lifecycle_stage_code
   coupling) and the metric math.
4. **API (router + real service, faked DB)** — a standalone FastAPI app
   mounting ONLY the dashboard router (no app.main: the shared main.py and
   the analytics router stay known transient hotspots between sibling P6AN
   cards). Canned aggregate results drive the real service end-to-end:
   unified schema, filter forwarding, 400 window validation, 422 bounds,
   cache hit/skip semantics (cache hit issues zero SQL).

Live-DB performance acceptance (P95 < 500ms @ 10k messages) is executed in
a QA session against a scratch DB — see docs/P6AN-02-dashboard-overview.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, List
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.routers.dashboard as dr
from app.db.session import get_db
from app.schemas.dashboard import (
    AgentsOverview,
    DashboardOverviewResponse,
)
from app.services import dashboard_cache as cache_mod
from app.services.dashboard_cache import (
    MemoryDashboardCache,
    RedisDashboardCache,
    build_cache_key,
    resolve_cache_url,
)
from app.services.dashboard_service import (
    CONVERTED_LEAD_STATUS,
    DashboardOverviewService,
    _resolve_window,
)


# =====================================================================
# 1. Window resolution
# =====================================================================

class TestResolveWindow:
    NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_default_days_window(self):
        s, e, days = _resolve_window(None, None, 30, now=self.NOW)
        assert e == self.NOW
        assert s == self.NOW - timedelta(days=30)
        assert days == 30

    def test_explicit_range_wins(self):
        s = datetime(2026, 9, 1, tzinfo=timezone.utc)
        e = datetime(2026, 9, 8, tzinfo=timezone.utc)
        rs, re_, days = _resolve_window(s, e, 30, now=self.NOW)
        assert rs == s and re_ == e and days == 0

    def test_start_only_defaults_end_to_now(self):
        s = datetime(2026, 9, 10, tzinfo=timezone.utc)
        rs, re_, days = _resolve_window(s, None, 30, now=self.NOW)
        assert rs == s and re_ == self.NOW

    def test_end_only_starts_days_before_end(self):
        e = datetime(2026, 9, 15, tzinfo=timezone.utc)
        rs, re_, days = _resolve_window(None, e, 7, now=self.NOW)
        assert re_ == e and days == 7 and rs == e - timedelta(days=7)

    def test_naive_inputs_treated_as_utc(self):
        s, e = datetime(2026, 9, 1), datetime(2026, 9, 2)
        rs, re_, _ = _resolve_window(s, e, 30, now=self.NOW)
        assert rs.tzinfo is not None and re_.tzinfo is not None

    def test_inverted_window_rejected(self):
        s = datetime(2026, 9, 5, tzinfo=timezone.utc)
        e = datetime(2026, 9, 1, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            _resolve_window(s, e, 30, now=self.NOW)

    def test_equal_bounds_rejected(self):
        t = datetime(2026, 9, 5, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            _resolve_window(t, t, 30, now=self.NOW)


# =====================================================================
# 2. Cache
# =====================================================================

class TestCache:
    def test_same_params_same_key(self):
        a = build_cache_key("2026-09-01T00:00:00", "", "30", None, None)
        b = build_cache_key("2026-09-01T00:00:00", "", "30", None, None)
        assert a == b
        assert a.startswith("analytics:dashboard:overview:")

    def test_different_params_different_keys(self):
        k0 = build_cache_key("", "", "30", None, None)
        k_agent = build_cache_key("", "", "30", str(uuid4()), None)
        k_channel = build_cache_key("", "", "30", None, "wechat")
        k_days = build_cache_key("", "", "7", None, None)
        assert len({k0, k_agent, k_channel, k_days}) == 4

    def test_resolve_no_redis_env_defaults_to_memory(self):
        cache_mod.reset_dashboard_cache()
        assert resolve_cache_url() is None
        cache = cache_mod.get_dashboard_cache()
        assert isinstance(cache, MemoryDashboardCache)

    async def test_memory_ttl_expiry(self):
        cache = MemoryDashboardCache(ttl=0)
        await cache.set("k", "v")
        assert await cache.get("k") is None

    async def test_memory_roundtrip(self):
        cache = MemoryDashboardCache(ttl=60)
        await cache.set("k", "v")
        assert await cache.get("k") == "v"
        assert await cache.get("missing") is None

    async def test_redis_degrades_to_memory_when_unavailable(self):
        # Dead port: ping fails -> fallback engages, never raises.
        cache = RedisDashboardCache("redis://127.0.0.1:63999/0", ttl=60)
        await cache.set("k", "v")
        assert await cache.get("k") == "v"  # served from memory fallback
        assert cache._degraded is True
        assert cache._client is None

    def test_redact_url_masks_credentials(self):
        from app.services.dashboard_cache import _redact_url

        out = _redact_url("redis://user:secret@host:6379/0")
        assert "secret" not in out and "user" not in out
        assert "***" in out

    def test_redact_url_plain_unchanged(self):
        from app.services.dashboard_cache import _redact_url

        assert _redact_url("redis://localhost:6379/0") == "redis://localhost:6379/0"


# =====================================================================
# 3. Service SQL builders (fake session)
# =====================================================================

class _Scalar:
    """Canned ``Result`` for aggregate scalar queries."""

    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def all(self):
        return []


class _Rows:
    """Canned ``Result`` for grouped (non-scalar) queries."""

    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def scalar(self):
        return None


class FakeDB:
    """Fake session: scripted results, then sensible defaults.

    The P6AN-02 service issues:
      * scalar aggregate counts (need ``.scalar()``), and
      * grouped queries (need ``.all()``) inside ``_by_agent``.
    A script shorter than the actual query count falls back to
    ``_Scalar(0)`` / empty rows, so section tests only need to script the
    queries they assert on.
    """

    def __init__(self, results: List[Any] = None, by_agent_rows: List[Any] = None):
        self.scripts = list(results or [])
        self.by_agent_rows = list(by_agent_rows or [])
        self.statements: List[Any] = []
        self._executed = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        # The 5th+ query of a compute() is the grouped by_agent query;
        # direct _by_agent calls see it as their first query when the
        # scalar queue is exhausted. Route by queue state:
        if self.scripts:
            return self.scripts.pop(0)
        if self.by_agent_rows:
            return _Rows(self.by_agent_rows.pop(0))
        return _Scalar(0)

    def sql(self, i: int) -> str:
        return str(self.statements[i].compile(compile_kwargs={"literal_binds": True}))


DAY = datetime(2026, 9, 1, tzinfo=timezone.utc)
DAY_END = DAY + timedelta(days=30)


class TestServiceSections:
    async def test_agents_counts_live_and_active(self):
        db = FakeDB([_Scalar(5), _Scalar(3)])
        res = await DashboardOverviewService(db)._agents()
        assert res == AgentsOverview(total=5, active=3)
        assert "status = 'active'" in db.sql(1)
        assert "is_deleted = false" in db.sql(0).lower()

    async def test_conversion_uses_p6an05_status_source_of_truth(self):
        db = FakeDB([_Scalar(4), _Scalar(100), _Scalar(40)])
        res = await DashboardOverviewService(db)._conversion(DAY, DAY_END, agent_id=None)
        assert res.new_leads == 4
        assert res.total_leads == 100
        assert res.closed_leads == 40
        assert res.conversion_rate == 0.4
        # Converted-count query must key on lead.status, NOT lifecycle_stage_code.
        sql = db.sql(2)
        assert "lead.status = 'converted'" in sql
        assert "lifecycle_stage_code" not in sql
        assert CONVERTED_LEAD_STATUS == "converted"

    async def test_conversion_agent_filter_scopes_new_leads_via_binding(self):
        agent = uuid4()
        db = FakeDB([_Scalar(4), _Scalar(100), _Scalar(40)])
        await DashboardOverviewService(db)._conversion(DAY, DAY_END, agent_id=agent)
        assert "agent_customer_binding" in db.sql(0)

    async def test_conversion_rate_none_when_no_leads(self):
        db = FakeDB([_Scalar(0), _Scalar(0), _Scalar(0)])
        res = await DashboardOverviewService(db)._conversion(DAY, DAY_END, None)
        assert res.conversion_rate is None and res.total_leads == 0

    async def test_agent_filter_scopes_conversations_via_binding_subquery(self):
        agent = uuid4()
        db = FakeDB([_Scalar(2), _Scalar(6.5), _Scalar(7), _Scalar(11)])
        res = await DashboardOverviewService(db)._conversations(
            DAY, DAY_END, agent_id=agent, channel=None
        )
        assert res.new == 2
        assert res.active == 7
        assert res.total_messages == 11
        assert res.avg_messages_per_new_conversation == 6.5
        # New-conversations query must semi-join agent_customer_binding.
        assert "agent_customer_binding" in db.sql(0)
        # The message count is scoped by messages.agent_id.
        assert "messages.agent_id" in db.sql(3)

    async def test_channel_filter_applies_to_conversation_and_message_queries(self):
        db = FakeDB([_Scalar(1), _Scalar(None), _Scalar(3), _Scalar(9)])
        res = await DashboardOverviewService(db)._conversations(DAY, DAY_END, None, channel="wechat")
        assert "channel = 'wechat'" in db.sql(0)
        assert "messages.channel = 'wechat'" in db.sql(3)
        assert res.avg_messages_per_new_conversation is None

    async def test_message_success_rate_completed_denominator_only(self):
        # total=25, delivered=10, failed=5, outbound=20
        db = FakeDB([_Scalar(25), _Scalar(10), _Scalar(5), _Scalar(20)])
        res = await DashboardOverviewService(db)._messages(DAY, DAY_END, None, None)
        assert res.total == 25 and res.sent == 20
        assert res.success_rate == pytest.approx(10 / 15, abs=1e-4)
        assert "delivered" in db.sql(1) and "read" in db.sql(1)

    async def test_message_success_rate_none_when_no_completed(self):
        db = FakeDB([_Scalar(10), _Scalar(0), _Scalar(0), _Scalar(8)])
        res = await DashboardOverviewService(db)._messages(DAY, DAY_END, None, None)
        assert res.success_rate is None

    async def test_by_agent_groups_top_agents_with_stats(self):
        a1, a2 = uuid4(), uuid4()
        db = FakeDB(by_agent_rows=[
            [
                SimpleNamespace(agent_id=a1, messages=30),
                SimpleNamespace(agent_id=a2, messages=10),
            ],
            [
                SimpleNamespace(agent_id=a1, delivered=27, failed=3),
                SimpleNamespace(agent_id=a2, delivered=10, failed=0),
            ],
            [
                SimpleNamespace(id=a1, name="A"),
                SimpleNamespace(id=a2, name="B"),
            ],
            [
                (a1, 5), (a2, 2),
            ],
        ])
        res = await DashboardOverviewService(db)._by_agent(DAY, DAY_END, None)
        assert [r.agent_id for r in res] == [a1, a2]
        assert res[0].agent_name == "A" and res[0].conversations == 5
        assert res[0].message_success_rate == pytest.approx(0.9, abs=1e-4)
        assert res[1].message_success_rate == 1.0
        # Top-N ordering by volume desc + limit.
        assert "ORDER BY" in db.sql(0).upper()
        assert "LIMIT 10" in db.sql(0).upper()

    async def test_by_agent_filter_collapses_to_single_entry(self):
        a1 = uuid4()
        db = FakeDB(by_agent_rows=[
            [SimpleNamespace(agent_id=a1, messages=30)],
            [SimpleNamespace(agent_id=a1, delivered=30, failed=0)],
            [SimpleNamespace(id=a1, name="A")],
            [(a1, 4)],
        ])
        res = await DashboardOverviewService(db)._by_agent(DAY, DAY_END, a1)
        assert len(res) == 1 and res[0].agent_id == a1
        # Postgres UUID literals are rendered without hyphens.
        assert a1.hex in db.sql(0)  # agent filter in the WHERE clause

    async def test_by_agent_empty_window_short_circuits(self):
        db = FakeDB(by_agent_rows=[[]])
        res = await DashboardOverviewService(db)._by_agent(DAY, DAY_END, None)
        assert res == []
        # Only the single grouped query ran.
        assert len(db.statements) == 1

    async def test_compute_composes_all_sections(self):
        canned = [
            _Scalar(2), _Scalar(1),               # agents
            _Scalar(3), _Scalar(12.0), _Scalar(1), _Scalar(40),  # conversations
            _Scalar(40), _Scalar(25), _Scalar(2), _Scalar(30),   # messages
            _Scalar(2), _Scalar(20), _Scalar(5),  # conversion
        ]
        db = FakeDB(canned)
        res = await DashboardOverviewService(db).compute(start=DAY, end=DAY_END, days=30)
        assert isinstance(res, DashboardOverviewResponse)
        assert res.range.days == 0  # explicit range -> 0-day label
        assert res.agents.total == 2
        assert res.messages.success_rate == pytest.approx(25 / 27, abs=1e-4)
        assert res.conversion.conversion_rate == 0.25
        assert res.by_agent == []  # grouped queue empty -> no agents
        assert res.cached is False
        # 2 (agents) + 4 (conversations) + 4 (messages) + 3 (conversion)
        # + 1 (by_agent grouped count; empty result short-circuits the rest)
        assert len(db.statements) == 14

    async def test_compute_invalid_window_raises(self):
        db = FakeDB([])
        with pytest.raises(ValueError):
            await DashboardOverviewService(db).compute(start=DAY_END, end=DAY, days=30)

    async def test_compute_days_clamped_to_1_365(self):
        db = FakeDB([_Scalar(0)] * 15)
        res = await DashboardOverviewService(db).compute(days=5000, now=DAY_END)
        # 5000 -> clamped to 365
        assert res.range.end - res.range.start == timedelta(days=365)


# =====================================================================
# 4. API layer (router + real service, canned aggregate results)
# =====================================================================

def _full_compute_canned(delivered: int = 25, failed: int = 2) -> List[Any]:
    """Ordered canned results for one full compute() call.

    Order: agents(2) + conversations(4) + messages(4) + conversion(3)
    + by_agent grouped (falls back to empty rows when not scripted).
    """
    return [
        _Scalar(2), _Scalar(1),
        _Scalar(3), _Scalar(12.0), _Scalar(1), _Scalar(40),
        _Scalar(40), _Scalar(delivered), _Scalar(failed), _Scalar(30),
        _Scalar(2), _Scalar(20), _Scalar(5),
    ]


def _make_app(canned: List[Any] = None) -> FastAPI:
    app = FastAPI()
    app.include_router(dr.router)
    # P6AN-16: dashboard overview now requires an authenticated principal.
    # Functional tests use a platform-wide admin (no tenant scoping) to keep
    # the legacy unscoped behavior under test.
    from app.security.analytics_access import override_analytics_auth, test_principal
    override_analytics_auth(app, test_principal(role="admin"))
    db = FakeDB(canned if canned is not None else _full_compute_canned())
    app.dependency_overrides[get_db] = lambda: db
    return app


@pytest.fixture(autouse=True)
def _reset_cache_singleton():
    cache_mod.reset_dashboard_cache()
    yield
    cache_mod.reset_dashboard_cache()


def _db_of(client: TestClient) -> FakeDB:
    return client.app.dependency_overrides[get_db]()


class TestOverviewAPI:
    def test_unified_schema_ok(self):
        client = TestClient(_make_app())
        r = client.get("/api/v1/analytics/dashboard/overview")
        assert r.status_code == 200
        body = r.json()
        assert {"range", "agents", "conversations", "messages", "conversion",
                "by_agent", "computed_at", "cached", "cache_ttl_seconds"}.issubset(
            body.keys()
        )
        assert body["cached"] is False
        assert body["cache_ttl_seconds"] == 300
        assert body["messages"]["success_rate"] == pytest.approx(25 / 27, abs=1e-4)

    def test_explicit_range_and_filters_forwarded(self):
        client = TestClient(_make_app())
        agent = uuid4()
        r = client.get(
            "/api/v1/analytics/dashboard/overview",
            params={
                "time_range_start": "2026-09-01T00:00:00Z",
                "time_range_end": "2026-09-15T00:00:00Z",
                "agent_id": str(agent),
                "channel": "wechat",
            },
        )
        assert r.status_code == 200
        assert r.json()["range"]["days"] == 0  # explicit range -> 0-day label
        db = _db_of(client)
        all_sql = " ".join(str(s.compile(compile_kwargs={"literal_binds": True}))
                           for s in db.statements)
        # channel filter must actually reach the emitted SQL.
        assert "messages.channel = 'wechat'" in all_sql
        # Postgres UUID literals are rendered without hyphens.
        assert agent.hex in all_sql
        # agent filter must scope the binding subquery.
        assert "agent_customer_binding" in all_sql

    def test_agent_filter_scopes_agent_dimension(self):
        """The "Agent 维度可按 Agent 过滤" acceptance criterion."""
        client = TestClient(_make_app())
        agent = uuid4()
        r = client.get("/api/v1/analytics/dashboard/overview",
                       params={"agent_id": str(agent), "days": 7})
        assert r.status_code == 200
        db = _db_of(client)
        all_sql = " ".join(str(s.compile(compile_kwargs={"literal_binds": True}))
                           for s in db.statements)
        assert agent.hex in all_sql

    def test_inverted_window_400(self):
        client = TestClient(_make_app())
        r = client.get(
            "/api/v1/analytics/dashboard/overview",
            params={
                "time_range_start": "2026-09-15T00:00:00Z",
                "time_range_end": "2026-09-01T00:00:00Z",
            },
        )
        assert r.status_code == 400

    def test_bad_timestamp_400(self):
        client = TestClient(_make_app())
        r = client.get("/api/v1/analytics/dashboard/overview",
                       params={"time_range_start": "not-a-date"})
        assert r.status_code == 400

    def test_url_decoded_plus_offset_parsed(self):
        """A ``+00:00`` offset in a query string URL-decodes to a space
        (``... 00:00``); the parser must recover, not 400 (real client bug)."""
        client = TestClient(_make_app())
        r = client.get(
            "/api/v1/analytics/dashboard/overview",
            # Simulate what an HTTP client sends: the + is already decoded.
            params={"time_range_start": "2026-09-01T00:00:00 00:00",
                    "time_range_end": "2026-09-15T00:00:00 00:00"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["range"]["days"] == 0  # explicit range

    def test_url_encoded_plus_offset_end_to_end(self):
        """Percent-encoded ``%2B00%3A00`` reaches the handler as ``+00:00``."""
        client = TestClient(_make_app())
        r = client.get(
            "/api/v1/analytics/dashboard/overview?time_range_start="
            "2026-09-01T00%3A00%3A00%2B00%3A00&time_range_end="
            "2026-09-15T00%3A00%3A00%2B00%3A00"
        )
        assert r.status_code == 200, r.text

    def test_days_bounds_422(self):
        client = TestClient(_make_app())
        assert client.get("/api/v1/analytics/dashboard/overview",
                          params={"days": 0}).status_code == 422
        assert client.get("/api/v1/analytics/dashboard/overview",
                          params={"days": 366}).status_code == 422

    def test_cache_hit_issues_zero_sql(self):
        client = TestClient(_make_app())
        db = _db_of(client)
        r1 = client.get("/api/v1/analytics/dashboard/overview")
        assert r1.json()["cached"] is False
        mid = len(db.statements)
        assert mid > 0
        r2 = client.get("/api/v1/analytics/dashboard/overview")
        assert r2.json()["cached"] is True
        assert len(db.statements) == mid  # cache hit -> no SQL

    def test_different_filters_have_separate_cache_entries(self):
        client = TestClient(_make_app())
        db = _db_of(client)
        client.get("/api/v1/analytics/dashboard/overview")
        client.get("/api/v1/analytics/dashboard/overview")  # hit
        stmts_mid = len(db.statements)
        client.get("/api/v1/analytics/dashboard/overview",
                   params={"channel": "douyin"})  # miss: different key
        miss_delta = len(db.statements) - stmts_mid
        assert miss_delta > 0
        client.get("/api/v1/analytics/dashboard/overview",
                   params={"channel": "douyin"})  # hit again
        assert len(db.statements) == stmts_mid + miss_delta  # no new SQL
