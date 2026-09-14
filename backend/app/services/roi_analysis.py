"""ROI Analysis service (Phase 6 / P6AN-09).

Computes 投入产出 (input/output) ROI across three dimensions:

- ``agent``          — per-agent ROI (revenue attributed via
  ``agent_customer_binding``; input = the agent's outbound message volume +
  its own operational cost).
- ``campaign``       — per-campaign ROI (a *campaign* is a distinct
  ``lead.source_id`` where ``lead.source_type == 'campaign'``; revenue via the
  ``deal_item.lead_id`` link; input = the campaign's lead-acquisition volume).
- ``private-domain`` — a single account-scoped aggregate (input = private-domain
  operating activity: outbound messages + nurture executions + follow-up tasks
  + active-agent overhead).

Layering (API → Service → DB) mirrors P6AN-06 so the two concerns stay decoupled:

- :meth:`ROIService.collect_raw` runs a small set of focused, 对拍-able
  aggregate queries and returns a flat raw dict (per-dimension).
- :meth:`ROIService.assemble` is a *pure* function of the raw dict + the
  cost-proxy rates + the effective window: it turns raw numbers into the
  ``ROIResponse``. The div-by-zero guard (input == 0 → ROI ``None``), the
  rounding, and the ``summary == Σ items`` invariant all live here so they are
  unit-testable with no database.

Caliber (full doc: ``docs/P6AN-09-roi-analysis-api.md``)
---------------------------------------------------------
- **Output** = total won-deal value (``deal_item.value``, cents, status
  ``won``) created in the window. This is the 成交额 basis.
  ``ltv_proxy_cents_per_reached`` (value ÷ distinct reached customers) is
  carried as *auxiliary context* only — it is **not** the ROI output basis.
- **Input** = an operations **cost proxy** = Σ(volume × per-unit rate) over the
  dimension's observable activity. No finance system is wired up yet (out of
  scope this wave), so the per-unit rates are the only knobs; they are
  env-configurable (see ``app.config.roi_cost_rates``) and default to 0.
- **ROI** = ``(output − input) / input``. When ``input == 0`` the ratio is
  *undefined*, not ``0``: ``roi`` / ``roi_percent`` are ``None`` and
  ``net_cents`` still reports ``output − input``.
- ``summary`` for the grouped dimensions (agent / campaign) is the aggregate
  over the reported items, so the ``summary == Σ items`` invariant holds; for
  the single-aggregate dimension (private-domain) ``summary`` IS the whole
  answer and ``items`` is empty.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent, AgentCustomerBinding
from app.db.models.conversation import Conversation
from app.db.models.lead import Lead
from app.db.models.messages import ChannelMessage
from app.db.models.nurture_execution import NurtureStepExecution
from app.db.models.private_domain import DealItem, FollowUpTask
from app.schemas.roi_analysis import (
    ROIItem,
    ROICostRates,
    ROIResponse,
    ROIValue,
    ROIWindow,
    ROIFilters,
)

logger = logging.getLogger(__name__)

#: Delivery states that mean an outbound message actually reached the customer.
#: Mirrors P6AN-06: ``queued`` (not dispatched) and ``failed`` (never reached)
#: are excluded from the "reached" population.
_REACHED_MESSAGE_STATUSES = ("sent", "delivered", "read")

#: Default window (days) applied when the caller supplies no since/until.
DEFAULT_WINDOW_DAYS = 30

#: lead.source_type value that marks a lead as campaign-sourced (P6AN-09 口径).
CAMPAIGN_SOURCE = "campaign"

#: lead lifecycle code meaning "deal closed / won".
_WON_STAGE_CODE = "成交"

#: The five input (cost-proxy) sources, keyed the same as
#: ``config.roi_cost_rates()`` / :class:`ROICostRates`.
_ROI_RATE_KEYS: tuple[str, ...] = (
    "cost_per_outbound_message_cents",
    "cost_per_nurture_execution_cents",
    "cost_per_followup_task_cents",
    "cost_per_active_agent_cents",
    "cost_per_campaign_lead_cents",
)

#: Dimensions accepted by the endpoint.
DIMENSIONS = ("agent", "campaign", "private-domain")


def _safe_div(numerator: float, denominator: float) -> Optional[float]:
    """``numerator / denominator`` rounded to 4 decimals; ``None`` when the
    denominator is 0 — the ROI div-by-zero guard (undefined, not 0%). Pure."""
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def _coerce_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Attach UTC to a naive datetime (query params may arrive naive)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Strip tzinfo to a naive-UTC wall clock (for naive-timestamp columns like
    ``lead.created_at`` — exact for aware-UTC inputs). Mirrors P6AN-07."""
    return dt.replace(tzinfo=None) if dt is not None else None


