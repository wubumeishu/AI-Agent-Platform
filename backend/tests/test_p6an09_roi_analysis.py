"""P6AN-09 ROI Analysis: 口径 + service + API + live-PG tests.

Three layers (mirrors the P6AN-06 repo conventions):

1. **Pure math layer** (no DB): the div-by-zero ROI guard, rate/rounding,
   the summary==Σitems invariant, and the cost-proxy input pricing — done at
   the ``assemble_*`` level so they run deterministically without Postgres.

2. **API layer** (TestClient, service patched): the ``dimension`` gate
   (unknown → 422), ISO window parsing (bad → 422, good → forwarded), UUID
   validation, and the default private-domain path.

3. **Live-PG 对拍 layer** (``ai_agent_platform_test``): seed the Phase-4/5
   source graph (customers, agent bindings, outbound messages, won deals,
   campaign leads + linked deals, nurture, follow-up), then 对拍 every
   revenue / input / ROI number against hand-computed expectations. Skipped
   cleanly when the test DB is unreachable.

The ROI口径 is documented in ``docs/P6AN-09-roi-analysis-api.md``.
"""
from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models.agent import Agent, AgentCustomerBinding
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.lead import Lead
from app.db.models.messages import ChannelMessage
from app.db.models.nurture_execution import NurtureStepExecution
from app.db.models.platform import Platform
from app.db.models.account import Account
from app.db.models.private_domain import DealItem, DealPipeline, FollowUpTask
from app.schemas.roi_analysis import ROIItem, ROIResponse
from app.services.roi_analysis import (
    DEFAULT_WINDOW_DAYS,
    DIMENSIONS,
    ROIService,
    _coerce_aware,
    _safe_div,
)

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:***@localhost:5432/ai_agent_platform_test"
_TEST_URL_ASYNCPG = "postgresql://postgres:***@localhost:5432/ai_agent_platform_test"


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
class TestSafeDiv:
    def test_safe_div_normal(self):
        assert _safe_div(100.0, 25.0) == 4.0

    def test_safe_div_rounds_four_decimals(self):
        assert _safe_div(1, 3) == 0.3333

    def test_safe_div_zero_denominator_returns_none(self):
        assert _safe_div(100.0, 0.0) is None

    def test_safe_div_zero_zero_returns_none(self):
        assert _safe_div(0.0, 0.0) is None


