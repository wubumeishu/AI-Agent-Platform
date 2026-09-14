"""P6AN-01 Analytics foundation: schema, service, and API tests.

The repo's test convention keeps service tests independent of a live
Postgres by faking the session (per-entity result routing), mirroring
``test_scheduler_consumer`` / ``test_memory_api``. A live-DB migration
check runs in ``_e2e_analytics_migration.py`` (opt-in, real PG).

Covers:
- model constants + value domains
- schema validation (domain patterns, required fields)
- service CRUD behaviour with a fake session (create/get/list/update/delete)
- experiment state machine (legal + illegal transitions, terminate reason)
- uniqueness conflict handling (IntegrityError -> AnalyticsConflictError)
- API HTTP status codes (404/409/201/204/200) via a standalone analytics app
  (no app.main: the security task's uncommitted main.py work is a known
  transient hotspot — see the P6AN-01 board comment)
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models.analytics import (
    DashboardWidget,
    Experiment,
    EXPERIMENT_STATUSES,
    EXPERIMENT_TERMINAL_STATUSES,
    EXPERIMENT_TRANSITIONS,
    FunnelStep,
    MetricDefinition,
    WIDGET_TYPES,
)
from app.routers.analytics import router as analytics_router
from app.schemas.analytics import (
    DashboardWidgetCreate,
    DashboardWidgetUpdate,
    ExperimentCreate,
    ExperimentResultCreate,
    ExperimentStatusUpdate,
    ExperimentUpdate,
    FunnelStepCreate,
    FunnelStepUpdate,
    MetricDefinitionCreate,
    MetricDefinitionUpdate,
)
from app.services.analytics_service import (
    AnalyticsConflictError,
    AnalyticsEntityNotFoundError,
    DashboardWidgetService,
    ExperimentService,
    ExperimentStatusError,
    FunnelStepService,
    MetricDefinitionService,
)


# ---------- fake DB (per-entity result routing, repo convention) ----------

def _entity_name(stmt) -> str:
    """Extract the routed entity class name from a select() statement."""
    desc = stmt.column_descriptions[0]
    ent = desc.get("entity")
    return ent.__name__ if ent is not None else "unknown"


def _where_matches(criteria, row) -> bool:
    """Evaluate simple ``column == value`` / ``column != value`` criteria against a fake row.

    Complex criteria (IN, LIKE, joins) pass through unfiltered — tests only
    use equality criteria, which is what the services generate.
    """
    import operator as _op

    for crit in criteria:
        op = getattr(crit, "operator", None)
        if op not in (_op.eq, _op.ne):
            continue
        left = crit.left
        colkey = getattr(left, "key", None)
        if colkey is None:
            continue
        # Right side may be a BindParameter (.value) or a False_/True_ single
        # (which is a bool subclass). Resolve to a plain Python value.
        right = crit.right
        expected = getattr(right, "value", right)
        actual = getattr(row, colkey, None)
        if op is _op.ne:
            if actual == expected:
                return False
        else:  # eq
            if actual != expected:
                return False
    return True


class FakeDB:
    """Per-entity rows + commit/rollback/refresh + optional IntegrityError injection."""

    def __init__(self, entities: Optional[Dict[str, List]] = None,
                 raise_integrity_on_commit: Optional[type] = None,
                 on_commit: Optional[Any] = None):
        self.entities = entities if entities is not None else {}
        self.raise_integrity = raise_integrity_on_commit
        self.on_commit = on_commit
        self.commits = 0
        self.added: List[Any] = []
        self.deleted: List[Any] = []

    def _rows_for(self, stmt):
        name = _entity_name(stmt)
        rows = self.entities.get(name, [])
        criteria = [c for c in getattr(stmt, "_where_criteria", [])]
        if criteria:
            rows = [r for r in rows if _where_matches(criteria, r)]
        return rows

    def _result(self, stmt):
        name = _entity_name(stmt)
        matched = self._rows_for(stmt)
        live = [r for r in matched if getattr(r, "is_deleted", False) is False]

        class Result:
            def scalar_one_or_none(self):
                return live[0] if live else None

            def scalars(self):
                rows = list(live)

                class S:
                    def all(self):
                        return rows

                return S()

        return Result()

    async def execute(self, stmt):
        return self._result(stmt)

    def add(self, obj):
        self.added.append(obj)
        # register into the entity row list so subsequent get/list see it
        key = type(obj).__name__
        self.entities.setdefault(key, []).append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)
        key = type(obj).__name__
        rows = self.entities.get(key, [])
        if obj in rows:
            rows.remove(obj)

    async def commit(self):
        if self.raise_integrity:
            raise self.raise_integrity()
        self.commits += 1
        if self.on_commit:
            self.on_commit()

    async def rollback(self):
        pass

    async def refresh(self, obj):
        # fill server-side-ish defaults the ORM would set on insert
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        now = datetime.now(timezone.utc)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now


def _fake_db(rows: Dict[str, List], **kw) -> FakeDB:
    return FakeDB(rows, **kw)


def _row(cls, **kw):
    o = cls()
    o.id = kw.pop("id", uuid4())
    o.created_at = kw.pop("created_at", datetime.now(timezone.utc))
    o.updated_at = kw.pop("updated_at", o.created_at)
    o.is_deleted = kw.pop("is_deleted", False)
    for k, v in kw.items():
        setattr(o, k, v)
    return o


# ---------- constants ----------

class TestConstants:
    def test_experiment_state_machine_covers_all_statuses(self):
        for s in EXPERIMENT_STATUSES:
            assert s in EXPERIMENT_TRANSITIONS, s

    def test_terminal_states_have_no_outgoing_transitions(self):
        for s in EXPERIMENT_TERMINAL_STATUSES:
            assert EXPERIMENT_TRANSITIONS[s] == frozenset(), s

    def test_widget_types_non_empty(self):
        assert "kpi" in WIDGET_TYPES and "funnel" in WIDGET_TYPES


# ---------- schemas ----------

class TestSchemas:
    def test_widget_create_defaults(self):
        w = DashboardWidgetCreate(name="W")
        assert w.widget_type == "kpi"
        assert w.enabled is True
        assert w.config == {}
        assert w.refresh_interval_seconds == 300

    def test_widget_rejects_bad_type(self):
        with pytest.raises(Exception):
            DashboardWidgetCreate(name="W", widget_type="hologram")

    def test_metric_code_pattern(self):
        MetricDefinitionCreate(code="conversation.sent_count", name="m")
        with pytest.raises(Exception):
            MetricDefinitionCreate(code="BAD CODE!", name="m")

    def test_experiment_result_value_types(self):
        r = ExperimentResultCreate(
            experiment_id=uuid4(), variant_label="control", metric_code="m.cnt",
            metric_value=Decimal("12.5"),
        )
        assert r.metric_value == Decimal("12.5")
        assert r.sample_size == 0
        assert r.p_value is None

    def test_experiment_result_p_value_bounds(self):
        with pytest.raises(Exception):
            ExperimentResultCreate(
                experiment_id=uuid4(), variant_label="v", metric_code="m",
                metric_value=Decimal(1), p_value=Decimal("1.5"),
            )

    def test_status_update_rejects_unknown(self):
        with pytest.raises(Exception):
            ExperimentStatusUpdate(status="aborted")


# ---------- service: widget ----------

def _widget_row(**kw) -> DashboardWidget:
    kw.setdefault("name", "W1")
    kw.setdefault("widget_type", "kpi")
    kw.setdefault("config", {})
    kw.setdefault("position", 0)
    kw.setdefault("refresh_interval_seconds", 300)
    kw.setdefault("enabled", True)
    return _row(DashboardWidget, **kw)


class TestWidgetService:
    async def test_create_registers_and_commits(self):
        db = _fake_db({})
        svc = DashboardWidgetService(db)
        w = await svc.create(DashboardWidgetCreate(name="Revenue KPI", widget_type="kpi"))
        assert db.commits == 1
        assert w.name == "Revenue KPI"
        assert db.added and db.added[0] is w

    async def test_get_returns_live_row(self):
        w = _widget_row()
        db = _fake_db({"DashboardWidget": [w]})
        svc = DashboardWidgetService(db)
        got = await svc.get(w.id)
        assert got is w

    async def test_get_excludes_soft_deleted(self):
        w = _widget_row(is_deleted=True)
        db = _fake_db({"DashboardWidget": [w]})
        svc = DashboardWidgetService(db)
        assert await svc.get(w.id) is None

    async def test_list_returns_items_and_total(self):
        rows = [_widget_row(name="a"), _widget_row(name="b")]
        db = _fake_db({"DashboardWidget": rows})
        svc = DashboardWidgetService(db)
        items, total = await svc.list(page=1, page_size=20)
        assert total == 2 and len(items) == 2

    async def test_update_patches_only_given_fields(self):
        w = _widget_row(name="old")
        db = _fake_db({"DashboardWidget": [w]})
        svc = DashboardWidgetService(db)
        await svc.update(w, DashboardWidgetUpdate(name="new"))
        assert w.name == "new"
        assert w.position == 0  # untouched

    async def test_delete_soft_deletes(self):
        w = _widget_row()
        db = _fake_db({"DashboardWidget": [w]})
        svc = DashboardWidgetService(db)
        assert await svc.delete(w.id) is True
        assert w.is_deleted is True
        assert await svc.delete(w.id) is False  # gone afterwards


# ---------- service: funnel step ----------

def _integrity_err() -> "BaseException":
    """Factory called by FakeDB.commit() to raise a unique-violation IntegrityError."""
    from sqlalchemy.exc import IntegrityError
    return IntegrityError("stmt", {}, Exception("unique violation"))


def _step_row(**kw) -> FunnelStep:
    kw.setdefault("funnel_code", "lead")
    kw.setdefault("name", "s1")
    kw.setdefault("seq", 1)
    kw.setdefault("entry_criteria", {})
    return _row(FunnelStep, **kw)


class TestFunnelStepService:
    async def test_create_commits(self):
        db = _fake_db({})
        svc = FunnelStepService(db)
        s = await svc.create(FunnelStepCreate(funnel_code="lead", name="visit", seq=1))
        assert s.seq == 1 and s.funnel_code == "lead"

    async def test_create_conflict(self):
        db = _fake_db({}, raise_integrity_on_commit=_integrity_err)
        svc = FunnelStepService(db)
        with pytest.raises(AnalyticsConflictError):
            await svc.create(FunnelStepCreate(funnel_code="lead", name="visit", seq=1))

    async def test_update_conflict(self):
        s = _step_row()
        db = _fake_db({"FunnelStep": [s]}, raise_integrity_on_commit=_integrity_err)
        svc = FunnelStepService(db)
        with pytest.raises(AnalyticsConflictError):
            await svc.update(s, FunnelStepUpdate(seq=99))


# ---------- service: metric ----------

def _metric_row(**kw) -> MetricDefinition:
    kw.setdefault("code", "m.cnt")
    kw.setdefault("name", "M")
    kw.setdefault("category", "custom")
    kw.setdefault("value_type", "numeric")
    kw.setdefault("formula", {})
    kw.setdefault("window_days", 30)
    kw.setdefault("enabled", True)
    return _row(MetricDefinition, **kw)


class TestMetricService:
    async def test_create_and_get_by_code(self):
        m = _metric_row()
        db = _fake_db({"MetricDefinition": [m]})
        svc = MetricDefinitionService(db)
        got = await svc.get_by_code("m.cnt")
        assert got is m
        assert await svc.get_by_code("nope") is None

    async def test_create_conflict(self):
        db = _fake_db({}, raise_integrity_on_commit=_integrity_err)
        svc = MetricDefinitionService(db)
        with pytest.raises(AnalyticsConflictError):
            await svc.create(MetricDefinitionCreate(code="dup", name="n"))


# ---------- service: experiment state machine ----------

def _exp_row(status="draft", **kw) -> Experiment:
    kw.setdefault("code", "exp1")
    kw.setdefault("name", "E")
    kw.setdefault("variants", [{"label": "control"}])
    return _row(Experiment, status=status, **kw)


class TestExperimentService:
    async def test_create_starts_draft(self):
        db = _fake_db({})
        svc = ExperimentService(db)
        e = await svc.create(ExperimentCreate(code="exp-new", name="E"))
        assert e.status == "draft"
        assert e.started_at is None

    async def test_legal_transitions(self):
        e = _exp_row("draft")
        db = _fake_db({"Experiment": [e]})
        svc = ExperimentService(db)
        e = await svc.set_status(e, ExperimentStatusUpdate(status="running"))
        assert e.status == "running"
        assert e.started_at is not None
        e = await svc.set_status(e, ExperimentStatusUpdate(status="paused"))
        assert e.status == "paused"
        # completed is only reachable from running (strict graph: resuming a
        # paused experiment makes it finishable again).
        e = await svc.set_status(e, ExperimentStatusUpdate(status="running"))
        e = await svc.set_status(e, ExperimentStatusUpdate(status="completed"))
        assert e.status == "completed" and e.ended_at is not None

    @pytest.mark.parametrize("to_state", ["draft", "completed", "terminated"])
    async def test_completed_is_terminal(self, to_state):
        e = _exp_row("completed")
        db = _fake_db({"Experiment": [e]})
        svc = ExperimentService(db)
        with pytest.raises(ExperimentStatusError):
            await svc.set_status(e, ExperimentStatusUpdate(status=to_state))

    async def test_draft_cannot_pause(self):
        e = _exp_row("draft")
        db = _fake_db({"Experiment": [e]})
        svc = ExperimentService(db)
        with pytest.raises(ExperimentStatusError):
            await svc.set_status(e, ExperimentStatusUpdate(status="paused"))

    async def test_terminate_requires_reason(self):
        e = _exp_row("running")
        db = _fake_db({"Experiment": [e]})
        svc = ExperimentService(db)
        with pytest.raises(ExperimentStatusError):
            await svc.set_status(e, ExperimentStatusUpdate(status="terminated"))
        e2 = await svc.set_status(_exp_row("running"),
                                  ExperimentStatusUpdate(status="terminated", reason="done"))
        assert e2.ended_at is not None

    async def test_conflict_on_duplicate_code(self):
        db = _fake_db({}, raise_integrity_on_commit=_integrity_err)
        svc = ExperimentService(db)
        with pytest.raises(AnalyticsConflictError):
            await svc.create(ExperimentCreate(code="dup", name="E"))

    async def test_result_requires_live_experiment(self):
        db = _fake_db({"Experiment": []})
        svc = ExperimentService(db)
        data = ExperimentResultCreate(experiment_id=uuid4(), variant_label="v",
                                      metric_code="m", metric_value=Decimal(1))
        with pytest.raises(AnalyticsEntityNotFoundError):
            await svc.add_result(data)

    async def test_add_result_success(self):
        e = _exp_row("running")
        db = _fake_db({"Experiment": [e]})
        svc = ExperimentService(db)
        data = ExperimentResultCreate(experiment_id=e.id, variant_label="control",
                                      metric_code="m.cnt", metric_value=Decimal("42"))
        r = await svc.add_result(data)
        assert r.experiment_id == e.id
        assert r.variant_label == "control"

    async def test_list_results_filters(self):
        e = _exp_row()
        r1 = _row(_exp_res_class(), experiment_id=e.id,
                  variant_label="a", metric_code="m1", sample_size=1, metric_value=Decimal(1))
        db = _fake_db({"ExperimentResult": [r1]})
        svc = ExperimentService(db)
        items, total = await svc.list_results(e.id, variant_label="a")
        assert total == 1 and items[0] is r1
        items, total = await svc.list_results(e.id, variant_label="zzz")
        assert total == 0


# ---------- API layer ----------

def _analytics_app():
    app = FastAPI(title="P6AN-01 analytics-only app")
    app.include_router(analytics_router)
    return app


def _wire_db(app, db: FakeDB):
    from app.db.session import get_db
    app.dependency_overrides[get_db] = lambda: db
    return db


class TestApi:
    def test_routes_registered(self):
        # Version-stable: assert on the OpenAPI path map (full prefixed
        # paths) rather than the internal Route / _IncludedRouter shape,
        # which changed across FastAPI releases (0.14x wraps includes in
        # _IncludedRouter whose sub-routes are unprefixed).
        app = _analytics_app()
        paths = set(app.openapi()["paths"].keys())
        assert "/api/v1/analytics/widgets" in paths
        assert "/api/v1/analytics/experiments" in paths
        assert "/api/v1/analytics/experiment-results/{result_id}" in paths
        assert "/api/v1/analytics/experiments/{experiment_id}/results/summary" in paths

    def test_create_widget_201(self):
        client = TestClient(_analytics_app())
        _wire_db(client.app, _fake_db({}))
        resp = client.post("/api/v1/analytics/widgets", json={"name": "W"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "W" and body["widget_type"] == "kpi"
        assert "id" in body and "created_at" in body

    def test_create_widget_invalid_type_422(self):
        app = _analytics_app()
        client = TestClient(app)
        _wire_db(app, _fake_db({}))
        resp = client.post("/api/v1/analytics/widgets",
                           json={"name": "W", "widget_type": "hologram"})
        assert resp.status_code == 422

    def test_get_missing_widget_404(self):
        app = _analytics_app()
        client = TestClient(app)
        _wire_db(app, _fake_db({"DashboardWidget": []}))
        resp = client.get(f"/api/v1/analytics/widgets/{uuid4()}")
        assert resp.status_code == 404

    def test_delete_widget_204_then_404(self):
        app = _analytics_app()
        client = TestClient(app)
        w = _widget_row()
        db = _wire_db(app, _fake_db({"DashboardWidget": [w]}))
        assert client.delete(f"/api/v1/analytics/widgets/{w.id}").status_code == 204
        assert client.delete(f"/api/v1/analytics/widgets/{w.id}").status_code == 404

    def test_metric_conflict_409(self):
        app = _analytics_app()
        client = TestClient(app)
        db = _fake_db({}, raise_integrity_on_commit=_integrity_err)
        _wire_db(app, db)
        resp = client.post("/api/v1/analytics/metrics",
                           json={"code": "dup", "name": "n"})
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_experiment_status_illegal_409(self):
        app = _analytics_app()
        client = TestClient(app)
        e = _exp_row("completed")
        _wire_db(app, _fake_db({"Experiment": [e]}))
        resp = client.post(f"/api/v1/analytics/experiments/{e.id}/status",
                           json={"status": "running"})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["from_state"] == "completed" and detail["to_state"] == "running"

    def test_experiment_status_legal_200(self):
        app = _analytics_app()
        client = TestClient(app)
        e = _exp_row("draft")
        _wire_db(app, _fake_db({"Experiment": [e]}))
        resp = client.post(f"/api/v1/analytics/experiments/{e.id}/status",
                           json={"status": "running"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_result_requires_experiment_404(self):
        app = _analytics_app()
        client = TestClient(app)
        _wire_db(app, _fake_db({"Experiment": []}))
        resp = client.post(f"/api/v1/analytics/experiments/{uuid4()}/results",
                           json={"variant_label": "v", "metric_code": "m",
                                 "metric_value": "1"})
        assert resp.status_code == 404

    def test_result_create_201(self):
        app = _analytics_app()
        client = TestClient(app)
        e = _exp_row("running")
        _wire_db(app, _fake_db({"Experiment": [e]}))
        resp = client.post(f"/api/v1/analytics/experiments/{e.id}/results",
                           json={"variant_label": "control", "metric_code": "m.cnt",
                                 "metric_value": "42", "p_value": "0.03"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["metric_value"] == "42"

    def test_result_delete_204(self):
        app = _analytics_app()
        client = TestClient(app)
        e = _exp_row()
        from app.db.models.analytics import ExperimentResult as ER
        r = _row(ER, experiment_id=e.id, variant_label="v", metric_code="m",
                 sample_size=0, metric_value=Decimal(1),
                 computed_at=datetime.now(timezone.utc))
        db = _wire_db(app, _fake_db({"Experiment": [e], "ExperimentResult": [r]}))
        assert client.delete(f"/api/v1/analytics/experiment-results/{r.id}").status_code == 204
        assert client.delete(f"/api/v1/analytics/experiment-results/{r.id}").status_code == 404


def _exp_res_class():
    from app.db.models.analytics import ExperimentResult
    return ExperimentResult
