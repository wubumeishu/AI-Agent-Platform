"""P6AN-06 Private Domain Conversion: 口径 + service + API tests.

Two layers (mirrors the P5MSG-03 / P6AN-01 repo conventions):

1. **Pure layer** (no DB): the rate math (``_pct``), window resolution, and
   the pure ``assemble`` step — div-by-zero guards, rounding, step vs overall
   rates, and the LTV-proxy口径. These are the "指标计算正确" acceptance check
   done at the math level so they run deterministically without Postgres.

2. **Live PG layer** (``ai_agent_platform_test``): seed the Phase-5 source
   rows (customers, agent bindings, conversations, outbound/inbound messages,
   won deals, nurture executions, follow-up tasks), call the service
   end-to-end, and 对拍 the raw counts against hand-computed expectations.
   Skipped cleanly when the test DB is unreachable.

The LTV proxy口径 is documented in
``docs/P6AN-06-private-domain-conversion-api.md``.
"""
from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models.account import Account
from app.db.models.agent import Agent, AgentCustomerBinding
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.messages import ChannelMessage
from app.db.models.nurture_execution import NurtureStepExecution
from app.db.models.platform import Platform
from app.db.models.private_domain import DealItem, DealPipeline, FollowUpTask
from app.schemas.private_domain_conversion import (
    ConversionFilters,
    PDCResponse,
)
from app.services.private_domain_conversion import (
    DEFAULT_WINDOW_DAYS,
    PrivateDomainConversionService,
    _coerce_aware,
    _pct,
)

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"
_TEST_URL_ASYNCPG = "postgresql://postgres:postgres@localhost:5432/ai_agent_platform_test"


def _pg_available() -> bool:
    if importlib.util.find_spec("asyncpg") is None:
        return False

    async def probe():
        import asyncpg

        try:
            c = await asyncpg.connect(_TEST_URL_ASYNCPG, timeout=3)
            await c.close()
            return True
        except Exception:
            return False

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(probe())
    finally:
        loop.close()


LIVE = _pg_available()
skip_live = pytest.mark.skipif(not LIVE, reason="Postgres test DB (ai_agent_platform_test) unreachable")


# ==========================================================================
# 1) Pure math layer
# ==========================================================================
class TestPctMath:
    def test_pct_normal(self):
        assert _pct(1, 4) == 25.0

    def test_pct_rounds_two_decimals(self):
        assert _pct(1, 3) == 33.33

    def test_pct_zero_denominator(self):
        assert _pct(5, 0) == 0.0

    def test_pct_zero_numerator(self):
        assert _pct(0, 10) == 0.0


