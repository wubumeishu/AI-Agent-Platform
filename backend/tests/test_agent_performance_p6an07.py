"""P6AN-07 Agent Performance API tests.

Layered coverage (the real grouped-SQL 对拍 runs in ``_p6an07_duipai.py``
against a scratch Postgres; those are the authoritative "SQL is correct"
checks and are opt-in / env-gated, keeping the unit suite fast + DB-free):

- **pure logic**: range-window resolution (presets + explicit bounds + unknown
  value), the leaderboard sort-key -> metric mapping (regression guard for the
  "conversations/messages silently 0" bug), and the ``_assemble`` math
  (conversion rate, satisfaction proxy, peak hour, active-hours, all-zeros).
- **service empty path**: an agent with no data yields a zeroed metric block
  (never an error) — the card's "空数据 Agent 返回 0 而非报错" criterion.
- **HTTP layer**: route registration + status semantics (200 shape, 404 for a
  missing agent, 422 for an unknown range / sort / order) via a standalone
  analytics-only app with a fake ``get_db`` override (repo convention, same as
  P6AN-01).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.agent_performance import router as agent_perf_router
from app.schemas.agent_performance import (
    AgentPerformanceLeaderboardResponse,
    AgentPerformanceMetrics,
    AgentPerformanceResponse,
    LEADERBOARD_ORDERS,
    LEADERBOARD_SORT_KEYS,
)
from app.services.agent_performance_service import (
    AgentNotFoundError,
    AgentPerformanceService,
    InvalidRangeError,
    SENTIMENT_SCORES,
    VALID_RANGES,
)


NOW = datetime(2026, 9, 15, 0, 0, 0, tzinfo=timezone.utc)


# ============================= pure logic =============================

class TestResolveWindow:
    def test_all_means_unbounded(self):
        s, u = AgentPerformanceService.resolve_window("all", None, None, now=NOW)
        assert s is None and u is None

    def test_none_range_is_all(self):
        s, u = AgentPerformanceService.resolve_window(None, None, None, now=NOW)
        assert s is None and u is None

    def test_preset_days(self):
        s, u = AgentPerformanceService.resolve_window("7d", None, None, now=NOW)
        assert u == NOW
        assert s == NOW - _days(7)

    @pytest.mark.parametrize("preset,days", [("7d", 7), ("30d", 30), ("90d", 90), ("365d", 365)])
    def test_all_presets(self, preset, days):
        s, u = AgentPerformanceService.resolve_window(preset, None, None, now=NOW)
        assert u == NOW and s == NOW - _days(days)

    def test_explicit_bounds_override_preset(self):
        hi = datetime(2026, 9, 10, tzinfo=timezone.utc)
        lo = datetime(2026, 9, 12, tzinfo=timezone.utc)
        s, u = AgentPerformanceService.resolve_window("30d", hi, lo, now=NOW)
        assert s == hi and u == lo  # explicit wins over the 30d window

    def test_explicit_since_only(self):
        hi = datetime(2026, 9, 1, tzinfo=timezone.utc)
        s, u = AgentPerformanceService.resolve_window("all", hi, None, now=NOW)
        assert s == hi and u is None

    def test_naive_bounds_normalized_to_aware_utc(self):
        naive = datetime(2026, 9, 1, 3, 4, 5)  # no tz
        s, _ = AgentPerformanceService.resolve_window("all", naive, None, now=NOW)
        assert s.tzinfo is not None and s.utcoffset() is not None

    def test_unknown_range_raises(self):
        with pytest.raises(InvalidRangeError):
            AgentPerformanceService.resolve_window("forever", None, None, now=NOW)


def _days(n: int):
    from datetime import timedelta
    return timedelta(days=n)


class TestSortValueMapping:
    """Regression guard: every public sort key must map to a real comparable
    value — the original getattr fallback silently returned 0 for the default
    ``conversations`` key, making the leaderboard a no-op."""

    def _m(self, **kw) -> AgentPerformanceMetrics:
        base = dict(agent_id=uuid4(), agent_name="a", total_customers=0,
                    active_customers=0, conversation_count=0, message_count=0,
                    lead_count=0, converted_lead_count=0, conversion_rate=None,
                    satisfaction_proxy=None, satisfaction_sample=0,
                    sentiment_breakdown={"positive": 0, "neutral": 0, "negative": 0},
                    active_hours=[0] * 24, peak_hour=None)
        base.update(kw)
        return AgentPerformanceMetrics(**base)

    def test_conversations_maps_to_conversation_count(self):
        m = self._m(conversation_count=5)
        assert AgentPerformanceService._sort_value(MagicMock(), m, "conversations") == 5

    def test_messages_maps_to_message_count(self):
        m = self._m(message_count=9)
        assert AgentPerformanceService._sort_value(MagicMock(), m, "messages") == 9

    def test_activity_is_sum(self):
        m = self._m(conversation_count=3, message_count=7)
        assert AgentPerformanceService._sort_value(MagicMock(), m, "activity") == 10

    def test_conversion_rate_null_substitutes_zero(self):
        m = self._m(conversion_rate=None)
        assert AgentPerformanceService._sort_value(MagicMock(), m, "conversion_rate") == 0.0

    def test_conversion_rate_value_preserved(self):
        m = self._m(conversion_rate=0.4)
        assert AgentPerformanceService._sort_value(MagicMock(), m, "conversion_rate") == 0.4

    def test_satisfaction_null_substitutes_zero(self):
        m = self._m(satisfaction_proxy=None)
        assert AgentPerformanceService._sort_value(MagicMock(), m, "satisfaction") == 0.0

    def test_customers_maps_to_total(self):
        m = self._m(total_customers=12)
        assert AgentPerformanceService._sort_value(MagicMock(), m, "customers") == 12

    def test_name_sort_is_casefolded(self):
        m = self._m(agent_name="Zed")
        assert AgentPerformanceService._sort_value(MagicMock(), m, "name") == "zed"

    def test_all_public_keys_resolvable(self):
        m = self._m()
        agent = MagicMock(created_at=NOW)
        for key in LEADERBOARD_SORT_KEYS:
            val = AgentPerformanceService._sort_value(agent, m, key)
            assert isinstance(val, (int, float, str, datetime)) or val is not None, key


class TestAssemble:
    """_assemble math on crafted agg/cust cells (no DB)."""

    def _agent(self):
        from app.db.models.agent import Agent
        a = Agent(id=uuid4(), name="agent-x", status="active")
        a.created_at = NOW
        a.updated_at = NOW
        return a

    def _cells(self, **agg_over):
        agg = {
            "conversation_count": 0, "message_count": 0, "lead_count": 0,
            "converted_lead_count": 0,
            "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
            "active_hours": [0] * 24,
        }
        agg.update(agg_over)
        cust = {"total_customers": 0, "active_customers": 0}
        return agg, cust

    def test_all_zeros_yields_none_rates(self):
        agg, cust = self._cells()
        m = AgentPerformanceService._assemble(self._agent(), agg, cust, None, None)
        assert m.conversion_rate is None
        assert m.satisfaction_proxy is None
        assert m.peak_hour is None
        assert m.active_hours == [0] * 24
        assert m.satisfaction_sample == 0

    def test_conversion_rate(self):
        agg, cust = self._cells(lead_count=4, converted_lead_count=1)
        m = AgentPerformanceService._assemble(self._agent(), agg, cust, None, None)
        assert m.conversion_rate == pytest.approx(0.25)

    def test_satisfaction_proxy_weighted_mean(self):
        # positive=1.0, neutral=0.5, negative=0.0  -> (2*1.0 + 2*0.5 + 1*0.0)/5 = 0.6
        agg, cust = self._cells(sentiment={"positive": 2, "neutral": 2, "negative": 1})
        m = AgentPerformanceService._assemble(self._agent(), agg, cust, None, None)
        assert m.satisfaction_sample == 5
        assert m.satisfaction_proxy == pytest.approx(0.6)
        assert m.sentiment_breakdown == {"positive": 2, "neutral": 2, "negative": 1}

    def test_peak_hour_is_argmax(self):
        hours = [0] * 24
        hours[2] = 3
        hours[14] = 3
        hours[9] = 5
        agg, cust = self._cells(message_count=11, active_hours=list(hours))
        m = AgentPerformanceService._assemble(self._agent(), agg, cust, None, None)
        assert m.peak_hour == 9
        assert m.active_hours == hours

    def test_customers_survive_from_cust_cells(self):
        agg, cust = self._cells()
        cust.update(total_customers=7, active_customers=3)
        m = AgentPerformanceService._assemble(self._agent(), agg, cust, None, None)
        assert m.total_customers == 7 and m.active_customers == 3


class TestSchemaDomains:
    def test_sort_keys_and_orders_nonempty(self):
        assert "conversations" in LEADERBOARD_SORT_KEYS
        assert "desc" in LEADERBOARD_ORDERS and "asc" in LEADERBOARD_ORDERS
        assert "all" in VALID_RANGES and "30d" in VALID_RANGES

    def test_metrics_defaults(self):
        m = AgentPerformanceMetrics(agent_id=uuid4(), agent_name="x")
        assert m.total_customers == 0 and m.conversation_count == 0
        assert m.conversion_rate is None and m.satisfaction_proxy is None
        assert m.peak_hour is None and m.active_hours == [0] * 24
        assert m.sentiment_breakdown == {"positive": 0, "neutral": 0, "negative": 0}

    def test_sentiment_scores_domain(self):
        assert set(SENTIMENT_SCORES) == {"positive", "neutral", "negative"}
        assert SENTIMENT_SCORES["positive"] > SENTIMENT_SCORES["neutral"] > SENTIMENT_SCORES["negative"]


# ============================ fake session ============================

def _agent(name="agent", status="active", created=None):
    from app.db.models.agent import Agent
    a = Agent(id=uuid4(), name=name, status=status, description=None)
    a.created_at = created or NOW
    a.updated_at = a.created_at
    a.is_deleted = False
    return a


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def scalars(self):
        rows = list(self._rows)

        class _S:
            def all(self_inner):
                return rows
        return _S()

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakePerfDB:
    """Fake AsyncSession for agent-performance service / API tests.

    - ``select(Agent)`` -> the seeded live agents (filtered to the specific
      id when the where clause pins ``Agent.id``).
    - every grouped aggregate query -> ``[]`` (the empty-data path).
    - a canned override map (query-entity -> rows) lets individual tests
      inject specific grouped rows where they want.
    """

    def __init__(self, agents: Optional[List[Any]] = None, grouped: Optional[Dict[str, list]] = None):
        self.agents = list(agents or [])
        self.grouped = grouped or {}
        self.executed: List[Any] = []
        self.commits = 0

    def _leading_entity(self, stmt) -> Optional[str]:
        try:
            ent = stmt.column_descriptions[0].get("entity")
        except Exception:
            return None
        return ent.__name__ if ent is not None else None

    def _pinned_agent_id(self, stmt) -> Optional[UUID]:
        # ``select(Agent).where(Agent.id == X, ...)`` -> the pinned id (if any).
        for crit in getattr(stmt, "_where_criteria", []) or []:
            op = getattr(crit, "operator", None)
            if op is None:
                continue
            left = getattr(crit, "left", None)
            key = getattr(left, "key", None)
            if key == "id":
                right = getattr(crit, "right", None)
                val = getattr(right, "value", right)
                if isinstance(val, UUID):
                    return val
        return None

    async def execute(self, stmt):
        name = self._leading_entity(stmt)
        self.executed.append(name)
        if name == "Agent":
            pinned = self._pinned_agent_id(stmt)
            rows = [a for a in self.agents if getattr(a, "is_deleted", False) is False]
            if pinned is not None:
                rows = [a for a in rows if a.id == pinned]
            return _FakeResult(rows)
        # grouped aggregate query -> canned rows (default empty)
        return _FakeResult(self.grouped.get(name, []))

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def refresh(self, obj):
        pass


# =========================== service empty path =========================

class TestServiceEmptyAgent:
    async def test_single_empty_agent_returns_zeroed_block(self):
        a = _agent(name="lonely")
        db = FakePerfDB(agents=[a])
        svc = AgentPerformanceService(db)
        resp = await svc.single(a.id, range_="all")
        m = resp.metrics
        assert m.total_customers == 0
        assert m.conversation_count == 0 and m.message_count == 0
        assert m.lead_count == 0 and m.converted_lead_count == 0
        assert m.conversion_rate is None
        assert m.satisfaction_proxy is None
        assert m.peak_hour is None

    async def test_single_unknown_agent_raises_404_source(self):
        db = FakePerfDB(agents=[])
        svc = AgentPerformanceService(db)
        with pytest.raises(AgentNotFoundError):
            await svc.single(uuid4(), range_="all")

    async def test_bad_range_raises(self):
        a = _agent()
        db = FakePerfDB(agents=[a])
        svc = AgentPerformanceService(db)
        with pytest.raises(InvalidRangeError):
            await svc.single(a.id, range_="yesterday")

    async def test_leaderboard_empty_agents_is_zero_total(self):
        db = FakePerfDB(agents=[])
        svc = AgentPerformanceService(db)
        lb = await svc.leaderboard(range_="all", sort_key="conversations")
        assert lb.total_agents == 0 and lb.items == []

    async def test_leaderboard_includes_zeroed_agents_and_sorts(self):
        # All metrics zeroed -> deterministic tie-break on name (asc) / created_at.
        a, b, c = _agent("zed"), _agent("alpha"), _agent("mid")
        db = FakePerfDB(agents=[a, b, c])
        svc = AgentPerformanceService(db)
        lb = await svc.leaderboard(range_="all", sort_key="conversations", order="asc",
                                   page=1, page_size=10)
        names = [m.agent_name for m in lb.items]
        assert lb.total_agents == 3
        assert names == ["alpha", "mid", "zed"]  # all tied on conversations=0 -> name asc

    async def test_leaderboard_bad_sort_is_422_source(self):
        db = FakePerfDB(agents=[_agent()])
        svc = AgentPerformanceService(db)
        with pytest.raises(InvalidRangeError):
            await svc.leaderboard(sort_key="bogus")

    async def test_leaderboard_bad_order_is_422_source(self):
        db = FakePerfDB(agents=[_agent()])
        svc = AgentPerformanceService(db)
        with pytest.raises(InvalidRangeError):
            await svc.leaderboard(order="sideways")


# ============================== HTTP layer =============================

def _perf_app():
    app = FastAPI(title="P6AN-07 agent-perf-only app")
    app.include_router(agent_perf_router)
    # P6AN-16: the analytics surface now requires an authenticated principal.
    # Functional tests use a platform-wide admin principal (account_id=None, no
    # tenant scoping) to preserve the legacy unscoped leaderboard/KPI behavior.
    from app.security.analytics_access import override_analytics_auth, test_principal
    override_analytics_auth(app, test_principal(role="admin"))
    return app


def _wire(app, db):
    from app.db.session import get_db
    app.dependency_overrides[get_db] = lambda: db
    return db


class TestApi:
    def test_routes_registered(self):
        # Use the OpenAPI schema as the ground-truth route list (FastAPI lazily
        # expands included routers, so ``app.routes`` contains _IncludedRouter
        # objects without ``.path`` — the schema is the stable source).
        paths = set(_perf_app().openapi().get("paths", {}))
        assert "/api/v1/analytics/agents/performance" in paths
        assert "/api/v1/analytics/agents/performance/metrics/{agent_id}" in paths

    def test_single_unknown_agent_404(self):
        client = TestClient(_perf_app())
        _wire(client.app, FakePerfDB(agents=[]))
        resp = client.get(f"/api/v1/analytics/agents/performance/metrics/{uuid4()}")
        assert resp.status_code == 404, resp.text

    def test_single_known_agent_200_zeroed(self):
        a = _agent(name="solo")
        client = TestClient(_perf_app())
        _wire(client.app, FakePerfDB(agents=[a]))
        resp = client.get(f"/api/v1/analytics/agents/performance/metrics/{a.id}",
                          params={"range": "all"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        m = body["metrics"]
        assert m["agent_id"] == str(a.id) and m["agent_name"] == "solo"
        assert m["conversion_rate"] is None and m["peak_hour"] is None
        assert body["window"] == {"range": "all"}

    def test_single_bad_range_422(self):
        a = _agent()
        client = TestClient(_perf_app())
        _wire(client.app, FakePerfDB(agents=[a]))
        resp = client.get(f"/api/v1/analytics/agents/performance/metrics/{a.id}",
                          params={"range": "forever"})
        assert resp.status_code == 422, resp.text

    def test_single_bad_since_422(self):
        a = _agent()
        client = TestClient(_perf_app())
        _wire(client.app, FakePerfDB(agents=[a]))
        resp = client.get(f"/api/v1/analytics/agents/performance/metrics/{a.id}",
                          params={"range": "all", "since": "not-a-date"})
        assert resp.status_code == 422, resp.text

    def test_leaderboard_200_shape(self):
        client = TestClient(_perf_app())
        _wire(client.app, FakePerfDB(agents=[]))
        resp = client.get("/api/v1/analytics/agents/performance",
                          params={"range": "30d", "sort": "conversations", "order": "desc"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_agents"] == 0 and body["items"] == []
        assert body["sort_key"] == "conversations" and body["order"] == "desc"
        assert "since" in body["window"] and "until" in body["window"]

    def test_leaderboard_bad_sort_422(self):
        client = TestClient(_perf_app())
        _wire(client.app, FakePerfDB(agents=[]))
        resp = client.get("/api/v1/analytics/agents/performance", params={"sort": "nope"})
        assert resp.status_code == 422, resp.text

    def test_leaderboard_bad_range_422(self):
        client = TestClient(_perf_app())
        _wire(client.app, FakePerfDB(agents=[]))
        resp = client.get("/api/v1/analytics/agents/performance", params={"range": "yesterday"})
        assert resp.status_code == 422, resp.text

    def test_leaderboard_bad_order_422(self):
        client = TestClient(_perf_app())
        _wire(client.app, FakePerfDB(agents=[]))
        resp = client.get("/api/v1/analytics/agents/performance", params={"order": "sideways"})
        assert resp.status_code == 422, resp.text
