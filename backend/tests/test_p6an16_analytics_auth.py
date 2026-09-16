"""P6AN-16: analytics-surface authentication + tenant isolation (P1-1) tests.

The P6AN-16 architecture review found the entire ``/api/v1/analytics/*``
surface was unauthenticated and had no tenant scope: any caller could read
cross-tenant BI and create/update/delete *any* account's analytics
definitions. This card closes that. These tests cover:

1. **Unit policy** — the role floor, ownership enforcement, create-account
   resolution, list predicates, and cross-account param resolution in
   :mod:`app.security.analytics_access`.
2. **Authentication (401)** — an analytics endpoint with no Bearer token is
   rejected, exercising the real :func:`get_current_principal` decode path.
3. **Authorization (403)** — a token whose role is below the analytics floor
   (or a platform-wide unscoped operator read) is a 403; a viewer cannot
   write; a tenant cannot reach another tenant's definitions / accounts.
4. **Tenant scoping** — CRUD reads/writes are scoped to the caller's account
   (cross-tenant ids are a 404, not a 403 leak; cross-tenant *writes* are a
   403), and the compute read endpoints force the caller's account as the
   tenant scope (never a client-supplied value).

No live Postgres is required — the CRUD layer rides a fake session and the
compute layer rides capturing service stubs, mirroring the P6AN-01/09 repo
conventions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.db.models.analytics import (
    DashboardWidget,
    Experiment,
    MetricDefinition,
    FunnelStep,
)
from app.db.session import get_db
from app.routers.analytics import router as analytics_router
from app.routers.dashboard import router as dashboard_router
from app.routers.agent_performance import router as agent_performance_router
from app.routers.private_domain_conversion import router as pdc_router
from app.routers.roi_analysis import router as roi_router
from app.security.analytics_access import (
    ANALYTICS_ROLES,
    PLATFORM_WIDE_ROLES,
    WRITE_CAPABLE_ROLES,
    assert_account_owns,
    list_account_predicates,
    override_analytics_auth,
    require_analytics_read,
    require_analytics_write,
    resolve_account_param,
    resolve_create_account,
)
from app.security.analytics_access import test_principal as mk_principal
from app.security.jwt_auth import (
    AccountOwnershipError,
    create_access_token,
    decode_access_token,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_ACCT_A = uuid4()
_ACCT_B = uuid4()


def _row(cls, **kw):
    o = cls()
    o.id = kw.pop("id", uuid4())
    now = datetime.now(timezone.utc)
    o.created_at = kw.pop("created_at", now)
    o.updated_at = kw.pop("updated_at", now)
    o.is_deleted = kw.pop("is_deleted", False)
    for k, v in kw.items():
        setattr(o, k, v)
    if isinstance(o, DashboardWidget):
        # DashboardWidgetResponse.from_model validates these; the response
        # model rejects None, so give the fixture the DB defaults.
        o.widget_type = getattr(o, "widget_type", None) or "kpi"
        o.config = getattr(o, "config", None) or {}
        o.refresh_interval_seconds = getattr(o, "refresh_interval_seconds", None) or 300
        o.position = getattr(o, "position", None) or 0
        o.enabled = getattr(o, "enabled", None) if getattr(o, "enabled", None) is not None else True
    return o


class FakeDB:
    """Per-entity CRUD rows + zero-valued scalar aggregates + optional
    IntegrityError injection on commit. Enough for the analytics CRUD layer
    and empty-scope compute paths without a live DB."""

    def __init__(self, entities: Optional[Dict[str, List]] = None,
                 raise_integrity_on_commit: Optional[Any] = None):
        self.entities = entities if entities is not None else {}
        self.raise_integrity = raise_integrity_on_commit
        self.added: List[Any] = []
        self.deleted: List[Any] = []
        self.commits = 0

    def _rows_for(self, stmt):
        desc = stmt.column_descriptions[0]
        ent = desc.get("entity")
        name = ent.__name__ if ent is not None else "unknown"
        rows = list(self.entities.get(name, []))
        criteria = [c for c in getattr(stmt, "_where_criteria", [])]
        if criteria:
            import operator as _op
            rows = [r for r in rows if self._where_matches(criteria, r)]
        return rows

    @staticmethod
    def _where_matches(criteria, row) -> bool:
        import operator as _op
        for crit in criteria:
            op = getattr(crit, "operator", None)
            if op not in (_op.eq, _op.ne):
                continue
            left = crit.left
            colkey = getattr(left, "key", None)
            if colkey is None:
                continue
            expected = getattr(crit.right, "value", crit.right)
            actual = getattr(row, colkey, None)
            if op is _op.ne:
                if actual == expected:
                    return False
            elif actual != expected:
                return False
        return True

    def _result(self, stmt):
        rows = self._rows_for(stmt)
        live = [r for r in rows if getattr(r, "is_deleted", False) is False]

        class Result:
            def scalar_one_or_none(self):
                return live[0] if live else None

            def scalars(self):
                rows = list(live)

                class S:
                    def all(self):
                        return rows

                return S()

            def all(self):
                return []

            def one(self):
                # compute paths (PDC/ROI) hitting this empty fake get zeroed
                # aggregates rather than a crash.
                class _Row:
                    def __getitem__(self, i):
                        return 0

                return _Row()

            def scalar(self):
                return 0

        return Result()

    async def execute(self, stmt):
        return self._result(stmt)

    def add(self, obj):
        self.added.append(obj)
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

    async def rollback(self):
        pass

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        now = datetime.now(timezone.utc)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now


def _analytics_app() -> FastAPI:
    """All five analytics routers + the global cross-account 403 handler.

    The auth dependency is NOT overridden here, so 401/403-role tests exercise
    the real :func:`get_current_principal`. Tenant-scoped behavior tests call
    :func:`override_analytics_auth` on the returned app.
    """
    app = FastAPI(title="P6AN-16 analytics auth app")
    app.include_router(analytics_router)
    app.include_router(dashboard_router)
    app.include_router(agent_performance_router)
    app.include_router(pdc_router)
    app.include_router(roi_router)
    # Mirror main.py's global cross-account handler so a cross-tenant CRUD
    # write returns 403 (not a 500) even in a standalone app.
    @app.exception_handler(AccountOwnershipError)
    async def _acct_ownership(request, exc: AccountOwnershipError):
        return JSONResponse(
            status_code=403,
            content={"code": 403, "message": str(exc), "data": None},
        )
    return app


def _wire_db(app, db: FakeDB):
    app.dependency_overrides[get_db] = lambda: db
    return db


def _tenant_headers(account_id: UUID, role: str = "operator") -> Dict[str, str]:
    token = create_access_token("tester", account_id=str(account_id), role=role)
    return {"Authorization": f"Bearer {token}"}


def _platform_headers(role: str = "admin") -> Dict[str, str]:
    token = create_access_token("admin", account_id=None, role=role)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1) Unit policy
# ---------------------------------------------------------------------------

class TestRoleFloor:
    def test_read_requires_analytics_role(self):
        # An unknown role is rejected at the guard, not silently passed.
        with pytest.raises(Exception) as exc:
            require_analytics_read(mk_principal(role="janitor"))
        assert exc.value.status_code == 403

    def test_read_allows_tenant_analytics_roles(self):
        for role in sorted(ANALYTICS_ROLES):
            p = require_analytics_read(mk_principal(_ACCT_A, role))
            assert p.role == role

    def test_read_blocks_unscoped_platform_wide_operator(self):
        # operator with no account binding may NOT do an unscoped (whole
        # platform) read — the P1 cross-tenant read path is closed at the guard.
        with pytest.raises(Exception) as exc:
            require_analytics_read(mk_principal(None, "operator"))
        assert exc.value.status_code == 403

    def test_read_allows_unscoped_elevated(self):
        p = require_analytics_read(mk_principal(None, "admin"))
        assert p.account_id is None

    def test_write_requires_write_role(self):
        with pytest.raises(Exception) as exc:
            require_analytics_write(mk_principal(_ACCT_A, "viewer"))
        assert exc.value.status_code == 403
        for role in sorted(WRITE_CAPABLE_ROLES):
            assert require_analytics_write(
                mk_principal(_ACCT_A, role)).role == role


class TestOwnershipPolicy:
    def test_tenant_own_row_ok(self):
        assert_account_owns(_ACCT_A, mk_principal(_ACCT_A, "operator"))

    def test_tenant_foreign_row_403(self):
        with pytest.raises(AccountOwnershipError):
            assert_account_owns(_ACCT_B, mk_principal(_ACCT_A, "operator"))

    def test_tenant_cannot_touch_platform_wide(self):
        # A plain tenant operator must not read/mutate platform-wide (NULL) defs.
        with pytest.raises(AccountOwnershipError):
            assert_account_owns(None, mk_principal(_ACCT_A, "operator"))

    def test_elevated_tenant_can_touch_platform_wide(self):
        assert_account_owns(None, mk_principal(_ACCT_A, "admin"))

    def test_platform_wide_actor_touches_any(self):
        assert_account_owns(_ACCT_B, mk_principal(None, "admin"))
        assert_account_owns(None, mk_principal(None, "admin"))


class TestCreateResolution:
    def test_tenant_none_forces_own(self):
        assert resolve_create_account(None, mk_principal(_ACCT_A, "operator")) == _ACCT_A

    def test_tenant_own_ok(self):
        assert resolve_create_account(_ACCT_A, mk_principal(_ACCT_A)) == _ACCT_A

    def test_tenant_foreign_403(self):
        with pytest.raises(AccountOwnershipError):
            resolve_create_account(_ACCT_B, mk_principal(_ACCT_A, "operator"))

    def test_platform_wide_operator_cannot_create_null(self):
        with pytest.raises(AccountOwnershipError):
            resolve_create_account(None, mk_principal(None, "operator"))

    def test_platform_wide_admin_can_create_null_or_account(self):
        assert resolve_create_account(None, mk_principal(None, "admin")) is None
        assert resolve_create_account(_ACCT_B, mk_principal(None, "admin")) == _ACCT_B


def _list_sql(principal):
    """Compile list_account_predicates into a WHERE clause (literal binds).

    Deterministic and robust: it inspects the *actual SQL* the service would
    emit, so a regression that drops a clause (or adds a cross-tenant leak)
    shows up as a missing / extra term in the rendered predicate.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    preds = list_account_predicates(DashboardWidget, principal)
    if not preds:
        return None  # platform-wide actor: unscoped list
    stmt = select(DashboardWidget).where(*preds)
    return " ".join(
        str(stmt.compile(dialect=postgresql.dialect(),
                         compile_kwargs={"literal_binds": True})).split()
    )