class TestWindowResolution:
    def _svc(self):
        return PrivateDomainConversionService(db=None)  # type: ignore[arg-type]

    def test_explicit_window_not_default(self):
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        until = datetime(2026, 2, 1, tzinfo=timezone.utc)
        s, u, dfl = self._svc()._resolve_window(since, until)
        assert s == since and u == until and dfl is False

    def test_since_only_extends_forward(self):
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        s, u, dfl = self._svc()._resolve_window(since, None)
        assert s == since
        assert u == since + timedelta(days=DEFAULT_WINDOW_DAYS)
        assert dfl is False

    def test_until_only_extends_backward(self):
        until = datetime(2026, 2, 1, tzinfo=timezone.utc)
        s, u, dfl = self._svc()._resolve_window(None, until)
        assert u == until
        assert s == until - timedelta(days=DEFAULT_WINDOW_DAYS)

    def test_neither_defaults_30d_ending_now(self):
        s, u, dfl = self._svc()._resolve_window(None, None)
        assert dfl is True
        assert u - s == timedelta(days=DEFAULT_WINDOW_DAYS)

    def test_naive_inputs_coerced_to_utc(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        aware = _coerce_aware(naive)
        assert aware.tzinfo is not None
        assert aware == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestAssemblePure:
    """The pure assemble step: div-by-zero guards, step vs overall rates."""

    def _svc(self):
        return PrivateDomainConversionService(db=None)  # type: ignore[arg-type]

    def test_empty_database_all_zero_no_div_error(self):
        raw = {
            "base_customers": 0, "reached_customers": 0, "interacted_customers": 0,
            "converted_customers": 0, "won_deal_count": 0, "total_won_value_cents": 0,
            "ltv_currencies": [], "nse_success_attempts": 0, "nse_executed_attempts": 0,
            "fu_completed": 0, "fu_total": 0,
        }
        out = self._svc().assemble(raw, None, None,
                                   datetime.now(timezone.utc), datetime.now(timezone.utc), False)
        assert out["funnel"]["reach_rate_percent"] == 0.0
        assert out["ltv"]["ltv_proxy_cents_per_reached"] == 0.0
        assert out["nurture_execution"]["execution_rate_percent"] == 0.0
        assert out["follow_up"]["completion_rate_percent"] == 0.0

    def test_step_vs_overall_rates(self):
        raw = {
            "base_customers": 100, "reached_customers": 50, "interacted_customers": 25,
            "converted_customers": 10, "won_deal_count": 4, "total_won_value_cents": 40000,
            "ltv_currencies": ["CNY"], "nse_success_attempts": 0, "nse_executed_attempts": 0,
            "fu_completed": 0, "fu_total": 0,
        }
        out = self._svc().assemble(raw, None, None,
                                   datetime.now(timezone.utc), datetime.now(timezone.utc), False)
        f = out["funnel"]
        # step rates: reached/base, interacted/reached, converted/interacted
        assert f["reach_rate_percent"] == 50.0
        assert f["interaction_rate_percent"] == 50.0        # 25/50
        assert f["conversion_rate_percent"] == 40.0         # 10/25
        # overall rates: all vs base
        assert f["interaction_rate_overall_percent"] == 25.0  # 25/100
        assert f["conversion_rate_overall_percent"] == 10.0   # 10/100

    def test_ltv_proxy_values(self):
        raw = {
            "base_customers": 10, "reached_customers": 4, "interacted_customers": 2,
            "converted_customers": 2, "won_deal_count": 3, "total_won_value_cents": 30000,
            "ltv_currencies": ["CNY"], "nse_success_attempts": 0, "nse_executed_attempts": 0,
            "fu_completed": 0, "fu_total": 0,
        }
        out = self._svc().assemble(raw, None, None,
                                   datetime.now(timezone.utc), datetime.now(timezone.utc), False)
        ltv = out["ltv"]
        # 金额/次数 (single transaction) = 30000 / 3
        assert ltv["avg_won_deal_value_cents"] == 10000.0
        # value-per-reached = 30000 / 4
        assert ltv["ltv_proxy_cents_per_reached"] == 7500.0
        # roi_inputs mirror the same raw value
        assert out["roi_inputs"]["total_won_value_cents"] == 30000
        assert out["roi_inputs"]["reached_customers"] == 4


class TestSchemaShape:
    def test_conversion_filters_defaults(self):
        f = ConversionFilters()
        assert f.agent_id is None and f.account_id is None
        assert f.since is None and f.until is None

    def test_response_round_trip(self):
        payload = {
            "window": {"since": datetime.now(timezone.utc), "until": datetime.now(timezone.utc)},
            "funnel": {"base_customers": 1, "reached_customers": 1},
            "ltv": {}, "nurture_execution": {}, "follow_up": {}, "roi_inputs": {},
        }
        r = PDCResponse(**payload)
        assert r.funnel.base_customers == 1


# ==========================================================================
# 3) API-layer (real HTTP path via TestClient, service patched)
# ==========================================================================
class _CapturedService:
    """Stand-in for the service the router instantiates, so the HTTP test can
    assert the window strings were parsed + forward the right args without a DB."""

    def __init__(self):
        self.calls: list = []

    async def get_conversion(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "window": {"since": _SINCE, "until": _UNTIL, "default_applied": False},
            "agent_id": kwargs.get("agent_id"),
            "account_id": kwargs.get("account_id"),
            "funnel": {}, "ltv": {}, "nurture_execution": {}, "follow_up": {},
            "roi_inputs": {},
        }


def _make_pdc_app(captured: _CapturedService):
    from fastapi import FastAPI
    from app.db.session import get_db
    from app.routers.private_domain_conversion import router as pdc_router

    app = FastAPI(title="P6AN-06 PDC-only app")
    app.include_router(pdc_router)
    # P6AN-16: the analytics surface now requires an authenticated principal.
    # Functional tests exercise PDC behavior with a platform-wide admin
    # principal (no tenant scoping) to preserve the legacy unscoped semantics.
    from app.security.analytics_access import override_analytics_auth, test_principal
    override_analytics_auth(app, test_principal(role="admin"))
    app.dependency_overrides[get_db] = lambda: object()
    return app


class TestApiLayer:
    def test_get_returns_200_and_parses_iso_window(self, monkeypatch):
        import app.routers.private_domain_conversion as mod
        captured = _CapturedService()
        app = _make_pdc_app(captured)
        monkeypatch.setattr(mod, "PrivateDomainConversionService", lambda db: captured)

        from fastapi.testclient import TestClient

        resp = TestClient(app).get(
            "/api/v1/analytics/private-domain/conversion",
            params={"since": "2026-07-01T00:00:00Z", "until": "2026-09-01T00:00:00Z"},
        )
        assert resp.status_code == 200, resp.text
        # funnel defaults to the full PDCFunnel (base 0) after response validation
        assert resp.json()["funnel"]["base_customers"] == 0
        # window strings were parsed into aware datetimes (Z normalised to +00:00)
        assert captured.calls[0]["since"] == datetime.fromisoformat("2026-07-01T00:00:00+00:00")
        assert captured.calls[0]["until"] == datetime.fromisoformat("2026-09-01T00:00:00+00:00")

    def test_get_no_params_defaults(self, monkeypatch):
        import app.routers.private_domain_conversion as mod
        captured = _CapturedService()
        app = _make_pdc_app(captured)
        monkeypatch.setattr(mod, "PrivateDomainConversionService", lambda db: captured)

        from fastapi.testclient import TestClient

        resp = TestClient(app).get("/api/v1/analytics/private-domain/conversion")
        assert resp.status_code == 200, resp.text
        assert captured.calls[0]["since"] is None
        assert captured.calls[0]["until"] is None
        assert captured.calls[0]["agent_id"] is None
        assert captured.calls[0]["account_id"] is None

    def test_get_invalid_uuid_agent_422(self, monkeypatch):
        import app.routers.private_domain_conversion as mod
        captured = _CapturedService()
        app = _make_pdc_app(captured)
        monkeypatch.setattr(mod, "PrivateDomainConversionService", lambda db: captured)

        from fastapi.testclient import TestClient

        resp = TestClient(app).get(
            "/api/v1/analytics/private-domain/conversion",
            params={"agent_id": "not-a-uuid"},
        )
        assert resp.status_code == 422
        assert captured.calls == []  # never reached the service (validation gate)

    def test_get_malformed_since_422(self, monkeypatch):
        import app.routers.private_domain_conversion as mod
        captured = _CapturedService()
        app = _make_pdc_app(captured)
        monkeypatch.setattr(mod, "PrivateDomainConversionService", lambda db: captured)

        from fastapi.testclient import TestClient

        resp = TestClient(app).get(
            "/api/v1/analytics/private-domain/conversion",
            params={"since": "not-a-date"},
        )
        assert resp.status_code == 422
        assert "Invalid ISO-8601" in resp.json()["detail"]
        assert captured.calls == []  # malformed window parsed before service call

    def test_get_agent_id_forwarded_as_uuid(self, monkeypatch):
        import app.routers.private_domain_conversion as mod
        captured = _CapturedService()
        app = _make_pdc_app(captured)
        monkeypatch.setattr(mod, "PrivateDomainConversionService", lambda db: captured)

        from fastapi.testclient import TestClient

        agent = uuid4()
        resp = TestClient(app).get(
            "/api/v1/analytics/private-domain/conversion",
            params={"agent_id": str(agent)},
        )
        assert resp.status_code == 200
        assert captured.calls[0]["agent_id"] == agent  # parsed to UUID, not str



# ==========================================================================
# 2) Live-PG 对拍 layer
# ==========================================================================
# Deterministic window + seed timestamps.
_T = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)          # in-window
_T_OUT = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)      # out-of-window
_SINCE = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
_UNTIL = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Seed:
    """Holds the ids of everything the live tests create so teardown is precise."""

    def __init__(self):
        self.ids: dict[str, list] = {
            "messages": [], "conversations": [], "nse": [], "fu": [],
            "deals": [], "pipelines": [], "bindings": [], "customers": [],
            "agents": [], "accounts": [], "platforms": [],
        }
        self.customers: dict[str, "uuid"] = {}
        self.agent_id = None
        self.account_id = None

    def cleanup(self, db: AsyncSession) -> "asyncio.coroutine":
        async def _run() -> None:
            pairs = [
                (ChannelMessage, "messages"),
                (NurtureStepExecution, "nse"),
                (FollowUpTask, "fu"),
                (DealItem, "deals"),
                (Conversation, "conversations"),
                (AgentCustomerBinding, "bindings"),
                (Customer, "customers"),
                (DealPipeline, "pipelines"),
                (Agent, "agents"),
                (Account, "accounts"),
                (Platform, "platforms"),
            ]
            for model, key in pairs:
                ids = self.ids.get(key, [])
                if ids:
                    await db.execute(delete(model).where(model.id.in_(ids)))
            await db.commit()
        return _run()