class ROIService:
    """Computes the three-dimension ROI report. Depends only on an
    ``AsyncSession`` so it is testable against a live PG test DB (SQL layer)
    or via the pure ``assemble`` (math layer)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # window resolution (same convention as P6AN-06)
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_window(
        since: Optional[datetime], until: Optional[datetime]
    ) -> tuple[datetime, datetime, bool]:
        """Return ``(since, until, default_applied)`` with an effective window.

        - both given  -> use as-is (aware-UTC normalised)
        - only since  -> until = since + DEFAULT_WINDOW_DAYS
        - only until  -> since = until - DEFAULT_WINDOW_DAYS
        - neither     -> until = now, since = now - DEFAULT_WINDOW_DAYS (default)
        """
        since = _coerce_aware(since)
        until = _coerce_aware(until)
        default_span = timedelta(days=DEFAULT_WINDOW_DAYS)
        if since is not None and until is not None:
            return since, until, False
        if since is not None:
            return since, since + default_span, False
        if until is not None:
            return until - default_span, until, False
        now = datetime.now(timezone.utc)
        return now - default_span, now, True

    @staticmethod
    def _rates(rates: Optional[Dict[str, int]]) -> Dict[str, int]:
        """Normalise the rate table (fill missing keys with 0, clamp to >=0)."""
        rates = rates or {}
        out: Dict[str, int] = {}
        for k in _ROI_RATE_KEYS:
            v = rates.get(k, 0)
            out[k] = max(0, int(v)) if v is not None else 0
        return out

    @staticmethod
    def _cost_basis_configured(rates: Dict[str, int]) -> bool:
        return any(rates.get(k, 0) > 0 for k in _ROI_RATE_KEYS)

    # ------------------------------------------------------------------
    # raw aggregate collection (the SQL / 对拍-able layer)
    # ------------------------------------------------------------------
    async def collect_raw_private_domain(
        self, account_id: Optional[UUID], since: datetime, until: datetime
    ) -> Dict[str, Any]:
        """Private-domain (account-scoped) raw volumes + revenue."""
        db = self.db
        raw: Dict[str, Any] = {}

        # ---- revenue: total won-deal value (account-scoped) ----
        q = select(
            func.count(DealItem.id),
            func.coalesce(func.sum(DealItem.value), 0),
        ).where(
            DealItem.is_deleted.is_(False),
            DealItem.status == "won",
            DealItem.created_at >= since,
            DealItem.created_at < until,
        )
        if account_id is not None:
            q = q.where(DealItem.account_id == account_id)
        row = (await db.execute(q)).one()
        raw["won_deal_count"] = int(row[0] or 0)
        raw["won_value_cents"] = int(row[1] or 0)

        # ---- reached customers (aux LTV-proxy denominator, account-scoped) ----
        raw["reached_customers"] = await self._reached_customers(
            None, account_id, since, until
        )

        # ---- input volumes ----
        raw["outbound_messages"] = await self._outbound_messages(
            agent_id=None, account_id=account_id, since=since, until=until
        )
        raw["nurture_executions"] = await self._nurture_executions(
            account_id=account_id, since=since, until=until
        )
        raw["follow_up_tasks"] = await self._follow_up_tasks(
            account_id=account_id, since=since, until=until
        )
        raw["active_agents"] = await self._active_agents()
        return raw

    async def collect_raw_agent(
        self, since: datetime, until: datetime
    ) -> Dict[str, Any]:
        """Per-agent raw volumes + revenue (grouped by agent)."""
        db = self.db
        # (1) won revenue per agent via bound customers.
        bound = (
            select(AgentCustomerBinding.agent_id, AgentCustomerBinding.customer_id)
            .where(AgentCustomerBinding.is_deleted.is_(False))
            .subquery()
        )
        rev_q = (
            select(
                bound.c.agent_id,
                func.count(DealItem.id).label("n"),
                func.coalesce(func.sum(DealItem.value), 0).label("v"),
            )
            .join(
                bound,
                and_(
                    DealItem.customer_id == bound.c.customer_id,
                    DealItem.is_deleted.is_(False),
                ),
            )
            .where(
                DealItem.status == "won",
                DealItem.created_at >= since,
                DealItem.created_at < until,
            )
            .group_by(bound.c.agent_id)
        )
        revenue: Dict[UUID, Dict[str, int]] = {}
        for r in (await db.execute(rev_q)).all():
            if r.agent_id is None:
                continue
            revenue.setdefault(r.agent_id, {})["won_deal_count"] = int(r.n or 0)
            revenue[r.agent_id]["won_value_cents"] = int(r.v or 0)

        # (2) outbound messages per agent (direct attribution via msg.agent_id).
        msg_q = (
            select(
                ChannelMessage.agent_id,
                func.count(ChannelMessage.id).label("n"),
            )
            .where(
                ChannelMessage.is_deleted.is_(False),
                ChannelMessage.agent_id.is_not(None),
                ChannelMessage.direction == "out",
                ChannelMessage.status.in_(_REACHED_MESSAGE_STATUSES),
                ChannelMessage.created_at >= since,
                ChannelMessage.created_at < until,
            )
            .group_by(ChannelMessage.agent_id)
        )
        msgs: Dict[UUID, int] = {}
        for r in (await db.execute(msg_q)).all():
            msgs[r.agent_id] = int(r.n or 0)

        # (3) the set of live agents (so a zero-activity agent still appears).
        agents = list((await db.execute(select(Agent.id, Agent.name).where(
            Agent.is_deleted.is_(False)))).all())

        return {
            "revenue": revenue,
            "outbound": msgs,
            "agents": [
                {"agent_id": a.id, "agent_name": a.name} for a in agents
            ],
        }

    async def collect_raw_campaign(
        self, since: datetime, until: datetime
    ) -> Dict[str, Any]:
        """Per-campaign raw volumes + revenue (grouped by lead source_id).

        A *campaign* is a distinct ``lead.source_id`` among live leads with
        ``source_type == 'campaign'``. Revenue is the won value of the deals
        linked to that campaign's leads (``deal_item.lead_id``).
        """
        db = self.db
        # (1) distinct campaigns + their lead counts (naive-timestamp window).
        lead_since, lead_until = _naive_utc(since), _naive_utc(until)
        camp_q = (
            select(
                Lead.source_id,
                func.count(Lead.id).label("n"),
            )
            .where(
                Lead.is_deleted.is_(False),
                Lead.source_type == CAMPAIGN_SOURCE,
                Lead.source_id.is_not(None),
                Lead.created_at >= lead_since,
                Lead.created_at < lead_until,
            )
            .group_by(Lead.source_id)
        )
        campaigns: Dict[str, int] = {}
        for r in (await db.execute(camp_q)).all():
            campaigns[str(r.source_id)] = int(r.n or 0)

        # (2) per-campaign campaign-lead ids (for the revenue link).
        ids_by_campaign: Dict[str, List[UUID]] = {}
        for sid in campaigns:
            lead_ids_q = select(Lead.id).where(
                Lead.is_deleted.is_(False),
                Lead.source_type == CAMPAIGN_SOURCE,
                Lead.source_id == sid,
                Lead.created_at >= lead_since,
                Lead.created_at < lead_until,
            )
            ids_by_campaign[sid] = list((await db.execute(lead_ids_q)).scalars().all())

        # (3) won revenue per campaign via deal_item.lead_id IN (...).
        revenue: Dict[str, Dict[str, int]] = {}
        for sid, lead_ids in ids_by_campaign.items():
            if not lead_ids:
                revenue[sid] = {"won_deal_count": 0, "won_value_cents": 0}
                continue
            rev_q = (
                select(func.count(DealItem.id), func.coalesce(func.sum(DealItem.value), 0))
                .where(
                    DealItem.is_deleted.is_(False),
                    DealItem.status == "won",
                    DealItem.lead_id.in_(lead_ids),
                    DealItem.created_at >= since,
                    DealItem.created_at < until,
                )
            )
            row = (await db.execute(rev_q)).one()
            revenue[sid] = {"won_deal_count": int(row[0] or 0), "won_value_cents": int(row[1] or 0)}

        return {"campaigns": campaigns, "revenue": revenue}

    # ---- helpers: scoped input-volume + reached aggregates ----
    async def _reached_customers(
        self,
        agent_id: Optional[UUID],
        account_id: Optional[UUID],
        since: datetime,
        until: datetime,
    ) -> int:
        """Distinct customers with ≥1 successful outbound message in window."""
        q = (
            select(func.count(func.distinct(Conversation.customer_id)))
            .select_from(ChannelMessage)
            .join(Conversation, Conversation.id == ChannelMessage.conversation_id)
            .where(
                ChannelMessage.is_deleted.is_(False),
                Conversation.is_deleted.is_(False),
                Conversation.customer_id.is_not(None),
                ChannelMessage.direction == "out",
                ChannelMessage.status.in_(_REACHED_MESSAGE_STATUSES),
                ChannelMessage.created_at >= since,
                ChannelMessage.created_at < until,
            )
        )
        if account_id is not None:
            q = q.where(ChannelMessage.account_id == account_id)
        if agent_id is not None:
            bound = (
                select(AgentCustomerBinding.customer_id)
                .where(AgentCustomerBinding.is_deleted.is_(False),
                       AgentCustomerBinding.agent_id == agent_id)
                .subquery()
            )
            q = q.where(Conversation.customer_id.in_(select(bound)))
        return int((await self.db.execute(q)).scalar() or 0)

    async def _outbound_messages(
        self,
        agent_id: Optional[UUID],
        account_id: Optional[UUID],
        since: datetime,
        until: datetime,
    ) -> int:
        """Count of successful outbound messages in window (input volume)."""
        q = select(func.count(ChannelMessage.id)).where(
            ChannelMessage.is_deleted.is_(False),
            ChannelMessage.direction == "out",
            ChannelMessage.status.in_(_REACHED_MESSAGE_STATUSES),
            ChannelMessage.created_at >= since,
            ChannelMessage.created_at < until,
        )
        if account_id is not None:
            q = q.where(ChannelMessage.account_id == account_id)
        if agent_id is not None:
            q = q.where(ChannelMessage.agent_id == agent_id)
        return int((await self.db.execute(q)).scalar() or 0)

    async def _nurture_executions(
        self, account_id: Optional[UUID], since: datetime, until: datetime
    ) -> int:
        """Count of *executed* nurture step attempts in window (input volume).

        Mirrors P6AN-06: an "executed" attempt is any status other than
        pending/running. Scoped by ``account_id`` (step rows have no agent
        link), so the agent dimension does not count these.
        """
        q = select(func.count(NurtureStepExecution.id)).where(
            NurtureStepExecution.is_deleted.is_(False),
            NurtureStepExecution.created_at >= since,
            NurtureStepExecution.created_at < until,
        )
        if account_id is not None:
            q = q.where(NurtureStepExecution.account_id == account_id)
        return int((await self.db.execute(q)).scalar() or 0)

    async def _follow_up_tasks(
        self, account_id: Optional[UUID], since: datetime, until: datetime
    ) -> int:
        """Count of follow-up tasks created in window (input volume)."""
        q = select(func.count(FollowUpTask.id)).where(
            FollowUpTask.is_deleted.is_(False),
            FollowUpTask.created_at >= since,
            FollowUpTask.created_at < until,
        )
        if account_id is not None:
            q = q.where(FollowUpTask.account_id == account_id)
        return int((await self.db.execute(q)).scalar() or 0)

    async def _active_agents(self) -> int:
        """Current count of live active agents (operational-overhead proxy)."""
        q = select(func.count(Agent.id)).where(
            Agent.is_deleted.is_(False), Agent.status == "active"
        )
        return int((await self.db.execute(q)).scalar() or 0)

    # ------------------------------------------------------------------
    # pure assembly (the math / rounding / div-by-zero layer)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_value(
        revenue: int,
        won_deal_count: int,
        reached_customers: int,
        input_terms: Dict[str, int],
        rates: Dict[str, int],
    ) -> ROIValue:
        """Turn raw revenue + input volumes + rates into one :class:`ROIValue`.

        ``input_terms`` maps a source name (e.g. ``outbound_messages``) to its
        volume; the per-source cost is volume × the matching rate.
        """
        volume_by_source: Dict[str, int] = {
            "outbound_messages": "cost_per_outbound_message_cents",
            "nurture_executions": "cost_per_nurture_execution_cents",
            "follow_up_tasks": "cost_per_followup_task_cents",
            "active_agents": "cost_per_active_agent_cents",
            "campaign_leads": "cost_per_campaign_lead_cents",
        }
        activity: Dict[str, int] = {}
        breakdown: Dict[str, int] = {}
        total_input = 0
        for source, vol in input_terms.items():
            vol = int(vol or 0)
            if vol <= 0:
                continue
            rate_key = volume_by_source.get(source, source)
            rate = int(rates.get(rate_key, 0))
            activity[source] = vol
            cost = vol * rate
            breakdown[source] = cost
            total_input += cost

        net = revenue - total_input
        roi = _safe_div(float(revenue - total_input), float(total_input))
        roi_pct = round(roi * 100.0, 2) if roi is not None else None
        ltv_proxy = round(revenue / reached_customers, 2) if reached_customers else 0.0

        return ROIValue(
            revenue_cents=revenue,
            won_deal_count=won_deal_count,
            input_cents=total_input,
            net_cents=net,
            roi=roi,
            roi_percent=roi_pct,
            ltv_proxy_cents_per_reached=ltv_proxy,
            reached_customers=reached_customers,
            activity=activity,
            input_breakdown=breakdown,
        )

    @staticmethod
    def assemble_private_domain(
        raw: Dict[str, Any],
        rates: Dict[str, int],
        since: datetime,
        until: datetime,
        default_applied: bool,
        agent_id: Optional[UUID],
        account_id: Optional[UUID],
        filters: ROIFilters,
    ) -> ROIResponse:
        """Private-domain single aggregate (no items)."""
        value = ROIService._build_value(
            revenue=int(raw.get("won_value_cents", 0)),
            won_deal_count=int(raw.get("won_deal_count", 0)),
            reached_customers=int(raw.get("reached_customers", 0)),
            input_terms={
                "outbound_messages": raw.get("outbound_messages", 0),
                "nurture_executions": raw.get("nurture_executions", 0),
                "follow_up_tasks": raw.get("follow_up_tasks", 0),
                "active_agents": raw.get("active_agents", 0),
            },
            rates=rates,
        )
        return ROIResponse(
            dimension="private-domain",
            window=ROIWindow(since=since, until=until, default_applied=default_applied),
            filters=filters,
            cost_rates=ROICostRates(
                cost_per_outbound_message_cents=rates.get("cost_per_outbound_message_cents", 0),
                cost_per_nurture_execution_cents=rates.get("cost_per_nurture_execution_cents", 0),
                cost_per_followup_task_cents=rates.get("cost_per_followup_task_cents", 0),
                cost_per_active_agent_cents=rates.get("cost_per_active_agent_cents", 0),
                cost_per_campaign_lead_cents=rates.get("cost_per_campaign_lead_cents", 0),
                configured=ROIService._cost_basis_configured(rates),
            ),
            cost_basis_configured=ROIService._cost_basis_configured(rates),
            summary=value,
            items=[],
        )

    @staticmethod
    def assemble_agent(
        raw: Dict[str, Any],
        rates: Dict[str, int],
        since: datetime,
        until: datetime,
        default_applied: bool,
        agent_id: Optional[UUID],
        account_id: Optional[UUID],
        filters: ROIFilters,
    ) -> ROIResponse:
        """Per-agent grouped report; summary aggregates all items.

        Each item's input = its own outbound-message volume + one active-agent
        operational-cost unit. The summary re-prices the *summed* activity
        volumes across all items, so ``summary == Σ items`` holds on both the
        output and the input side (the P6AN-09 invariant).
        """
        revenue = raw.get("revenue", {})
        outbound = raw.get("outbound", {})
        agents = raw.get("agents", [])

        items: List[ROIItem] = []
        for a in agents:
            aid = a["agent_id"]
            # An optional agent_id filter narrows the report to that agent.
            if agent_id is not None and aid != agent_id:
                continue
            cell = revenue.get(aid, {})
            item = ROIItem(
                entity_id=str(aid),
                entity_label=a.get("agent_name"),
                **ROIService._build_value(
                    revenue=int(cell.get("won_value_cents", 0)),
                    won_deal_count=int(cell.get("won_deal_count", 0)),
                    reached_customers=0,  # LTV proxy not attributed per agent here
                    input_terms={
                        "outbound_messages": outbound.get(aid, 0),
                        "active_agents": 1,  # this agent's own operational cost
                    },
                    rates=rates,
                ).model_dump(),
            )
            items.append(item)

        # Deterministic ordering: by roi (None last), then revenue desc, then name.
        items.sort(
            key=lambda i: (i.roi is None, -(i.revenue_cents or 0), i.entity_label or ""),
        )

        # Summary = re-price the summed activity volumes (output + input both).
        summary_terms: Dict[str, int] = {}
        for i in items:
            for src, vol in i.activity.items():
                summary_terms[src] = summary_terms.get(src, 0) + vol
        summary = ROIService._build_value(
            revenue=sum(i.revenue_cents for i in items),
            won_deal_count=sum(i.won_deal_count for i in items),
            reached_customers=0,
            input_terms=summary_terms,
            rates=rates,
        )

        return ROIResponse(
            dimension="agent",
            window=ROIWindow(since=since, until=until, default_applied=default_applied),
            filters=filters,
            cost_rates=ROICostRates(
                cost_per_outbound_message_cents=rates.get("cost_per_outbound_message_cents", 0),
                cost_per_nurture_execution_cents=rates.get("cost_per_nurture_execution_cents", 0),
                cost_per_followup_task_cents=rates.get("cost_per_followup_task_cents", 0),
                cost_per_active_agent_cents=rates.get("cost_per_active_agent_cents", 0),
                cost_per_campaign_lead_cents=rates.get("cost_per_campaign_lead_cents", 0),
                configured=ROIService._cost_basis_configured(rates),
            ),
            cost_basis_configured=ROIService._cost_basis_configured(rates),
            summary=summary,
            items=items,
        )

    @staticmethod
    def assemble_campaign(
        raw: Dict[str, Any],
        rates: Dict[str, int],
        since: datetime,
        until: datetime,
        default_applied: bool,
        agent_id: Optional[UUID],
        account_id: Optional[UUID],
        filters: ROIFilters,
    ) -> ROIResponse:
        """Per-campaign grouped report; summary aggregates all items."""
        campaigns = raw.get("campaigns", {})
        revenue = raw.get("revenue", {})

        items: List[ROIItem] = []
        for sid in sorted(campaigns):
            rev = revenue.get(sid, {"won_deal_count": 0, "won_value_cents": 0})
            item = ROIItem(
                entity_id=str(sid),
                entity_label=str(sid),
                **ROIService._build_value(
                    revenue=int(rev.get("won_value_cents", 0)),
                    won_deal_count=int(rev.get("won_deal_count", 0)),
                    reached_customers=0,  # no reach attribution per campaign
                    input_terms={"campaign_leads": campaigns[sid]},
                    rates=rates,
                ).model_dump(),
            )
            items.append(item)

        items.sort(
            key=lambda i: (i.roi is None, -(i.revenue_cents or 0), i.entity_id or ""),
        )

        summary_terms: Dict[str, int] = {}
        for sid in campaigns:
            summary_terms["campaign_leads"] = summary_terms.get("campaign_leads", 0) + campaigns[sid]
        summary = ROIService._build_value(
            revenue=sum(i.revenue_cents for i in items),
            won_deal_count=sum(i.won_deal_count for i in items),
            reached_customers=0,
            input_terms=summary_terms,
            rates=rates,
        )

        return ROIResponse(
            dimension="campaign",
            window=ROIWindow(since=since, until=until, default_applied=default_applied),
            filters=filters,
            cost_rates=ROICostRates(
                cost_per_outbound_message_cents=rates.get("cost_per_outbound_message_cents", 0),
                cost_per_nurture_execution_cents=rates.get("cost_per_nurture_execution_cents", 0),
                cost_per_followup_task_cents=rates.get("cost_per_followup_task_cents", 0),
                cost_per_active_agent_cents=rates.get("cost_per_active_agent_cents", 0),
                cost_per_campaign_lead_cents=rates.get("cost_per_campaign_lead_cents", 0),
                configured=ROIService._cost_basis_configured(rates),
            ),
            cost_basis_configured=ROIService._cost_basis_configured(rates),
            summary=summary,
            items=items,
        )

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------
    async def get_roi(
        self,
        dimension: str,
        agent_id: Optional[UUID] = None,
        account_id: Optional[UUID] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        rates: Optional[Dict[str, int]] = None,
    ) -> ROIResponse:
        """Compute the ROI report for one dimension.

        ``rates`` overrides the env-configurable cost-proxy table (defaults to
        ``app.config.roi_cost_rates()`` when omitted) so callers can test /
        ad-hoc re-price the input side without a deploy change.
        """
        if dimension not in DIMENSIONS:
            raise ValueError(
                f"unknown dimension {dimension!r}; expected one of {list(DIMENSIONS)}"
            )
        if rates is None:
            from app.config import roi_cost_rates

            rates = roi_cost_rates()
        rates = self._rates(rates)

        win_since, win_until, default_applied = self._resolve_window(since, until)
        filters = ROIFilters(
            dimension=dimension,
            agent_id=agent_id,
            account_id=account_id,
            since=win_since,
            until=win_until,
        )

        if dimension == "private-domain":
            raw = await self.collect_raw_private_domain(account_id, win_since, win_until)
            return self.assemble_private_domain(
                raw, rates, win_since, win_until, default_applied,
                agent_id, account_id, filters,
            )
        if dimension == "agent":
            raw = await self.collect_raw_agent(win_since, win_until)
            return self.assemble_agent(
                raw, rates, win_since, win_until, default_applied,
                agent_id, account_id, filters,
            )
        raw = await self.collect_raw_campaign(win_since, win_until)
        return self.assemble_campaign(
            raw, rates, win_since, win_until, default_applied,
            agent_id, account_id, filters,
        )


__all__ = [
    "ROIService",
    "DIMENSIONS",
    "CAMPAIGN_SOURCE",
    "_safe_div",
    "_coerce_aware",
    "_naive_utc",
    "DEFAULT_WINDOW_DAYS",
    "_REACHED_MESSAGE_STATUSES",
]