class TestListPredicates:
    def test_tenant_list_scoped_to_own_account_only(self):
        sql = _list_sql(mk_principal(_ACCT_A, "operator"))
        assert sql is not None
        assert str(_ACCT_A) in sql                      # own account
        assert "IS NULL" not in sql.upper()             # no platform-wide leak
        assert str(_ACCT_B) not in sql                  # no other tenant

    def test_elevated_tenant_list_includes_platform_wide(self):
        sql = _list_sql(mk_principal(_ACCT_A, "admin"))
        assert sql is not None
        assert str(_ACCT_A) in sql
        assert "IS NULL" in sql.upper()                 # + platform-wide NULL rows

    def test_platform_wide_actor_unscoped(self):
        assert _list_sql(mk_principal(None, "admin")) is None


class TestAccountParamResolution:
    def test_tenant_forced_to_own(self):
        assert resolve_account_param(None, mk_principal(_ACCT_A, "operator")) == _ACCT_A
        assert resolve_account_param(_ACCT_A, mk_principal(_ACCT_A)) == _ACCT_A

    def test_tenant_cannot_request_foreign(self):
        with pytest.raises(AccountOwnershipError):
            resolve_account_param(_ACCT_B, mk_principal(_ACCT_A, "operator"))

    def test_platform_wide_passthrough(self):
        assert resolve_account_param(None, mk_principal(None, "admin")) is None
        assert resolve_account_param(_ACCT_B, mk_principal(None, "admin")) == _ACCT_B