@skip_live
@pytest.mark.asyncio
async def test_pdc_full_funnel_no_filters_on_live_db():
    """Seed the full Phase-5 source graph under a fresh account, then 对拍 every
    funnel/LTV/completion number against hand-computed expectations.

    The shared test DB has pre-existing rows, so the account-owned sources
    (messages / deals / follow-up / nurture) are scoped to the seeded
    ``account_id`` — that keeps the aggregates clean. The customer base is
    agent-scoped (bound customers) so the denominator is a clean, small set
    rather than the whole (polluted) customer table.
    """
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    seed = _Seed()
    async with Session() as db:
        await _seed_source_graph(db, seed, T=_T)
        svc = PrivateDomainConversionService(db)
        out = await svc.get_conversion(agent_id=seed.agent_id,
                                       account_id=seed.account_id,
                                       since=_SINCE, until=_UNTIL)
        f = out["funnel"]
        # Agent bound to c1,c2,c3 -> base 3 (the clean, agent-scoped denominator)
        assert f["base_customers"] == 3, f
        # reached = c1,c2 (bound + outbound sent/delivered); c3 has no messages
        assert f["reached_customers"] == 2, f
        assert f["interacted_customers"] == 2, f  # c1 + c2 inbound
        assert f["converted_customers"] == 3, f  # c1,c2,c3 won deals
        assert f["reach_rate_percent"] == pytest.approx(66.67, abs=0.01)  # 2/3
        assert f["conversion_rate_overall_percent"] == pytest.approx(100.0)  # 3/3

        ltv = out["ltv"]
        assert ltv["won_deal_count"] == 3, ltv          # c1,c2,c3 under this account
        assert ltv["total_won_value_cents"] == 18000, ltv  # 10000+5000+3000
        assert ltv["avg_won_deal_value_cents"] == 6000.0    # 18000/3
        assert ltv["ltv_proxy_cents_per_reached"] == 9000.0  # 18000/2

        ne = out["nurture_execution"]
        assert ne["success_attempts"] == 2, ne
        assert ne["executed_attempts"] == 5, ne  # success+failed+dead_letter+skipped
        assert ne["execution_rate_percent"] == 40.0  # 2/5

        fu = out["follow_up"]
        assert fu["completed"] == 3, fu
        assert fu["total"] == 7, fu
        assert fu["completion_rate_percent"] == pytest.approx(42.86, abs=0.01)  # 3/7

        await seed.cleanup(db)
    await eng.dispose()


