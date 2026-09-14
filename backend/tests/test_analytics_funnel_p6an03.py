"""P6AN-03 Acquisition Funnel: computation, filtering, and API tests.

The funnel math (status counts -> "reached" -> rates) is pure and is
cross-checked (对撞) without a live DB; the SQL assembly and endpoint are
verified with the repo's fake-session convention (mirrors
``test_analytics_p6an01``). A live-DB 对撞 runs in
``_e2e_analytics_funnel.py`` (opt-in, real PG).

Covers:
- range preset + date parsing (incl. unknown-preset fallback, aware/naive)
- reached-math core (cumulative counts, zero denominators, unresolvable stage)
- funnel assembly (rates, empty funnel, end-to-end rate)
- service ``compute_funnel`` with a fake session (status GROUP BY routing,
  agent/platform customer subquery wiring, time window)
- API ``GET /analytics/funnel`` (200 empty, 200 with data, 422 bad range)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models.analytics import FunnelStep
from app.routers.analytics import router as analytics_router
from app.schemas.analytics import FunnelResponse, FunnelStage
from app.services import funnel_service as fs
from app.services.funnel_service import (
    _assemble,
    _FunnelCtx,
    _parse_date,
    _parse_range_days,
    _reached_from_counts,
    _Stage,
)


# ---------- pure helpers ----------

def _builtin_stages() -> List[_Stage]:
    return [_Stage(key=k, name=n, status=k) for k, n in fs.ACQUISITION_STAGES]


def _ctx(stages: Optional[List[_Stage]] = None, **kw) -> _FunnelCtx:
    kw.setdefault("stages", stages or _builtin_stages())
    kw.setdefault("funnel_code", "acquisition")
    kw.setdefault("filters", {})
    kw.setdefault("start", None)
    kw.setdefault("end", None)
    return _FunnelCtx(**kw)


class TestRangeParsing:
    def test_known_presets(self):
        assert _parse_range_days("7d") == 7
        assert _parse_range_days("30d") == 30
        assert _parse_range_days("90d") == 90
        assert _parse_range_days("365d") == 365
        assert _parse_range_days("all") is None

    def test_case_insensitive(self):
        assert _parse_range_days("7D") == 7
        assert _parse_range_days(" 30d ") == 30

    def test_default_when_omitted(self):
        assert _parse_range_days(None) == fs.RANGE_PRESETS[fs.DEFAULT_RANGE]

    def test_unknown_falls_back_to_default(self):
        assert _parse_range_days("1d") == fs.RANGE_PRESETS[fs.DEFAULT_RANGE]
        assert _parse_range_days("garbage") == fs.RANGE_PRESETS[fs.DEFAULT_RANGE]


class TestDateParsing:
    def test_none(self):
        assert _parse_date(None) is None
        assert _parse_date("") is None

    def test_date_only_naive(self):
        d = _parse_date("2026-09-01")
        assert d == datetime(2026, 9, 1) and d.tzinfo is None

    def test_zulu_to_naive_utc(self):
        d = _parse_date("2026-09-01T12:00:00Z")
        assert d == datetime(2026, 9, 1, 12, 0, 0) and d.tzinfo is None

    def test_offset_normalizes_to_naive_utc(self):
        d = _parse_date("2026-09-01T15:00:00+03:00")
        assert d == datetime(2026, 9, 1, 12, 0, 0)  # 15:00+03 == 12:00Z


class TestReachedMath:
    def test_cumulative_reached(self):
        reached = _reached_from_counts(
            _builtin_stages(), {"new": 40, "contacted": 30, "qualified": 18, "converted": 12}
        )
        assert reached["new"] == 100
        assert reached["contacted"] == 60
        assert reached["qualified"] == 30
        assert reached["converted"] == 12

    def test_empty_counts(self):
        assert _reached_from_counts(_builtin_stages(), {}) == {
            "new": 0, "contacted": 0, "qualified": 0, "converted": 0,
        }

    def test_only_top_filled(self):
        assert _reached_from_counts(_builtin_stages(), {"new": 5}) == {
            "new": 5, "contacted": 0, "qualified": 0, "converted": 0,
        }

    def test_unresolvable_stage_reports_zero(self):
        stages = [
            _Stage("a", "A", "new"),
            _Stage("b", "B", None),
            _Stage("c", "C", "converted"),
        ]
        reached = _reached_from_counts(stages, {"new": 3, "converted": 1})
        assert reached["a"] == 4
        assert reached["b"] == 0  # no resolvable status
        assert reached["c"] == 1

    def test_duplicate_status_collapses(self):
        stages = [
            _Stage("s1", "S1", "new"),
            _Stage("s2", "S2", "new"),
            _Stage("s3", "S3", "converted"),
        ]
        reached = _reached_from_counts(stages, {"new": 2, "converted": 2})
        assert reached["s1"] == 4 and reached["s2"] == 4 and reached["s3"] == 2


class TestAssemble:
    def test_rates(self):
        out = _assemble(_ctx(), {"new": 100, "contacted": 60, "qualified": 30, "converted": 12})
        by_key = {s["key"]: s for s in out["stages"]}
        assert by_key["new"]["conversion_rate"] is None
        assert by_key["new"]["overall_rate"] == 1.0
        assert by_key["contacted"]["conversion_rate"] == 0.6
        assert by_key["contacted"]["overall_rate"] == 0.6
        assert by_key["qualified"]["conversion_rate"] == 0.5
        assert by_key["converted"]["conversion_rate"] == 0.4
        assert by_key["converted"]["overall_rate"] == 0.12
        assert out["total"] == 100
        assert out["conversion_rate"] == 0.12

    def test_empty_funnel_no_crash(self):
        out = _assemble(_ctx(), {"new": 0, "contacted": 0, "qualified": 0, "converted": 0})
        assert out["total"] == 0
        assert out["conversion_rate"] is None
        for s in out["stages"]:
            assert s["count"] == 0 and s["conversion_rate"] is None and s["overall_rate"] is None

    def test_zero_top_rate_is_none_not_zero_div(self):
        out = _assemble(_ctx(), {"new": 0, "contacted": 0, "qualified": 0, "converted": 3})
        assert out["total"] == 0
        assert out["conversion_rate"] is None


class TestStageResolution:
    def _step(self, seq, name, cfg, ec):
        s = FunnelStep()
        s.seq, s.name = seq, name
        s.config, s.entry_criteria = cfg, ec
        return s

    def test_step_status_from_config(self):
        rows = [
            self._step(1, "Visit", {"status": "new"}, {}),
            self._step(2, "Talk", {}, {"status": "contacted"}),
        ]
        stages = fs._stages_from_funnel_steps(rows)
        assert [s.status for s in stages] == ["new", "contacted"]
        assert [s.key for s in stages] == ["Visit", "Talk"]

    def test_config_wins_over_entry(self):
        rows = [self._step(1, "X", {"status": "qualified"}, {"status": "new"})]
        assert fs._stages_from_funnel_steps(rows)[0].status == "qualified"


# ---------- service with a fake session ----------

class _FakeSession:
    """Routes the leading-entity select() to a canned row list.

    For the default (built-in) funnel, ``_load_stages`` never hits the DB, so
    the only query the service issues is the status GROUP BY. A custom funnel
    also issues a ``select(FunnelStep)`` — routed to ``funnel_steps``.
    """

    def __init__(self, status_counts: Optional[Dict[str, int]] = None,
                 funnel_steps: Optional[List[Any]] = None):
        self.status_counts = status_counts or {}
        self.funnel_steps = funnel_steps or []
        self.executed_group_by: List[Any] = []

    async def execute(self, stmt):
        descs = getattr(stmt, "column_descriptions", [{}])
        ent = descs[0].get("entity") if descs else None
        name = ent.__name__ if ent is not None else "unknown"
        outer = self.funnel_steps
        if name == "FunnelStep":
            class _R:
                def scalars(self):
                    class _S:
                        def all(self):
                            return list(outer)
                    return _S()
            return _R()
        # Default: the status GROUP BY count query.
        self.executed_group_by.append(stmt)
        rows = [(status, n) for status, n in self.status_counts.items()]

        class _R2:
            def all(self):
                return rows

        return _R2()


async def _run(db, **kw):
    return await fs.compute_funnel(db, **kw)


class TestComputeFunnel:
    async def test_empty_scope(self):
        db = _FakeSession(status_counts={})
        res = await _run(db, range="all")
        assert res["total"] == 0 and res["conversion_rate"] is None
        assert [s["count"] for s in res["stages"]] == [0, 0, 0, 0]

    async def test_with_counts(self):
        db = _FakeSession(status_counts={"new": 40, "contacted": 30, "qualified": 18, "converted": 12})
        res = await _run(db, range="all")
        assert res["total"] == 100
        by_key = {s["key"]: s for s in res["stages"]}
        assert by_key["new"]["count"] == 100
        assert by_key["contacted"]["count"] == 60
        assert by_key["qualified"]["count"] == 30
        assert by_key["converted"]["count"] == 12
        assert by_key["converted"]["overall_rate"] == 0.12

    async def test_agent_filter_echoed_and_group_by_issued(self):
        db = _FakeSession(status_counts={"new": 10})
        agent = uuid4()
        res = await _run(db, agent_id=agent, range="all")
        assert res["filters"]["agent_id"] == str(agent)
        assert len(db.executed_group_by) == 1

    async def test_time_window_applied(self):
        db = _FakeSession(status_counts={"new": 10})
        res = await _run(db, from_date="2026-08-01", to_date="2026-09-01")
        assert res["filters"]["from"] == "2026-08-01T00:00:00"
        assert res["filters"]["to"] == "2026-09-01T00:00:00"

    async def test_custom_funnel_uses_step_rows(self):
        steps = [
            FunnelStep(),  # placeholder; configure below
        ]
        steps[0].seq, steps[0].name, steps[0].config = 1, "Enter", {"status": "new"}
        db = _FakeSession(status_counts={"new": 7}, funnel_steps=steps)
        res = await _run(db, range="all", funnel_code="custom_x")
        # Custom funnel drives stage order from the step rows.
        assert [s["key"] for s in res["stages"]] == ["Enter"]
        assert res["funnel_code"] == "custom_x"


# ---------- API layer ----------

def _funnel_app() -> FastAPI:
    app = FastAPI(title="P6AN-03 funnel-only app")
    app.include_router(analytics_router)
    return app


def _wire(app, db):
    from app.db.session import get_db
    app.dependency_overrides[get_db] = lambda: db
    return db


class TestFunnelApi:
    def test_route_registered(self):
        paths = {getattr(r, "path", "") for r in _funnel_app().routes}
        assert "/api/v1/analytics/funnel" in paths

    def test_empty_scope_200(self):
        app = _funnel_app()
        _wire(app, _FakeSession(status_counts={}))
        res = TestClient(app).get("/api/v1/analytics/funnel", params={"range": "all"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == 0
        assert len(body["stages"]) == 4
        assert all(s["count"] == 0 for s in body["stages"])
        assert body["conversion_rate"] is None

    def test_with_counts_200(self):
        app = _funnel_app()
        _wire(app, _FakeSession(status_counts={"new": 10, "converted": 4}))
        res = TestClient(app).get("/api/v1/analytics/funnel", params={"range": "all"})
        assert res.status_code == 200
        by_key = {s["key"]: s for s in res.json()["stages"]}
        assert by_key["new"]["count"] == 14
        assert by_key["converted"]["count"] == 4

    def test_bad_range_422(self):
        app = _funnel_app()
        _wire(app, _FakeSession())
        res = TestClient(app).get("/api/v1/analytics/funnel", params={"range": "1d"})
        assert res.status_code == 422

    def test_range_default_30d(self):
        app = _funnel_app()
        _wire(app, _FakeSession())
        res = TestClient(app).get("/api/v1/analytics/funnel")
        assert res.status_code == 200
        assert res.json()["filters"]["range"] == "30d"

    def test_agent_and_platform_filters_echoed(self):
        app = _funnel_app()
        _wire(app, _FakeSession())
        a, p = uuid4(), uuid4()
        res = TestClient(app).get(
            "/api/v1/analytics/funnel",
            params={"agent_id": str(a), "platform_id": str(p), "range": "7d"},
        )
        assert res.status_code == 200
        f = res.json()["filters"]
        assert f["agent_id"] == str(a) and f["platform_id"] == str(p) and f["range"] == "7d"


class TestFunnelResponseSchema:
    def test_funnel_stage_defaults(self):
        s = FunnelStage(key="k", name="n")
        assert s.status is None and s.count == 0
        assert s.conversion_rate is None and s.overall_rate is None

    def test_funnel_response_minimal(self):
        r = FunnelResponse(funnel_code="acquisition", stages=[FunnelStage(key="a", name="A")])
        assert r.total == 0 and r.conversion_rate is None and r.filters == {}