# ---------------------------------------------------------------------------
# 2) Authentication — 401 with no token
# ---------------------------------------------------------------------------

class TestUnauthenticated:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/v1/analytics/widgets"),
            ("GET", "/api/v1/analytics/dashboard/overview"),
            ("GET", "/api/v1/analytics/agents/performance"),
            ("GET", "/api/v1/analytics/private-domain/conversion"),
            ("GET", "/api/v1/analytics/roi"),
            ("GET", "/api/v1/analytics/funnel"),
            ("GET", "/api/v1/analytics/conversations"),
            ("GET", "/api/v1/analytics/leads/conversion"),
            ("POST", "/api/v1/analytics/widgets"),
            ("DELETE", "/api/v1/analytics/widgets/" + str(uuid4())),
        ],
    )
    def test_no_token_is_401(self, method, path):
        app = _analytics_app()
        _wire_db(app, FakeDB())
        client = TestClient(app)
        resp = client.request(method, path)
        assert resp.status_code == 401, (path, resp.status_code, resp.text)

    def test_garbage_token_is_401(self):
        app = _analytics_app()
        _wire_db(app, FakeDB())
        client = TestClient(app)
        resp = client.get("/api/v1/analytics/widgets",
                          headers={"Authorization": "Bearer not.a.token"})
        assert resp.status_code == 401

    def test_expired_token_is_401(self):
        import time
        tok = create_access_token("u", account_id=str(_ACCT_A), role="operator",
                                  ttl_seconds=-1)
        app = _analytics_app()
        _wire_db(app, FakeDB())
        client = TestClient(app)
        resp = client.get("/api/v1/analytics/widgets",
                          headers={"Authorization": f"Bearer {tok}"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 3) Authorization — 403 for insufficient role / unscoped operator read
# ---------------------------------------------------------------------------

class TestRoleAuthorization:
    def test_unknown_role_is_403(self):
        app = _analytics_app()
        _wire_db(app, FakeDB())
        client = TestClient(app)
        tok = create_access_token("u", account_id=str(_ACCT_A), role="janitor")
        resp = client.get("/api/v1/analytics/widgets",
                          headers={"Authorization": f"Bearer {tok}"})
        assert resp.status_code == 403

    def test_viewer_cannot_write(self):
        app = _analytics_app()
        _wire_db(app, FakeDB())
        client = TestClient(app)
        tok = create_access_token("v", account_id=str(_ACCT_A), role="viewer")
        resp = client.post("/api/v1/analytics/widgets",
                           json={"name": "W"},
                           headers={"Authorization": f"Bearer {tok}"})
        assert resp.status_code == 403

    def test_viewer_can_read(self):
        app = _analytics_app()
        _wire_db(app, FakeDB())
        client = TestClient(app)
        tok = create_access_token("v", account_id=str(_ACCT_A), role="viewer")
        resp = client.get("/api/v1/analytics/widgets",
                          headers={"Authorization": f"Bearer {tok}"})
        assert resp.status_code == 200

    def test_unscoped_platform_wide_operator_read_is_403(self):
        # A tenant operator with NO account binding may not read the whole
        # platform — the P1 cross-tenant read leak, closed at the guard.
        app = _analytics_app()
        _wire_db(app, FakeDB())
        client = TestClient(app)
        tok = create_access_token("op", account_id=None, role="operator")
        resp = client.get("/api/v1/analytics/dashboard/overview",
                          headers={"Authorization": f"Bearer {tok}"})
        assert resp.status_code == 403

    def test_platform_wide_admin_can_read(self):
        app = _analytics_app()
        _wire_db(app, FakeDB())
        client = TestClient(app)
        resp = client.get("/api/v1/analytics/dashboard/overview",
                          headers=_platform_headers("admin"))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 4) Tenant scoping — CRUD (definitions)