@skip_live
@pytest.mark.asyncio
async def test_pdc_agent_filter_scopes_funnel_and_ltv():
    """With agent_id set, the funnel + LTV scope to the agent's bound customers."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    seed = _Seed()
    async with Session() as db:
        await _seed_source_graph(db, seed, T=_T)
        svc = PrivateDomainConversionService(db)
        out = await svc.get_conversion(agent_id=seed.agent_id, account_id=seed.account_id,
                                       since=_SINCE, until=_UNTIL)
        f = out["funnel"]
        assert f["base_customers"] == 3, f
        assert f["reached_customers"] == 2, f   # c1,c2 (bound + outbound)
        assert f["interacted_customers"] == 2, f
        assert f["converted_customers"] == 3, f  # c1,c2,c3 won deals
        assert f["reach_rate_percent"] == pytest.approx(66.67, abs=0.01)  # 2/3

        ltv = out["ltv"]
        assert ltv["won_deal_count"] == 3, ltv
        assert ltv["total_won_value_cents"] == 18000, ltv
        assert ltv["ltv_proxy_cents_per_reached"] == 9000.0  # 18000/2

        # completion rates are account-scoped (by seed.account_id) + window
        assert out["nurture_execution"]["executed_attempts"] == 5
        assert out["follow_up"]["total"] == 7
        await seed.cleanup(db)
    await eng.dispose()


@skip_live
@pytest.mark.asyncio
async def test_pdc_account_filter_scopes_account_owned_sources():
    """With account_id set to a DIFFERENT (empty) account, the seeded
    account-owned sources do NOT count, isolating the account scoping."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    seed = _Seed()
    async with Session() as db:
        await _seed_source_graph(db, seed, T=_T)
        # A brand-new empty account (not the seeded one) has no messages/deals.
        from app.db.models.platform import Platform
        from app.db.models.account import Account
        empty_plat = Platform(code=f"p6an06-empty-{uuid4().hex[:8]}", name="p6an06-empty")
        db.add(empty_plat)
        await db.flush()
        empty_acct = Account(platform_id=empty_plat.id, name="p6an06-empty-acct")
        db.add(empty_acct)
        await db.flush()

        svc = PrivateDomainConversionService(db)
        out = await svc.get_conversion(agent_id=None, account_id=empty_acct.id,
                                       since=_SINCE, until=_UNTIL)
        f = out["funnel"]
        # no reached/interacted (no messages under the empty account)
        assert f["reached_customers"] == 0, f
        assert f["interacted_customers"] == 0
        assert f["converted_customers"] == 0
        assert out["ltv"]["won_deal_count"] == 0
        assert out["ltv"]["total_won_value_cents"] == 0
        assert out["nurture_execution"]["executed_attempts"] == 0
        assert out["follow_up"]["total"] == 0
        await db.execute(delete(Account).where(Account.id == empty_acct.id))
        await db.execute(delete(Platform).where(Platform.id == empty_plat.id))
        await db.commit()
        await seed.cleanup(db)
    await eng.dispose()