class TestCoerceAware:
    def test_naive_becomes_utc(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        aware = _coerce_aware(naive)
        assert aware.tzinfo is not None
        assert aware == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_none_passthrough(self):
        assert _coerce_aware(None) is None


_RATES_ZERO: Dict[str, int] = {
    "cost_per_outbound_message_cents": 0,
    "cost_per_nurture_execution_cents": 0,
    "cost_per_followup_task_cents": 0,
    "cost_per_active_agent_cents": 0,
    "cost_per_campaign_lead_cents": 0,
}
_RATES_SET: Dict[str, int] = {
    "cost_per_outbound_message_cents": 20,
    "cost_per_nurture_execution_cents": 50,
    "cost_per_followup_task_cents": 80,
    "cost_per_active_agent_cents": 1000,
    "cost_per_campaign_lead_cents": 300,
}


class TestAssemblePrivateDomain:
    def _svc(self):
        return ROIService(db=None)  # type: ignore[arg-type]

    def test_no_cost_basis_roi_is_none(self):
        """Zero rates → input 0 → roi/roi_percent None, net == revenue."""
        raw = {
            "won_deal_count": 3, "won_value_cents": 30000, "reached_customers": 2,
            "outbound_messages": 5, "nurture_executions": 4,
            "follow_up_tasks": 7, "active_agents": 3,
        }
        out = self._svc().assemble_private_domain(
            raw, dict(_RATES_ZERO),
            datetime.now(timezone.utc), datetime.now(timezone.utc), False,
            None, None, _filters("private-domain"),
        )
        assert out.cost_basis_configured is False
        s = out.summary
        assert s.revenue_cents == 30000
        assert s.input_cents == 0
        assert s.roi is None
        assert s.roi_percent is None
        assert s.net_cents == 30000  # revenue - 0
        # LTV proxy is auxiliary context: 30000 / 2
        assert s.ltv_proxy_cents_per_reached == 15000.0

    def test_configured_cost_computes_roi(self):
        """Set rates → input priced from activity volumes; ROI computed."""
        raw = {
            "won_deal_count": 3, "won_value_cents": 30000, "reached_customers": 2,
            "outbound_messages": 5, "nurture_executions": 4,
            "follow_up_tasks": 7, "active_agents": 3,
        }
        out = self._svc().assemble_private_domain(
            raw, dict(_RATES_SET),
            datetime.now(timezone.utc), datetime.now(timezone.utc), False,
            None, None, _filters("private-domain"),
        )
        assert out.cost_basis_configured is True
        s = out.summary
        # input = 5*20 + 4*50 + 7*80 + 3*1000 = 100 + 200 + 560 + 3000 = 3860
        assert s.input_cents == 3860, s.input_breakdown
        assert s.net_cents == 30000 - 3860
        # roi = (30000-3860)/3860 = 6.7720...
        assert s.roi == pytest.approx(round(26140 / 3860, 4), abs=1e-4)
        assert s.roi_percent == pytest.approx(round(26140 / 3860 * 100, 2), abs=0.01)
        # breakdown mirrors the per-source costs
        assert s.input_breakdown["active_agents"] == 3000
        assert s.input_breakdown["follow_up_tasks"] == 560

    def test_activity_zero_sources_omitted(self):
        """A zero-volume source is dropped from activity/breakdown."""
        raw = {
            "won_deal_count": 0, "won_value_cents": 0, "reached_customers": 0,
            "outbound_messages": 0, "nurture_executions": 2,
            "follow_up_tasks": 0, "active_agents": 1,
        }
        out = self._svc().assemble_private_domain(
            raw, dict(_RATES_SET),
            datetime.now(timezone.utc), datetime.now(timezone.utc), False,
            None, None, _filters("private-domain"),
        )
        assert "outbound_messages" not in out.summary.activity
        assert "follow_up_tasks" not in out.summary.activity
        assert out.summary.activity == {"nurture_executions": 2, "active_agents": 1}


class TestAssembleAgent:
    def _svc(self):
        return ROIService(db=None)  # type: ignore[arg-type]

    def _agent_raw(self):
        """Two agents: A1 (revenue 10000, 3 outbound msgs), A2 (revenue 0, 1 msg).

        revenue keyed by a real UUID; agents list carries the names.
        """
        a1, a2 = uuid4(), uuid4()
        raw = {
            "revenue": {a1: {"won_deal_count": 2, "won_value_cents": 10000},
                        a2: {"won_deal_count": 0, "won_value_cents": 0}},
            "outbound": {a1: 3, a2: 1},
            "agents": [{"agent_id": a1, "agent_name": "alpha"},
                       {"agent_id": a2, "agent_name": "beta"}],
        }
        return raw, a1, a2

    def test_summary_equals_sum_of_items(self):
        raw, a1, a2 = self._agent_raw()
        out = self._svc().assemble_agent(
            raw, dict(_RATES_SET),
            datetime.now(timezone.utc), datetime.now(timezone.utc), False,
            None, None, _filters("agent"),
        )
        assert out.dimension == "agent"
        assert len(out.items) == 2
        # summary revenue = sum of item revenues
        assert out.summary.revenue_cents == sum(i.revenue_cents for i in out.items)
        # summary input = sum of item inputs (3+1 outbound, 2 active agents)
        assert out.summary.input_cents == sum(i.input_cents for i in out.items)
        # summary input: outbound 4*20 + active 2*1000 = 80 + 2000 = 2080
        assert out.summary.input_cents == 2080, out.summary.input_breakdown

    def test_agent_filter_narrows_to_one(self):
        raw, a1, a2 = self._agent_raw()
        out = self._svc().assemble_agent(
            raw, dict(_RATES_SET),
            datetime.now(timezone.utc), datetime.now(timezone.utc), False,
            a1, None, _filters("agent"),
        )
        assert len(out.items) == 1
        assert out.items[0].entity_id == str(a1)
        # summary now equals the single item
        assert out.summary.revenue_cents == out.items[0].revenue_cents

    def test_zero_revenue_agent_still_listed(self):
        """An agent with no won deals still appears (zeroed), not dropped."""
        raw, a1, a2 = self._agent_raw()
        out = self._svc().assemble_agent(
            raw, dict(_RATES_SET),
            datetime.now(timezone.utc), datetime.now(timezone.utc), False,
            None, None, _filters("agent"),
        )
        by_id = {i.entity_id: i for i in out.items}
        assert by_id[str(a2)].revenue_cents == 0
        # zero revenue but non-zero input (its active-agent cost) → negative net
        assert by_id[str(a2)].net_cents < 0


class TestAssembleCampaign:
    def _svc(self):
        return ROIService(db=None)  # type: ignore[arg-type]

    def test_per_campaign_roi_and_summary(self):
        raw = {
            "campaigns": {"camp-A": 10, "camp-B": 4},
            "revenue": {
                "camp-A": {"won_deal_count": 2, "won_value_cents": 20000},
                "camp-B": {"won_deal_count": 0, "won_value_cents": 0},
            },
        }
        out = self._svc().assemble_campaign(
            raw, dict(_RATES_SET),
            datetime.now(timezone.utc), datetime.now(timezone.utc), False,
            None, None, _filters("campaign"),
        )
        assert out.dimension == "campaign"
        by_id = {i.entity_id: i for i in out.items}
        # camp-A: input = 10 leads * 300 = 3000; revenue 20000
        assert by_id["camp-A"].input_cents == 3000
        assert by_id["camp-A"].revenue_cents == 20000
        assert by_id["camp-A"].roi == pytest.approx(round(17000 / 3000, 4), abs=1e-4)
        # camp-B: input = 4*300 = 1200; revenue 0 → net -1200
        assert by_id["camp-B"].input_cents == 1200
        assert by_id["camp-B"].net_cents == -1200
        # summary: revenue 20000, input 4200
        assert out.summary.revenue_cents == 20000
        assert out.summary.input_cents == 4200
        assert out.summary.roi == pytest.approx(round(15800 / 4200, 4), abs=1e-4)


# --------------------------------------------------------------------------
# shared helper: a minimal ROIFilters for the pure assemble tests
# --------------------------------------------------------------------------
def _filters(dimension: str):
    from app.schemas.roi_analysis import ROIFilters

    return ROIFilters(
        dimension=dimension,
        since=datetime.now(timezone.utc),
        until=datetime.now(timezone.utc),
    )


# ==========================================================================
# 2) API layer (real HTTP path via TestClient, service patched)
# ==========================================================================
class _CapturedService:
    """Stand-in for the service the router instantiates so the HTTP test can
    assert the window/dimension were parsed + forwarded without a DB."""

    def __init__(self):
        self.calls: list = []

    async def get_roi(self, **kwargs):
        self.calls.append(kwargs)
        return ROIResponse(
            dimension=kwargs.get("dimension", "private-domain"),
            window={"since": _SINCE, "until": _UNTIL, "default_applied": False},
            filters={"dimension": kwargs.get("dimension", "private-domain")},
            cost_rates={},
            summary={},
            items=[],
        ).model_dump()


_SINCE = datetime(2026, 7, 1, tzinfo=timezone.utc)
_UNTIL = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _make_roi_app(captured: _CapturedService):
    from fastapi import FastAPI
    from app.db.session import get_db
    from app.routers.roi_analysis import router as roi_router

    app = FastAPI(title="P6AN-09 ROI-only app")
    app.include_router(roi_router)
    # P6AN-16: the analytics surface now requires an authenticated principal.
    # Functional tests exercise ROI behavior with a platform-wide admin
    # principal (no tenant scoping) to preserve the legacy unscoped semantics
    # (the captured service then receives account_id=None as before).
    from app.security.analytics_access import override_analytics_auth, test_principal
    override_analytics_auth(app, test_principal(role="admin"))
    app.dependency_overrides[get_db] = lambda: object()
    return app


class TestRoiApiLayer:
    def test_default_dimension_is_private_domain_200(self, monkeypatch):
        import app.routers.roi_analysis as mod
        captured = _CapturedService()
        app = _make_roi_app(captured)
        monkeypatch.setattr(mod, "ROIService", lambda db: captured)

        from fastapi.testclient import TestClient

        resp = TestClient(app).get("/api/v1/analytics/roi")
        assert resp.status_code == 200, resp.text
        assert captured.calls[0]["dimension"] == "private-domain"

    def test_each_dimension_forwarded(self, monkeypatch):
        import app.routers.roi_analysis as mod
        from fastapi.testclient import TestClient

        for dim in ("agent", "campaign", "private-domain"):
            captured = _CapturedService()
            app = _make_roi_app(captured)
            monkeypatch.setattr(mod, "ROIService", lambda db: captured)
            resp = TestClient(app).get("/api/v1/analytics/roi", params={"dimension": dim})
            assert resp.status_code == 200, (dim, resp.text)
            assert captured.calls[-1]["dimension"] == dim

    def test_unknown_dimension_422(self, monkeypatch):
        import app.routers.roi_analysis as mod
        captured = _CapturedService()
        app = _make_roi_app(captured)
        monkeypatch.setattr(mod, "ROIService", lambda db: captured)

        from fastapi.testclient import TestClient

        resp = TestClient(app).get(
            "/api/v1/analytics/roi", params={"dimension": "nonsense"},
        )
        assert resp.status_code == 422
        assert captured.calls == []  # rejected at the validation gate

    def test_malformed_since_422(self, monkeypatch):
        import app.routers.roi_analysis as mod
        captured = _CapturedService()
        app = _make_roi_app(captured)
        monkeypatch.setattr(mod, "ROIService", lambda db: captured)

        from fastapi.testclient import TestClient

        resp = TestClient(app).get(
            "/api/v1/analytics/roi",
            params={"dimension": "agent", "since": "not-a-date"},
        )
        assert resp.status_code == 422
        assert "Invalid ISO-8601" in resp.json()["detail"]
        assert captured.calls == []

    def test_bad_agent_uuid_422(self, monkeypatch):
        import app.routers.roi_analysis as mod
        captured = _CapturedService()
        app = _make_roi_app(captured)
        monkeypatch.setattr(mod, "ROIService", lambda db: captured)

        from fastapi.testclient import TestClient

        resp = TestClient(app).get(
            "/api/v1/analytics/roi",
            params={"dimension": "agent", "agent_id": "not-a-uuid"},
        )
        assert resp.status_code == 422
        assert captured.calls == []

    def test_iso_window_parsed_to_aware_datetime(self, monkeypatch):
        import app.routers.roi_analysis as mod
        captured = _CapturedService()
        app = _make_roi_app(captured)
        monkeypatch.setattr(mod, "ROIService", lambda db: captured)

        from fastapi.testclient import TestClient

        resp = TestClient(app).get(
            "/api/v1/analytics/roi",
            params={"dimension": "private-domain",
                    "since": "2026-07-01T00:00:00Z", "until": "2026-09-01T00:00:00Z"},
        )
        assert resp.status_code == 200, resp.text
        assert captured.calls[0]["since"] == datetime.fromisoformat("2026-07-01T00:00:00+00:00")
        assert captured.calls[0]["until"] == datetime.fromisoformat("2026-09-01T00:00:00+00:00")


# ==========================================================================
# 3) Live-PG 对拍 layer
# ==========================================================================
_T = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)          # in-window
_SINCE_W = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
_UNTIL_W = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Seed:
    """Holds the ids of everything the live tests create so teardown is precise."""

    def __init__(self):
        self.ids: dict[str, list] = {
            "messages": [], "conversations": [], "deals": [], "pipelines": [],
            "leads": [], "nse": [], "fu": [], "customers": [], "agents": [],
            "bindings": [], "accounts": [], "platforms": [],
        }
        self.customer_ids: Dict[str, UUID] = {}
        self.agent_id: Optional[UUID] = None
        self.account_id: Optional[UUID] = None
        self.campaign_lead_ids: Dict[str, List[UUID]] = {}
        self.campaign_a_id = f"p6an09-camp-{uuid4().hex[:8]}"
        self.campaign_b_id = f"p6an09-camp-{uuid4().hex[:8]}"

    def cleanup(self, db: AsyncSession):
        async def _run() -> None:
            pairs = [
                (ChannelMessage, "messages"),
                (Conversation, "conversations"),
                (DealItem, "deals"),
                (Lead, "leads"),
                (NurtureStepExecution, "nse"),
                (FollowUpTask, "fu"),
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


async def _seed_roi_graph(db: AsyncSession, seed: _Seed, T: datetime) -> None:
    """Seed the Phase-4/5 source graph the ROI report aggregates.

    Layout (created_at = T unless noted):
      account A (platform P)
      customers c1..c3 (live)
      agent AG bound to c1,c2,c3
      outbound messages (sent) under A: 5 total, all attributed to AG
      won deals (pipeline under A): c1=10000, c2=5000, c3=3000  (3 deals, 18000)
      campaign leads: camp-A -> 2 leads (one converted to a won deal),
                      camp-B -> 1 lead (no won deal)
      nurture_step_execution (A): 2 executed
      follow_up_task (A): 3
    """
    plat = Platform(code=f"p6an09-{uuid4().hex[:8]}", name="p6an09-test")
    db.add(plat)
    await db.flush()

    acct = Account(platform_id=plat.id, name="p6an09-account")
    db.add(acct)
    await db.flush()
    seed.account_id = acct.id

    cust_objs = {}
    for n in ("c1", "c2", "c3"):
        c = Customer(name=f"p6an09-{n}")
        db.add(c)
        cust_objs[n] = c
    await db.flush()
    for n in ("c1", "c2", "c3"):
        seed.customer_ids[n] = cust_objs[n].id
    seed.ids["customers"].extend(c.id for c in cust_objs.values())

    agent = Agent(name="p6an09-agent", status="active")
    db.add(agent)
    await db.flush()
    seed.agent_id = agent.id
    seed.ids["agents"].append(agent.id)
    bindings = []
    for n in ("c1", "c2", "c3"):
        b = AgentCustomerBinding(agent_id=agent.id, customer_id=seed.customer_ids[n])
        db.add(b)
        bindings.append(b)

    # Conversations per customer (the message FK target must be a real row).
    conv_objs = {}
    for n in ("c1", "c2", "c3"):
        cv = Conversation(customer_id=seed.customer_ids[n], channel="wechat",
                         subject=f"p6an09-{n}")
        db.add(cv)
        conv_objs[n] = cv
    await db.flush()
    for n in conv_objs:
        seed.ids["conversations"].append(conv_objs[n].id)

    # Outbound messages under the account, attributed to the agent (5 total).
    # c1 carries 3, c2 carries 2.
    msgs = []
    conv_spread = ("c1", "c1", "c1", "c2", "c2")
    for i, cn in enumerate(conv_spread):
        m = ChannelMessage(
            conversation_id=conv_objs[cn].id,
            direction="out", status="sent",
            content={"text": "p6an09"}, created_at=T, updated_at=T,
            account_id=acct.id, agent_id=agent.id,
        )
        db.add(m)
        msgs.append(m)

    # Won deals under the account.
    pipe = DealPipeline(account_id=acct.id, name="p6an09-pipeline")
    db.add(pipe)
    await db.flush()
    deals = []
    for cust_n, value in (("c1", 10000), ("c2", 5000), ("c3", 3000)):
        d = DealItem(
            pipeline_id=pipe.id, account_id=acct.id,
            customer_id=seed.customer_ids[cust_n],
            status="won", value=value, currency="CNY",
            name=f"p6an09-deal-{cust_n}",
            created_at=T, updated_at=T,
        )
        db.add(d)
        deals.append(d)

    # Campaign leads: camp-A -> 2 leads, camp-B -> 1 lead.
    camp_leads: Dict[str, List[Lead]] = {
        seed.campaign_a_id: [],
        seed.campaign_b_id: [],
    }
    lead_rows = [
        (seed.campaign_a_id, "c1"),
        (seed.campaign_a_id, "c2"),
        (seed.campaign_b_id, "c3"),
    ]
    # The two camp-A leads are the "won" ones (their deals linked by lead_id).
    for i, (camp, cust_n) in enumerate(lead_rows):
        l = Lead(
            customer_id=seed.customer_ids[cust_n],
            source_type="campaign",
            source_id=camp,
            status="new",
            notes=f"p6an09-lead-{i}",
            created_at=_naive(T),
            updated_at=_naive(T),
        )
        db.add(l)
        camp_leads[camp].append(l)
    await db.flush()
    for camp in camp_leads:
        seed.ids["leads"].extend(l.id for l in camp_leads[camp])
    # camp-A's 2 leads are the converted ones; link their won deals to them.
    camp_a_leads = camp_leads[seed.campaign_a_id]
    # Deal[0] (c1, 10000) and Deal[1] (c2, 5000) -> link to camp-A leads 0 & 1.
    deals[0].lead_id = camp_a_leads[0].id
    deals[1].lead_id = camp_a_leads[1].id
    seed.campaign_lead_ids["camp-A"] = [l.id for l in camp_a_leads]
    seed.campaign_lead_ids["camp-B"] = [l.id for l in camp_leads[seed.campaign_b_id]]

    # Nurture executions (2 executed) + follow-up tasks (3), all under A.
    nses = []
    for status in ("success", "success"):
        n = NurtureStepExecution(
            plan_id=uuid4(), account_id=acct.id, step_order=0, status=status,
            created_at=T, updated_at=T,
        )
        db.add(n)
        nses.append(n)
    fus = []
    for _ in range(3):
        t = FollowUpTask(
            account_id=acct.id, customer_id=seed.customer_ids["c1"],
            task_type="call", title="p6an09-fu", status="pending",
            created_at=T, updated_at=T,
        )
        db.add(t)
        fus.append(t)

    # One final flush populates every remaining child PK; record the real ids.
    await db.flush()
    seed.ids["platforms"].append(plat.id)
    seed.ids["accounts"].append(acct.id)
    seed.ids["bindings"].extend(b.id for b in bindings)
    seed.ids["messages"].extend(m.id for m in msgs)
    seed.ids["pipelines"].append(pipe.id)
    seed.ids["deals"].extend(d.id for d in deals)
    seed.ids["nse"].extend(n.id for n in nses)
    seed.ids["fu"].extend(t.id for t in fus)
    await db.commit()


def _naive(dt: datetime) -> datetime:
    """Naive-UTC wall clock for the naive-timestamp lead columns."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


@skip_live
@pytest.mark.asyncio
async def test_roi_private_domain_live():
    """Private-domain 对拍: revenue = total won value; input priced from the
    seeded activity volumes; ROI computed against the configured rates."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    seed = _Seed()
    async with Session() as db:
        await _seed_roi_graph(db, seed, T=_T)
        rates = {
            "cost_per_outbound_message_cents": 20,
            "cost_per_nurture_execution_cents": 50,
            "cost_per_followup_task_cents": 80,
            "cost_per_active_agent_cents": 0,   # keep agent overhead out here
            "cost_per_campaign_lead_cents": 0,
        }
        svc = ROIService(db)
        out = await svc.get_roi(
            dimension="private-domain",
            account_id=seed.account_id,
            since=_SINCE_W, until=_UNTIL_W,
            rates=rates,
        )
        s = out.summary
        # revenue = 3 won deals = 10000 + 5000 + 3000 = 18000
        assert s.revenue_cents == 18000, s
        assert s.won_deal_count == 3
        # input = outbound 5*20 + nurture 2*50 + followup 3*80 = 100 + 100 + 240 = 440
        assert s.input_cents == 440, s.input_breakdown
        assert s.net_cents == 18000 - 440
        assert s.roi == pytest.approx(round(17560 / 440, 4), abs=1e-4)
        assert s.roi_percent == pytest.approx(round(17560 / 440 * 100, 2), abs=0.01)
        await seed.cleanup(db)
    await eng.dispose()


@skip_live
@pytest.mark.asyncio
async def test_roi_agent_dimension_live():
    """Agent dimension: the seeded agent's revenue + its outbound volume."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    seed = _Seed()
    async with Session() as db:
        await _seed_roi_graph(db, seed, T=_T)
        rates = dict(_RATES_SET)  # full table incl. active-agent cost
        svc = ROIService(db)
        out = await svc.get_roi(
            dimension="agent",
            agent_id=seed.agent_id,
            since=_SINCE_W, until=_UNTIL_W,
            rates=rates,
        )
        assert out.dimension == "agent"
        assert len(out.items) == 1
        item = out.items[0]
        # This agent's bound customers own all 3 won deals (18000).
        assert item.revenue_cents == 18000, item
        # input = outbound 5*20 + active_agents 1*1000 = 100 + 1000 = 1100
        assert item.input_cents == 1100, item.input_breakdown
        assert item.net_cents == 18000 - 1100
        # summary mirrors the single filtered item
        assert out.summary.revenue_cents == 18000
        assert out.summary.input_cents == 1100
        await seed.cleanup(db)
    await eng.dispose()


@skip_live
@pytest.mark.asyncio
async def test_roi_campaign_dimension_live():
    """Campaign dimension: camp-A converted (won deals linked by lead_id),
    camp-B open (no revenue). 对拍 both items + the summary."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    seed = _Seed()
    async with Session() as db:
        await _seed_roi_graph(db, seed, T=_T)
        rates = {k: 0 for k in _RATES_SET}
        rates["cost_per_campaign_lead_cents"] = 300
        svc = ROIService(db)
        out = await svc.get_roi(
            dimension="campaign",
            since=_SINCE_W, until=_UNTIL_W,
            rates=rates,
        )
        assert out.dimension == "campaign"
        by_id = {i.entity_id: i for i in out.items}
        # camp-A: 2 leads, revenue = deals[0]+deals[1] = 10000 + 5000 = 15000
        assert by_id[seed.campaign_a_id].revenue_cents == 15000
        assert by_id[seed.campaign_a_id].input_cents == 2 * 300
        # camp-B: 1 lead, no won revenue
        assert by_id[seed.campaign_b_id].revenue_cents == 0
        assert by_id[seed.campaign_b_id].input_cents == 1 * 300
        # summary invariant: summary == Σ items (output AND input sides). This
        # holds regardless of any pre-existing campaign leads in the shared DB,
        # because my seeded campaigns carry unique source_ids.
        assert out.summary.revenue_cents == sum(i.revenue_cents for i in out.items)
        assert out.summary.input_cents == sum(i.input_cents for i in out.items)
        assert out.summary.net_cents == out.summary.revenue_cents - out.summary.input_cents
        # my two campaigns together: revenue 15000, input 900
        assert by_id[seed.campaign_a_id].revenue_cents + by_id[seed.campaign_b_id].revenue_cents == 15000
        await seed.cleanup(db)
    await eng.dispose()


@skip_live
@pytest.mark.asyncio
async def test_roi_no_cost_basis_live():
    """With all rates zero, input = 0 → roi is None (safe div-by-zero), and
    net_cents still reports the revenue. This is the 分母为0 acceptance case."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    seed = _Seed()
    async with Session() as db:
        await _seed_roi_graph(db, seed, T=_T)
        svc = ROIService(db)
        out = await svc.get_roi(
            dimension="private-domain",
            account_id=seed.account_id,
            since=_SINCE_W, until=_UNTIL_W,
            rates={k: 0 for k in _RATES_SET},
        )
        s = out.summary
        assert out.cost_basis_configured is False
        assert s.input_cents == 0
        assert s.roi is None
        assert s.roi_percent is None
        assert s.revenue_cents == 18000
        assert s.net_cents == 18000
        await seed.cleanup(db)
    await eng.dispose()
