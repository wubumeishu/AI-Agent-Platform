"""P6AN-08 Strategy Experiment: variant traffic-allocation rule + results
summary / variant comparison.

Extends P6AN-01's analytics surface (same fake-session repo convention as
``test_analytics_p6an01.py``):

- ``_validate_variants`` traffic-allocation rule: once any variant carries a
  ``share``/``traffic``/``traffic_share`` value, the provided shares must
  sum to 1.0 (±1e-6); out-of-range / partial / over-allocated / malformed
  shares are rejected (AnalyticsConflictError → HTTP 409). Legacy
  free-form variant lists (no shares) pass through untouched.
- ``GET /experiments/{id}/results/summary`` — per-metric variant
  comparison (latest snapshot per variant, derived lift vs the baseline
  variant, plain-language significance note). Basic comparison only; no
  statistical-inference library (out of scope for this card).

Note on the fake harness: P6AN-01's ``FakeDB`` intentionally does NOT apply
SQL ``WHERE`` criteria — it returns every row of the routed entity. These
tests therefore load at most one experiment per scenario so the unfiltered
read is a no-op; the summary's "latest per (variant, metric)" selection is
what the tests actually exercise.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models.analytics import Experiment, ExperimentResult
from app.routers.analytics import router as analytics_router
from app.schemas.analytics import (
    ExperimentCreate,
    ExperimentUpdate,
)
from app.services.analytics_service import (
    AnalyticsConflictError,
    AnalyticsEntityNotFoundError,
    ExperimentService,
    _validate_variants,
)

# Reuse P6AN-01's fake-session harness (same repo convention).
from tests.test_analytics_p6an01 import (
    _fake_db,
    _row,
    _exp_row,
    _exp_res_class,
    _wire_db,
)


def _now_ts() -> datetime:
    return datetime.now(timezone.utc)


def _res_row(**kw) -> ExperimentResult:
    """ExperimentResult fake row with result-column defaults the P6AN-01
    ``_row()`` helper does not set (metric_value / computed_at)."""
    kw.setdefault("variant_label", "control")
    kw.setdefault("metric_code", "m.cnt")
    kw.setdefault("sample_size", 0)
    kw.setdefault("metric_value", Decimal(0))
    kw.setdefault("computed_at", _now_ts())
    kw.setdefault("experiment_id", kw.pop("exp_id", uuid4()))
    return _row(_exp_res_class(), **kw)


# ---------- traffic-allocation rule (unit) ----------

class TestValidateVariants:
    def test_empty_and_single_pass_through(self):
        assert _validate_variants([]) == []
        assert _validate_variants([{"label": "control"}]) == [{"label": "control"}]

    def test_no_shares_legacy_free_form_pass_through(self):
        variants = [{"label": "a", "config": {"x": 1}}, "plain-string", {"config": {}}]
        assert _validate_variants(variants) == variants

    def test_full_allocation_accepted(self):
        variants = [
            {"label": "control", "share": 0.5, "config": {}},
            {"label": "treatment", "share": 0.5, "config": {}},
        ]
        out = _validate_variants(variants)
        assert out[0]["share"] == 0.5 and out[1]["share"] == 0.5

    def test_share_alias_and_string_coercion(self):
        out = _validate_variants([
            {"label": "a", "traffic": "0.3"},
            {"label": "b", "traffic_share": 0.7},
        ])
        assert out[0]["share"] == 0.3 and out[1]["share"] == 0.7

    def test_partial_allocation_rejected(self):
        with pytest.raises(AnalyticsConflictError):
            _validate_variants([
                {"label": "a", "share": 0.5},
                {"label": "b", "share": 0.2},
            ])

    def test_over_allocation_rejected(self):
        with pytest.raises(AnalyticsConflictError):
            _validate_variants([
                {"label": "a", "share": 0.6},
                {"label": "b", "share": 0.6},
            ])

    def test_out_of_range_share_rejected(self):
        with pytest.raises(AnalyticsConflictError):
            _validate_variants([
                {"label": "a", "share": 1.5},
                {"label": "b", "share": 0.5},
            ])
        with pytest.raises(AnalyticsConflictError):
            _validate_variants([
                {"label": "a", "share": -0.1},
                {"label": "b", "share": 1.1},
            ])

    def test_malformed_share_rejected(self):
        with pytest.raises(AnalyticsConflictError):
            _validate_variants([
                {"label": "a", "share": "lots"},
                {"label": "b", "share": 0.5},
            ])

    def test_zero_share_ok_when_sum_is_one(self):
        out = _validate_variants([
            {"label": "a", "share": 0.0},
            {"label": "b", "share": 1.0},
        ])
        assert out[0]["share"] == 0.0 and out[1]["share"] == 1.0


# ---------- service: create/update enforce allocation ----------

class TestExperimentServiceVariants:
    async def test_create_rejects_partial_allocation(self):
        db = _fake_db({})
        svc = ExperimentService(db)
        with pytest.raises(AnalyticsConflictError):
            await svc.create(ExperimentCreate(
                code="exp-a", name="E",
                variants=[{"label": "a", "share": 0.4}, {"label": "b", "share": 0.4}],
            ))
        assert db.commits == 0  # nothing persisted on rejection

    async def test_create_accepts_valid_allocation(self):
        db = _fake_db({})
        svc = ExperimentService(db)
        e = await svc.create(ExperimentCreate(
            code="exp-b", name="E",
            variants=[{"label": "control", "share": 0.5},
                      {"label": "treatment", "share": 0.5}],
        ))
        assert e.variants[0]["share"] == 0.5

    async def test_update_rejects_bad_allocation(self):
        e = _exp_row("draft")
        db = _fake_db({"Experiment": [e]})
        svc = ExperimentService(db)
        with pytest.raises(AnalyticsConflictError):
            await svc.update(e, ExperimentUpdate(
                variants=[{"label": "a", "share": 0.5},
                          {"label": "b", "share": 0.3}]))
        assert e.variants == [{"label": "control"}]  # untouched on rejection

    async def test_update_accepts_valid_allocation(self):
        e = _exp_row("draft")
        db = _fake_db({"Experiment": [e]})
        svc = ExperimentService(db)
        await svc.update(e, ExperimentUpdate(
            variants=[{"label": "control", "share": 0.7},
                      {"label": "treatment", "share": 0.3}]))
        assert e.variants[0]["share"] == 0.7


# ---------- service: summarize_results ----------

class TestSummarizeResults:
    async def test_summary_computes_lift_and_note(self):
        e = _exp_row("running", primary_metric_code="conv",
                     variants=[{"label": "control", "share": 0.5},
                                {"label": "treatment", "share": 0.5}])
        base = _res_row(exp_id=e.id, variant_label="control", metric_code="conv",
                        metric_value=Decimal(20), p_value=Decimal("0.50"))
        treat = _res_row(exp_id=e.id, variant_label="treatment", metric_code="conv",
                         metric_value=Decimal(30), sample_size=500,
                         p_value=Decimal("0.01"))
        db = _fake_db({"Experiment": [e], "ExperimentResult": [base, treat]})
        svc = ExperimentService(db)
        s = await svc.summarize_results(e.id)
        assert s.baseline_variant == "control"
        m = s.metrics[0]
        assert m.metric_code == "conv" and m.is_primary is True
        by_var = {v.variant_label: v for v in m.variants}
        assert by_var["control"].lift_vs_baseline_percent is None
        # lift = (30 - 20) / 20 * 100 = 50.0
        assert Decimal(by_var["treatment"].lift_vs_baseline_percent) == Decimal("50")
        assert by_var["treatment"].is_significant is True  # p < 0.05
        assert "significant" in m.note

    async def test_summary_missing_experiment_404(self):
        db = _fake_db({"Experiment": []})
        svc = ExperimentService(db)
        with pytest.raises(AnalyticsEntityNotFoundError):
            await svc.summarize_results(uuid4())

    async def test_summary_no_results_notes_it(self):
        e = _exp_row("running")
        db = _fake_db({"Experiment": [e]})
        svc = ExperimentService(db)
        s = await svc.summarize_results(e.id)
        assert s.metrics == []
        assert any("No result snapshots" in n for n in s.notes)

    async def test_summary_latest_snapshot_wins(self):
        e = _exp_row("running", variants=[{"label": "control", "share": 0.5},
                                           {"label": "treatment", "share": 0.5}])
        base = _res_row(exp_id=e.id, variant_label="control", metric_code="m",
                        metric_value=Decimal(10), computed_at=_now_ts())
        old = _res_row(exp_id=e.id, variant_label="treatment", metric_code="m",
                       metric_value=Decimal(10), computed_at=_now_ts())
        new = _res_row(exp_id=e.id, variant_label="treatment", metric_code="m",
                       metric_value=Decimal(99), computed_at=_now_ts())
        db = _fake_db({"Experiment": [e], "ExperimentResult": [base, old, new]})
        svc = ExperimentService(db)
        s = await svc.summarize_results(e.id)
        treat = [v for v in s.metrics[0].variants if v.variant_label == "treatment"][0]
        # old and new share computed_at; `new` is added last so the >= keeps it.
        assert Decimal(treat.metric_value) == Decimal(99)


# ---------- API layer (standalone analytics app, fake session) ----------

def _analytics_app() -> FastAPI:
    app = FastAPI(title="P6AN-08 analytics-only app")
    app.include_router(analytics_router)
    return app


class TestApiSummary:
    def test_summary_200(self):
        app = _analytics_app()
        e = _exp_row("running", variants=[{"label": "control", "share": 0.5},
                                           {"label": "treatment", "share": 0.5}])
        _wire_db(app, _fake_db({"Experiment": [e]}))
        client = TestClient(app)
        resp = client.get(f"/api/v1/analytics/experiments/{e.id}/results/summary")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["experiment_id"] == str(e.id)
        assert body["baseline_variant"] == "control"
        assert body["metrics"] == []

    def test_summary_missing_experiment_404(self):
        app = _analytics_app()
        _wire_db(app, _fake_db({"Experiment": []}))
        client = TestClient(app)
        resp = client.get(f"/api/v1/analytics/experiments/{uuid4()}/results/summary")
        assert resp.status_code == 404

    def test_create_experiment_partial_allocation_409(self):
        app = _analytics_app()
        _wire_db(app, _fake_db({}))
        client = TestClient(app)
        resp = client.post("/api/v1/analytics/experiments", json={
            "code": "exp-c", "name": "E",
            "variants": [{"label": "a", "share": 0.2},
                         {"label": "b", "share": 0.3}],
        })
        assert resp.status_code == 409, resp.text
        assert "sum to" in resp.json()["detail"]

    def test_create_experiment_valid_allocation_201(self):
        app = _analytics_app()
        _wire_db(app, _fake_db({}))
        client = TestClient(app)
        resp = client.post("/api/v1/analytics/experiments", json={
            "code": "exp-d", "name": "E",
            "variants": [{"label": "a", "share": 0.5},
                         {"label": "b", "share": 0.5}],
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["variants"][0]["share"] == 0.5

    def test_routes_registered_includes_summary(self):
        # Version-stable OpenAPI path check (full prefixed paths).
        paths = set(_analytics_app().openapi()["paths"].keys())
        assert "/api/v1/analytics/experiments/{experiment_id}/results/summary" in paths