@skip_live
@pytest.mark.asyncio
async def test_pdc_window_excludes_out_of_window_rows():
    """An out-of-window won deal (created before ``since``) must not count."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    seed = _Seed()
    async with Session() as db:
        await _seed_source_graph(db, seed, T=_T, out_of_window_deal_value=500)
        svc = PrivateDomainConversionService(db)
        # Scope to the seeded account; the out-of-window deal is also under it.
        out = await svc.get_conversion(agent_id=seed.agent_id,
                                       account_id=seed.account_id,
                                       since=_SINCE, until=_UNTIL)
        # 3 in-window won deals (c1,c2,c3); the out-of-window 500-cents deal
        # (also c1) is EXCLUDED by the window bound.
        assert out["ltv"]["won_deal_count"] == 3, out["ltv"]
        assert out["ltv"]["total_won_value_cents"] == 18000  # 10000+5000+3000, NOT +500
        await seed.cleanup(db)
    await eng.dispose()


# --------------------------------------------------------------------------
# seed helper
# --------------------------------------------------------------------------
async def _seed_source_graph(db: AsyncSession, seed: _Seed, T: datetime,
                             out_of_window_deal_value: int = 0) -> None:
    """Seed the full Phase-5 private-domain source graph under one account.

    Layout (all created_at = T unless noted):
      customers c1..c5 (live) + c6 (soft-deleted, must be excluded)
      agent A bound to c1,c2,c3
      conversations: c1, c2, c5 (each customer-scoped)
      messages:
        c1 conv: out sent x2, in read x1, out failed x1, out queued x1
        c2 conv: out delivered x1, in read x1
        c5 conv: out sent x1  (created OUT-OF-WINDOW -> not reached)
      deals (pipeline under account A):
        c1 won 10000, c2 won 5000, c3 won 3000, c4 won 7000, + 1 lost (excluded)
        + optional out-of-window won deal (value = out_of_window_deal_value)
      nurture_step_execution (account A):
        success x2, failed x1, dead_letter x1, skipped x1, pending x1, running x1
      follow_up_task (account A):
        completed x3, pending x2, in_progress x1, cancelled x1
    """
    # Parent rows (need PKs for their children).
    plat = Platform(code=f"p6an06-{uuid4().hex[:8]}", name="p6an06-test")
    db.add(plat)
    await db.flush()

    acct = Account(platform_id=plat.id, name="p6an06-account")
    db.add(acct)
    await db.flush()
    seed.account_id = acct.id

    # --- customers ---
    cust = {}
    cust_objs = {}
    for n in ("c1", "c2", "c3", "c4", "c5"):
        c = Customer(name=f"p6an06-{n}")
        db.add(c)
        cust_objs[n] = c
    c6 = Customer(name="p6an06-c6")
    c6.is_deleted = True
    db.add(c6)
    await db.flush()  # customer PKs populate now
    for n in ("c1", "c2", "c3", "c4", "c5"):
        cust[n] = cust_objs[n].id
    seed.customers.update(cust)

    # --- agent + bindings (A -> c1,c2,c3) ---
    agent = Agent(name="p6an06-agent")
    db.add(agent)
    await db.flush()
    seed.agent_id = agent.id
    bindings = []
    for n in ("c1", "c2", "c3"):
        b = AgentCustomerBinding(agent_id=agent.id, customer_id=cust[n])
        db.add(b)
        bindings.append(b)

    # P6AN-16 tenancy wiring: the account owns the agent through
    # agent_persona_binding (account -> agent -> customer). Without this link
    # the caller's account has no visible agents/customers, so a tenant-scoped
    # read would be empty. Seed a minimal persona + binding so the tenancy
    # model (account -> agent -> customer) is faithfully represented.
    from app.db.models.account import AgentPersonaBinding
    from app.db.models.persona import Persona

    persona = Persona(name="p6an06-persona")
    db.add(persona)
    await db.flush()
    apb = AgentPersonaBinding(
        account_id=acct.id, agent_id=agent.id, persona_id=persona.id
    )
    db.add(apb)

    # --- conversations ---
    conv_objs = {}
    for n in ("c1", "c2", "c5"):
        cv = Conversation(customer_id=cust[n], channel="wechat",
                         subject=f"p6an06-{n}")
        db.add(cv)
        conv_objs[n] = cv

    # --- messages ---
    def _add_msg(convn, direction, status, created=T):
        m = ChannelMessage(
            conversation_id=conv_objs[convn].id,  # flushed below
            direction=direction, status=status,
            content={"text": "p6an06"}, created_at=created, updated_at=created,
            account_id=acct.id,
        )
        db.add(m)
        return m

    # flush conversations first so messages can reference their real ids
    await db.flush()
    msgs = [
        _add_msg("c1", "out", "sent"),
        _add_msg("c1", "out", "sent"),
        _add_msg("c1", "in", "read"),
        _add_msg("c1", "out", "failed"),     # not reached (failed)
        _add_msg("c1", "out", "queued"),      # not reached (not dispatched)
        _add_msg("c2", "out", "delivered"),
        _add_msg("c2", "in", "read"),
        _add_msg("c5", "out", "sent", created=_T_OUT),  # OUT-OF-WINDOW
    ]

    # --- deals ---
    pipe = DealPipeline(account_id=acct.id, name="p6an06-pipeline")
    db.add(pipe)
    await db.flush()
    deals = []

    def _make_deal(custn, status, value, created=T):
        d = DealItem(
            pipeline_id=pipe.id, account_id=acct.id, customer_id=cust[custn],
            status=status, value=value, currency="CNY",
            name=f"p6an06-deal-{custn}-{status}",
            created_at=created, updated_at=created,
        )
        db.add(d)
        deals.append(d)

    _make_deal("c1", "won", 10000)
    _make_deal("c2", "won", 5000)
    _make_deal("c3", "won", 3000)
    _make_deal("c4", "won", 7000)
    _make_deal("c1", "lost", 12000)     # lost -> excluded from won aggregate
    if out_of_window_deal_value:
        _make_deal("c1", "won", out_of_window_deal_value, created=_T_OUT)

    # --- nurture step executions ---
    nses = []
    for status in ("success", "success", "failed", "dead_letter", "skipped",
                   "pending", "running"):
        n = NurtureStepExecution(
            plan_id=uuid4(), account_id=acct.id, step_order=0, status=status,
            created_at=T, updated_at=T,
        )
        db.add(n)
        nses.append(n)

    # --- follow-up tasks ---
    fus = []
    for status in ("completed", "completed", "completed", "pending", "pending",
                   "in_progress", "cancelled"):
        t = FollowUpTask(
            account_id=acct.id, customer_id=cust["c1"], task_type="call",
            title="p6an06-fu", status=status, created_at=T, updated_at=T,
        )
        db.add(t)
        fus.append(t)

    # One final flush (every child PK populates), then record the real ids.
    await db.flush()
    seed.ids["platforms"].append(plat.id)
    seed.ids["accounts"].append(acct.id)
    seed.ids["customers"].extend(cust_objs[n].id for n in cust_objs)
    seed.ids["customers"].append(c6.id)
    seed.ids["agents"].append(agent.id)
    seed.ids["bindings"].extend(b.id for b in bindings)
    seed.ids["conversations"].extend(cv.id for cv in conv_objs.values())
    seed.ids["messages"].extend(m.id for m in msgs)
    seed.ids["pipelines"].append(pipe.id)
    seed.ids["deals"].extend(d.id for d in deals)
    seed.ids["nse"].extend(n.id for n in nses)
    seed.ids["fu"].extend(t.id for t in fus)
    await db.commit()