# ---------------------------------------------------------------------------

class TestCrudTenancy:
    def _app(self, db):
        app = _analytics_app()
        _wire_db(app, db)
        return app

    def test_tenant_reads_own_widget_200(self):
        w = _row(DashboardWidget, name="mine", account_id=_ACCT_A)
        app = self._app(FakeDB({"DashboardWidget": [w]}))
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        resp = client.get(f"/api/v1/analytics/widgets/{w.id}")
        assert resp.status_code == 200
        assert resp.json()["account_id"] == str(_ACCT_A)

    def test_tenant_cannot_read_foreign_widget_404(self):
        w = _row(DashboardWidget, name="theirs", account_id=_ACCT_B)
        app = self._app(FakeDB({"DashboardWidget": [w]}))
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        # Cross-tenant id is a 404, not a 403 — the API never leaks which
        # accounts exist.
        resp = client.get(f"/api/v1/analytics/widgets/{w.id}")
        assert resp.status_code == 404

    def test_tenant_create_forces_own_account(self):
        app = self._app(FakeDB())
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        # body omits account_id -> created under the tenant's own account.
        resp = client.post("/api/v1/analytics/widgets", json={"name": "W"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["account_id"] == str(_ACCT_A)

    def test_tenant_create_cross_tenant_403(self):
        app = self._app(FakeDB())
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        # A tenant trying to create under another account's id -> 403.
        resp = client.post("/api/v1/analytics/widgets",
                           json={"name": "W", "account_id": str(_ACCT_B)})
        assert resp.status_code == 403

    def test_tenant_list_is_scoped(self):
        mine = _row(DashboardWidget, name="mine", account_id=_ACCT_A)
        theirs = _row(DashboardWidget, name="theirs", account_id=_ACCT_B)
        app = self._app(FakeDB({"DashboardWidget": [mine, theirs]}))
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        resp = client.get("/api/v1/analytics/widgets")
        assert resp.status_code == 200
        names = [w["name"] for w in resp.json()["items"]]
        assert names == ["mine"]

    def test_platform_wide_admin_sees_all(self):
        a = _row(DashboardWidget, name="a", account_id=_ACCT_A)
        b = _row(DashboardWidget, name="b", account_id=_ACCT_B)
        app = self._app(FakeDB({"DashboardWidget": [a, b]}))
        override_analytics_auth(app, mk_principal(None, "admin"))
        client = TestClient(app)
        resp = client.get("/api/v1/analytics/widgets")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_tenant_delete_foreign_is_404(self):
        w = _row(DashboardWidget, name="theirs", account_id=_ACCT_B)
        app = self._app(FakeDB({"DashboardWidget": [w]}))
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        resp = client.delete(f"/api/v1/analytics/widgets/{w.id}")
        assert resp.status_code == 404


class TestExperimentTenancy:
    def _app(self, db):
        app = _analytics_app()
        _wire_db(app, db)
        return app

    def test_tenant_cannot_mutate_foreign_experiment_403(self):
        e = _row(Experiment, code="e", name="E", variants=[{"label": "c"}],
                 status="draft", account_id=_ACCT_B)
        app = self._app(FakeDB({"Experiment": [e]}))
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        # The experiment is invisible to tenant A -> the update 404s on fetch.
        resp = client.put(f"/api/v1/analytics/experiments/{e.id}", json={"name": "x"})
        assert resp.status_code == 404

    def test_result_visible_only_via_own_experiment(self):
        from app.db.models.analytics import ExperimentResult
        e = _row(Experiment, code="e", name="E", variants=[{"label": "c"}],
                 status="running", account_id=_ACCT_B)
        r = _row(ExperimentResult, experiment_id=e.id, variant_label="c",
                 metric_code="m", sample_size=1, metric_value=Decimal(1))
        app = self._app(FakeDB({"Experiment": [e], "ExperimentResult": [r]}))
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        # Tenant A cannot read B's experiment's result (404, not a leak).
        resp = client.get(f"/api/v1/analytics/experiment-results/{r.id}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5) Tenant scoping — compute reads (account forced from the token)
# ---------------------------------------------------------------------------

class TestComputeTenancy:
    def test_funnel_forces_tenant_account(self):
        # Capture the account_id the router passes to the funnel service.
        import app.services.funnel_service as fs
        captured: Dict[str, Any] = {}

        async def _cap(db, **kw):
            captured.update(kw)
            return {
                "funnel_code": kw.get("funnel_code") or "acquisition",
                "stages": [],
                "total": 0,
                "conversion_rate": None,
                "filters": {k: (str(v) if isinstance(v, UUID) else v)
                             for k, v in kw.items() if k in
                             ("agent_id", "platform_id", "account_id", "range", "from", "to", "funnel_code")},
            }

        app = _analytics_app()
        _wire_db(app, FakeDB())
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        with _patch_funnel(_cap):
            resp = client.get("/api/v1/analytics/funnel", params={"range": "30d"})
        assert resp.status_code == 200, resp.text
        assert captured["account_id"] == _ACCT_A

    def test_pdc_forces_tenant_account(self):
        captured: Dict[str, Any] = {}

        class _CapPDC:
            def __init__(self, db):
                pass

            async def get_conversion(self, **kw):
                captured.update(kw)
                now = datetime.now(timezone.utc)
                return {
                    "window": {"since": now - timedelta(days=30), "until": now,
                               "default_applied": False},
                    "agent_id": kw.get("agent_id"),
                    "account_id": kw.get("account_id"),
                    "funnel": {"base_customers": 0, "reached_customers": 0,
                                "interacted_customers": 0, "converted_customers": 0,
                                "reach_rate_percent": 0.0, "interaction_rate_percent": 0.0,
                                "conversion_rate_percent": 0.0,
                                "reach_rate_overall_percent": 0.0,
                                "interaction_rate_overall_percent": 0.0,
                                "conversion_rate_overall_percent": 0.0},
                    "ltv": {"won_deal_count": 0, "total_won_value_cents": 0,
                             "avg_won_deal_value_cents": 0.0,
                             "ltv_proxy_cents_per_reached": 0.0, "currencies": []},
                    "nurture_execution": {"success_attempts": 0, "executed_attempts": 0,
                                            "execution_rate_percent": 0.0},
                    "follow_up": {"completed": 0, "total": 0, "completion_rate_percent": 0.0},
                    "roi_inputs": {"total_won_value_cents": 0, "won_deal_count": 0,
                                    "reached_customers": 0, "base_customers": 0,
                                    "ltv_proxy_cents_per_reached": 0.0},
                }

        import app.routers.private_domain_conversion as pdc_mod
        app = _analytics_app()
        _wire_db(app, FakeDB())
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        orig = pdc_mod.PrivateDomainConversionService
        pdc_mod.PrivateDomainConversionService = _CapPDC
        try:
            resp = client.get("/api/v1/analytics/private-domain/conversion")
        finally:
            pdc_mod.PrivateDomainConversionService = orig
        assert resp.status_code == 200, resp.text
        # A tenant's PDC read is forced to its own account.
        assert captured["account_id"] == _ACCT_A

    def test_pdc_cross_tenant_param_403(self):
        import app.routers.private_domain_conversion as pdc_mod
        app = _analytics_app()
        _wire_db(app, FakeDB())
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        resp = client.get("/api/v1/analytics/private-domain/conversion",
                          params={"account_id": str(_ACCT_B)})
        # A tenant that requests another account's data -> 403.
        assert resp.status_code == 403, resp.text

    def test_roi_forces_tenant_account(self):
        captured: Dict[str, Any] = {}

        class _CapROI:
            def __init__(self, db):
                pass

            async def get_roi(self, **kw):
                captured.update(kw)
                from app.schemas.roi_analysis import ROIResponse
                now = datetime.now(timezone.utc)
                return ROIResponse(
                    dimension=kw["dimension"],
                    window={"since": now - timedelta(days=30), "until": now,
                             "default_applied": True},
                    filters={"dimension": kw["dimension"], "agent_id": None,
                             "account_id": kw.get("account_id"), "since": None, "until": None},
                    cost_rates={"cost_per_outbound_message_cents": 0,
                                 "cost_per_nurture_execution_cents": 0,
                                 "cost_per_followup_task_cents": 0,
                                 "cost_per_active_agent_cents": 0,
                                 "cost_per_campaign_lead_cents": 0, "configured": False},
                    cost_basis_configured=False,
                    summary={"revenue_cents": 0, "won_deal_count": 0,
                              "input_cents": 0, "net_cents": 0,
                              "roi": None, "roi_percent": None,
                              "activity": {}, "input_breakdown": {}},
                    items=[],
                )

        import app.routers.roi_analysis as roi_mod
        app = _analytics_app()
        _wire_db(app, FakeDB())
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        orig = roi_mod.ROIService
        roi_mod.ROIService = _CapROI
        try:
            resp = client.get("/api/v1/analytics/roi")
        finally:
            roi_mod.ROIService = orig
        assert resp.status_code == 200, resp.text
        assert captured["account_id"] == _ACCT_A

    def test_leads_conversion_forces_tenant_account(self):
        captured: Dict[str, Any] = {}

        class _CapLead:
            def __init__(self, db):
                pass

            async def compute(self, **kw):
                captured.update(kw)
                return {
                    "filters": {"agent_id": str(kw.get("agent_id")) if kw.get("agent_id") else None,
                                "account_id": str(kw.get("account_id")) if kw.get("account_id") else None,
                                "channel": kw.get("channel"), "from_date": kw.get("from_date"),
                                "to_date": kw.get("to_date"), "group_by": kw.get("group_by", "overall"),
                                "window_basis": "lead.created_at"},
                    "totals": {"total_leads": 0, "status_counts": {},
                                "stage_reached_counts": {}, "conversion_rates": {},
                                "avg_conversion_cycle_days": None},
                    "groups": [],
                }

        import app.routers.analytics as an_mod
        app = _analytics_app()
        _wire_db(app, FakeDB())
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        orig = an_mod.LeadConversionService
        an_mod.LeadConversionService = _CapLead
        try:
            resp = client.get("/api/v1/analytics/leads/conversion")
        finally:
            an_mod.LeadConversionService = orig
        assert resp.status_code == 200, resp.text
        assert captured["account_id"] == _ACCT_A

    def test_dashboard_forces_tenant_account(self):
        captured: Dict[str, Any] = {}
        import app.routers.dashboard as dash_mod
        from app.schemas.dashboard import DashboardOverviewResponse

        class _CapDash:
            def __init__(self, db):
                pass

            async def compute(self, **kw):
                captured.update(kw)
                now = datetime.now(timezone.utc)
                return DashboardOverviewResponse(
                    range={"start": now - timedelta(days=30), "end": now, "days": 30},
                    agents={"total": 0, "active": 0},
                    conversations={"new": 0, "active": 0, "total_messages": 0,
                                   "avg_messages_per_new_conversation": None},
                    messages={"total": 0, "sent": 0, "delivered": 0, "failed": 0,
                              "success_rate": None},
                    conversion={"new_leads": 0, "total_leads": 0, "closed_leads": 0,
                                "conversion_rate": None},
                    by_agent=[],
                    computed_at=now,
                )

        app = _analytics_app()
        _wire_db(app, FakeDB())
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        orig = dash_mod.DashboardOverviewService
        dash_mod.DashboardOverviewService = _CapDash
        try:
            resp = client.get("/api/v1/analytics/dashboard/overview")
        finally:
            dash_mod.DashboardOverviewService = orig
        assert resp.status_code == 200, resp.text
        assert captured["account_id"] == _ACCT_A

    def test_agent_performance_forces_tenant_account(self):
        captured: Dict[str, Any] = {}
        import app.routers.agent_performance as ap_mod
        from app.schemas.agent_performance import (
            AgentPerformanceLeaderboardResponse,
            AgentPerformanceResponse,
            AgentPerformanceMetrics,
        )
        from app.db.models.agent import Agent

        class _CapAP:
            def __init__(self, db):
                pass

            async def leaderboard(self, **kw):
                captured["leaderboard"] = kw
                return AgentPerformanceLeaderboardResponse(
                    items=[], total_agents=0, sort_key="conversations", order="desc",
                    page=1, page_size=20, window={"range": "30d"},
                )

            async def single(self, agent_id, **kw):
                captured["single"] = kw
                return AgentPerformanceResponse(
                    metrics=AgentPerformanceMetrics(
                        agent_id=agent_id, agent_name="x", status="active",
                        total_customers=0, active_customers=0, conversation_count=0,
                        message_count=0, lead_count=0, converted_lead_count=0,
                        conversion_rate=None, satisfaction_proxy=None,
                        satisfaction_sample=0,
                        sentiment_breakdown={"positive": 0, "neutral": 0, "negative": 0},
                        active_hours=[0] * 24, peak_hour=None,
                    ),
                    window={"range": "30d"},
                )

        app = _analytics_app()
        _wire_db(app, FakeDB())
        override_analytics_auth(app, mk_principal(_ACCT_A, "operator"))
        client = TestClient(app)
        orig = ap_mod.AgentPerformanceService
        ap_mod.AgentPerformanceService = _CapAP
        try:
            r1 = client.get("/api/v1/analytics/agents/performance")
            assert r1.status_code == 200, r1.text
            r2 = client.get(f"/api/v1/analytics/agents/performance/metrics/{uuid4()}")
            assert r2.status_code == 200, r2.text
        finally:
            ap_mod.AgentPerformanceService = orig
        assert captured["leaderboard"]["account_id"] == _ACCT_A
        assert captured["single"]["account_id"] == _ACCT_A


def _patch_funnel(func):
    """Context manager patching the funnel compute (imported at call time)."""
    import contextlib

    @contextlib.contextmanager
    def _cm():
        import app.services.funnel_service as fs
        orig = fs.compute_funnel
        fs.compute_funnel = func
        try:
            yield
        finally:
            fs.compute_funnel = orig

    return _cm()
