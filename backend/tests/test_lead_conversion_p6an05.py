"""P6AN-05 Lead Conversion API: service math + API behavior tests.

Repo test convention (cf. ``test_analytics_p6an01``): the metric math is a
pure function so it is tested directly; the HTTP layer is exercised with a
standalone analytics app whose ``get_db`` dependency is overridden by a
canned-row fake DB (the lead-conversion queries are join/aggregation SQL the
repo's per-entity FakeDB cannot fake, so the fake here returns pre-baked
result rows per query, in execution order).

Real-Postgres SQL cross-check ("对拍 SQL") lives in
``tests/_e2e_lead_conversion_p6an05.py`` (opt-in, real PG).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.analytics import router as analytics_router
from app.schemas.lead_conversion import LeadConversionResponse
from app.services.lead_conversion_service import (
    CLOSED_STAGE_CODE,
    CONVERSATION_SOURCE,
    CONVERTED_STATUS,
    DIRECT_CHANNEL,
    FUNNEL_ORDER,
    LeadConversionError,
    LeadConversionService,
    UNASSIGNED_AGENT,
    _GroupStatusCounts,
    _funnel_rank,
    _rates,
    _stage_reached,
    compute_metrics,
)

NOW = datetime(2026, 9, 1, 0, 0, 0)


def _g(key: str, status_counts: Dict[str, int]) -> _GroupStatusCounts:
    return _GroupStatusCounts(key=key, label=key, status_counts=status_counts)


# ---------- pure metric math ----------

class TestFunnelMath:
    def test_fully_advanced_cohort(self):
        m = compute_metrics([_g("t", {"converted": 4})])
        assert m["total_leads"] == 4
        assert m["stage_reached_counts"] == {"new": 4, "contacted": 4, "qualified": 4, "converted": 4}
        assert m["conversion_rates"] == {
            "new_to_contacted": 1.0,
            "contacted_to_qualified": 1.0,
            "qualified_to_converted": 1.0,
            "new_to_converted": 1.0,
        }

    def test_mixed_cohort_rates(self):
        m = compute_metrics([_g("t", {"new": 10, "contacted": 5, "qualified": 2, "converted": 1})])
        assert m["stage_reached_counts"] == {"new": 18, "contacted": 8, "qualified": 3, "converted": 1}
        assert m["conversion_rates"]["new_to_contacted"] == pytest.approx(8 / 18)
        assert m["conversion_rates"]["contacted_to_qualified"] == pytest.approx(3 / 8)
        assert m["conversion_rates"]["qualified_to_converted"] == pytest.approx(1 / 3)
        assert m["conversion_rates"]["new_to_converted"] == pytest.approx(1 / 18)

    def test_unknown_status_ranks_before_new(self):
        # Legacy/unknown statuses never contribute to stage-reached counts
        # but are still counted as leads (they sit "before" the funnel).
        m = compute_metrics([_g("t", {"archived": 3, "new": 2})])
        assert m["total_leads"] == 5
        assert m["stage_reached_counts"]["new"] == 2
        assert m["stage_reached_counts"]["converted"] == 0
        assert m["conversion_rates"]["new_to_converted"] == 0.0

    def test_empty_cohort_returns_null_rates_and_cycle(self):
        m = compute_metrics([_g("t", {})])
        assert m["total_leads"] == 0
        for v in m["conversion_rates"].values():
            assert v is None
        assert m["avg_conversion_cycle_days"] is None
        assert m["stage_reached_counts"] == {s: 0 for s in FUNNEL_ORDER}

    def test_no_groups_same_as_empty(self):
        m = compute_metrics([])
        assert m["total_leads"] == 0 and m["avg_conversion_cycle_days"] is None

    def test_cycle_average(self):
        m = compute_metrics([_g("t", {"converted": 2})], [1.0, 3.0])
        assert m["avg_conversion_cycle_days"] == pytest.approx(2.0)

    def test_stage_reached_monotonic_back_transition(self):
        # A lead back at 'contacted' after qualifying reached every stage up
        # to 'contacted' (rank-based); 'qualified' is not reached by it.
        s = _stage_reached({"contacted": 1, "converted": 1})
        assert s == {"new": 2, "contacted": 2, "qualified": 1, "converted": 1}

    def test_rates_zero_denominator_is_none(self):
        assert _rates({"new": 0, "contacted": 0, "qualified": 0, "converted": 0}) == {
            "new_to_contacted": None,
            "contacted_to_qualified": None,
            "qualified_to_converted": None,
            "new_to_converted": None,
        }

    def test_funnel_rank_unknown(self):
        assert _funnel_rank("new") == 0 and _funnel_rank("converted") == 3
        assert _funnel_rank("definitely-not-a-status") == -1


class TestServiceValidation:
    @pytest.mark.asyncio
    async def test_invalid_group_by_raises(self):
        svc = LeadConversionService(MagicMock())
        with pytest.raises(LeadConversionError):
            await svc.compute(group_by="customer")

    def test_constants_locked(self):
        assert FUNNEL_ORDER == ("new", "contacted", "qualified", "converted")
        assert CONVERTED_STATUS == "converted"
        assert CLOSED_STAGE_CODE == "成交"
        assert DIRECT_CHANNEL == "direct"
        assert UNASSIGNED_AGENT == "unassigned"
        assert CONVERSATION_SOURCE == "conversation"


# ---------- fake DB helpers (execution-order result routing) ----------

class _Row:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _AllRows:
    def __init__(self, rows: List[_Row]):
        self._rows = rows

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _ResultsDB:
    """Returns pre-baked result rows, in the order the service executes queries."""

    def __init__(self, result_lists: List[List[_Row]]):
        self._result_lists = result_lists
        self.executed: List[Any] = []

    async def execute(self, stmt):
        self.executed.append(stmt)
        rows = self._result_lists.pop(0) if self._result_lists else []
        r = _AllRows(rows)
        return MagicMock(all=r.all, scalar_one_or_none=r.scalar_one_or_none)


def _lead_cycle_rows(start: datetime = NOW, cycles=None, lead_ids=None):
    """Build canned rows for the conversion-cycle query."""
    cycles = cycles or {}
    out = []
    for lid, days in cycles.items():
        created = start
        updated = created + timedelta(days=days)
        out.append(_Row(id=lid, created_at=created, updated_at=updated, stage_ts=None))
    return out


def _conversion_app(db) -> FastAPI:
    app = FastAPI(title="P6AN-05 lead-conversion-only app")
    app.include_router(analytics_router)
    # P6AN-16: the analytics surface now requires an authenticated principal.
    # Functional tests use a platform-wide admin principal (no tenant scoping)
    # to preserve the legacy unscoped behavior under test.
    from app.security.analytics_access import override_analytics_auth, test_principal
    override_analytics_auth(app, test_principal(role="admin"))
    from app.db.session import get_db
    app.dependency_overrides[get_db] = lambda: db
    return app


# ---------- HTTP layer ----------

class TestLeadConversionApi:
    def test_route_registered(self):
        paths = {r.path for r in analytics_router.routes}
        assert "/api/v1/analytics/leads/conversion" in paths

    def test_overall_200_shape(self):
        db = _ResultsDB([
            [_Row(status="new", n=6), _Row(status="converted", n=2)],
            [],
        ])
        client = TestClient(_conversion_app(db))
        resp = client.get("/api/v1/analytics/leads/conversion")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["filters"]["group_by"] == "overall"
        assert body["filters"]["window_basis"] == "lead.created_at"
        t = body["totals"]
        assert t["total_leads"] == 8
        assert t["status_counts"] == {"new": 6, "converted": 2}
        # 'new' leads reached the 'new' stage only; converted reached all.
        assert t["stage_reached_counts"] == {"new": 8, "contacted": 2, "qualified": 2, "converted": 2}
        assert t["avg_conversion_cycle_days"] is None
        assert body["groups"] == []
        # schema validation round-trip
        LeadConversionResponse(**body)

    def test_agent_filter_passthrough(self):
        agent = uuid4()
        db = _ResultsDB([[], []])
        client = TestClient(_conversion_app(db))
        resp = client.get(
            "/api/v1/analytics/leads/conversion",
            params={"agent_id": str(agent)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["filters"]["agent_id"] == str(agent)
        assert resp.json()["totals"]["total_leads"] == 0

    def test_invalid_group_by_422(self):
        db = _ResultsDB([[], []])
        client = TestClient(_conversion_app(db))
        resp = client.get(
            "/api/v1/analytics/leads/conversion",
            params={"group_by": "customer"},
        )
        # pattern rejection happens at FastAPI query validation
        assert resp.status_code == 422, resp.text

    def test_channel_filter_passthrough(self):
        db = _ResultsDB([[], []])
        client = TestClient(_conversion_app(db))
        resp = client.get(
            "/api/v1/analytics/leads/conversion",
            params={"channel": "wechat", "from_date": "2026-08-01T00:00:00"},
        )
        assert resp.status_code == 200, resp.text
        f = resp.json()["filters"]
        assert f["channel"] == "wechat"
        assert f["from_date"] is not None

    def test_cycle_days_serialization(self):
        lid = uuid4()
        db = _ResultsDB([
            [_Row(status="converted", n=1)],
            _lead_cycle_rows(start=NOW, cycles={lid: 5}),
        ])
        client = TestClient(_conversion_app(db))
        resp = client.get("/api/v1/analytics/leads/conversion")
        assert resp.status_code == 200, resp.text
        assert resp.json()["totals"]["avg_conversion_cycle_days"] == pytest.approx(5.0)


# ---------- service-level: grouping + filter plumbing (canned rows) ----------

class TestServiceGrouping:
    @pytest.mark.asyncio
    async def test_agent_grouping_rows(self):
        db = _ResultsDB([
            [_Row(status="new", n=2), _Row(status="converted", n=1)],
            [
                _Row(group_key="销售A", status="new", n=1),
                _Row(group_key="销售A", status="converted", n=1),
                _Row(group_key=None, status="new", n=1),
            ],
            [],
        ])
        svc = LeadConversionService(db)
        out = await svc.compute(group_by="agent")
        keys = [g["key"] for g in out["groups"]]
        assert "销售A" in keys and UNASSIGNED_AGENT in keys
        g = {x["key"]: x for x in out["groups"]}
        assert g["销售A"]["metrics"]["total_leads"] == 2
        assert g[UNASSIGNED_AGENT]["metrics"]["total_leads"] == 1
        assert out["totals"]["total_leads"] == 3  # distinct overall

    @pytest.mark.asyncio
    async def test_channel_grouping_rows(self):
        db = _ResultsDB([
            [_Row(status="new", n=1), _Row(status="converted", n=1)],
            [
                _Row(group_key="web", status="new", n=1),
                _Row(group_key="wechat", status="converted", n=1),
            ],
            [],
        ])
        svc = LeadConversionService(db)
        out = await svc.compute(group_by="channel")
        keys = [g["key"] for g in out["groups"]]
        # channel keys are lower-cased by the SQL; coalesce -> "direct" for NULL
        assert set(keys) == {"web", "wechat"}

    @pytest.mark.asyncio
    async def test_agent_filter_excludes_other_agents(self):
        """With an agent_id filter, the status-count + cycle queries carry the
        binding join and the agent_id equality."""
        agent_id = uuid4()
        db = _ResultsDB([
            [_Row(status="converted", n=2)],
            [],
        ])
        svc = LeadConversionService(db)
        await svc.compute(agent_id=agent_id)
        # Two executions: overall status counts + cycle sample (no per-group
        # query since group_by=overall).
        assert len(db.executed) == 2
        for stmt in db.executed:
            sql = str(stmt)
            assert "agent_customer_binding" in sql, sql
            assert "agent_id" in sql, sql

    @pytest.mark.asyncio
    async def test_channel_filter_applied(self):
        db = _ResultsDB([[], []])
        svc = LeadConversionService(db)
        await svc.compute(channel="douyin")
        joined = " ".join(str(s) for s in db.executed)
        assert "conversation" in joined
        assert "channel" in joined

    @pytest.mark.asyncio
    async def test_time_window_applied(self):
        db = _ResultsDB([[], []])
        svc = LeadConversionService(db)
        await svc.compute(from_date=NOW, to_date=NOW + timedelta(days=10))
        joined = " ".join(str(s) for s in db.executed)
        assert "created_at >=" in joined and "created_at <=" in joined
