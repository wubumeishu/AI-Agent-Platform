"""P6AN-05 Lead Conversion analytics.

Computes the lead conversion funnel (New -> Contacted -> Qualified ->
Converted) and the average conversion cycle, aggregated overall and by
Agent / channel / time window.

Data sources (Phase 3 CRM / Phase 4 lead-lifecycle, no new tables):

- ``lead.status``               current funnel position
                                 (state machine mirrors
                                 ``app.crm.services.lead.VALID_STATUS_TRANSITIONS``)
- ``agent_customer_binding``    agent <-> customer link (group-by Agent)
- ``conversation.channel``      channel attribution for leads whose
                                 ``source_type == "conversation"``
                                 (``source_id`` stores ``str(conversation_id)``)
- ``lifecycle_stage_log``       first ``new_stage_code == "成交"`` log gives
                                 the conversion moment; falls back to
                                 ``lead.updated_at`` when absent

All computation is a small number of aggregate SQL queries plus a pure
function (:func:`compute_metrics`) so the metric math is unit-testable
without a database (repo convention, cf. P6AN-01 fake-session tests).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import String, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent, AgentCustomerBinding
from app.db.models.conversation import Conversation
from app.db.models.lead import Lead
from app.db.models.lifecycle import LifecycleStageLog

#: Funnel order for the lead status state machine.
FUNNEL_ORDER: Tuple[str, ...] = ("new", "contacted", "qualified", "converted")
#: Status that defines a lead as converted.
CONVERTED_STATUS = "converted"
#: source_type marking a lead that originated from a conversation.
CONVERSATION_SOURCE = "conversation"
#: Channel label for leads without conversation attribution.
DIRECT_CHANNEL = "direct"
#: Agent label for leads with no agent binding.
UNASSIGNED_AGENT = "unassigned"
#: Lifecycle stage code meaning "deal closed".
CLOSED_STAGE_CODE = "成交"


class LeadConversionError(Exception):
    """Invalid parameters for the lead-conversion computation."""


@dataclass
class _GroupStatusCounts:
    """Distinct-lead counts per status for one group (or the overall cohort)."""

    key: str
    label: str
    status_counts: Dict[str, int] = field(default_factory=dict)


def _funnel_rank(status: str) -> int:
    """Position in the funnel; unknown statuses rank before 'new' (-1) and
    therefore contribute to no stage-reached count."""
    if status in FUNNEL_ORDER:
        return FUNNEL_ORDER.index(status)
    return -1


def _stage_reached(status_counts: Dict[str, int]) -> Dict[str, int]:
    """Number of leads that have *reached* each funnel stage.

    A lead at stage S has reached every stage up to and including S
    (monotonic-funnel assumption: statuses advance through the documented
    machine; the rare back-transition from ``qualified`` to ``contacted``
    still counts as having reached both).
    """
    return {
        stage: sum(n for s, n in status_counts.items() if _funnel_rank(s) >= _funnel_rank(stage))
        for stage in FUNNEL_ORDER
    }


def _rates(reached: Dict[str, int]) -> Dict[str, Optional[float]]:
    """Step + overall conversion rates.

    ``None`` when the denominator is 0 (empty source stage) — consumers
    render that as "no data", not 0%.
    """
    def div(num: int, den: int) -> Optional[float]:
        return (num / den) if den > 0 else None

    return {
        "new_to_contacted": div(reached.get("contacted", 0), reached.get("new", 0)),
        "contacted_to_qualified": div(reached.get("qualified", 0), reached.get("contacted", 0)),
        "qualified_to_converted": div(reached.get("converted", 0), reached.get("qualified", 0)),
        "new_to_converted": div(reached.get("converted", 0), reached.get("new", 0)),
    }


def compute_metrics(
    group_counts: List[_GroupStatusCounts],
    cycles_days: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Pure metric math over distinct-lead status counts + cycle samples.

    ``group_counts`` carries one element per reported cohort (overall or a
    single group); deterministic and DB-free so it can be unit-tested in
    isolation.
    """
    zero = {s: 0 for s in FUNNEL_ORDER}
    if not group_counts:
        return {
            "total_leads": 0,
            "status_counts": zero,
            "stage_reached_counts": zero,
            "conversion_rates": {k: None for k in _rates(zero)},
            "avg_conversion_cycle_days": None,
        }

    merged: Dict[str, int] = {}
    for g in group_counts:
        for s, n in g.status_counts.items():
            merged[s] = merged.get(s, 0) + n
    total = sum(merged.values())
    reached = _stage_reached(merged)

    avg_cycle: Optional[float] = None
    if cycles_days:
        avg_cycle = sum(cycles_days) / len(cycles_days)

    return {
        "total_leads": total,
        "status_counts": merged,
        "stage_reached_counts": reached,
        "conversion_rates": _rates(reached),
        "avg_conversion_cycle_days": avg_cycle,
    }


class LeadConversionService:
    """Aggregate lead-conversion funnels from the live CRM tables."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- query building helpers ----------

    @staticmethod
    def _base_where(agent_id: Optional[UUID], channel: Optional[str],
                    from_date: Optional[datetime], to_date: Optional[datetime]) -> List:
        criteria: List[Any] = [Lead.is_deleted == False]  # noqa: E712
        if from_date is not None:
            criteria.append(Lead.created_at >= from_date)
        if to_date is not None:
            criteria.append(Lead.created_at <= to_date)
        if agent_id is not None:
            criteria.append(AgentCustomerBinding.agent_id == agent_id)
        if channel is not None:
            # Only conversation-source leads carry a channel; the outer
            # conversation join makes non-conversation leads NULL, and the
            # equality filter excludes them.
            criteria.append(Conversation.channel == channel)
        return criteria

    def _apply_joins(self, q: Any, agent_group: bool, channel_group: bool,
                     agent_filter: bool, channel_filter: bool) -> Any:
        need_binding = agent_group or agent_filter
        need_conv = channel_group or channel_filter
        if need_binding:
            q = q.outerjoin(
                AgentCustomerBinding,
                and_(
                    Lead.customer_id == AgentCustomerBinding.customer_id,
                    Lead.customer_id.is_not(None),
                ),
            )
        if agent_group:
            q = q.outerjoin(Agent, AgentCustomerBinding.agent_id == Agent.id)
        if need_conv:
            q = q.outerjoin(
                Conversation,
                and_(
                    Lead.source_type == CONVERSATION_SOURCE,
                    Lead.source_id == func.cast(Conversation.id, String),
                ),
            )
        return q

    def _group_key(self, group_by: str) -> Any:
        if group_by == "agent":
            return func.coalesce(Agent.name, UNASSIGNED_AGENT).label("group_key")
        if group_by == "channel":
            return func.coalesce(func.lower(Conversation.channel), DIRECT_CHANNEL).label("group_key")
        return None

    # ---------- public API ----------

    async def compute(
        self,
        agent_id: Optional[UUID] = None,
        channel: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        group_by: str = "overall",
    ) -> Dict[str, Any]:
        """Compute the lead-conversion report.

        Returns a dict shaped like
        ``app.schemas.lead_conversion.LeadConversionResponse``:

        - ``totals``: metrics over the whole filtered cohort
        - ``groups``: per-Agent / per-channel metrics (empty when
          ``group_by == "overall"``); each entry carries the same metric
          dict plus a per-group ``avg_conversion_cycle_days``
        - ``filters``: echo of the applied filters

        Distinct-lead counting: a lead bound to two agents is counted once
        in *each* agent's group but only once in ``totals``.
        """
        if group_by not in ("overall", "agent", "channel"):
            raise LeadConversionError(
                f"invalid group_by {group_by!r}; expected overall/agent/channel"
            )

        where = self._base_where(agent_id, channel, from_date, to_date)
        gkey = self._group_key(group_by)

        # ---- Query 1: distinct-lead counts per status (overall) ----
        q = select(Lead.status, func.count(func.distinct(Lead.id)).label("n"))
        q = self._apply_joins(q, group_by == "agent", group_by == "channel",
                              agent_id is not None, channel is not None)
        q = q.where(*where).group_by(Lead.status)
        overall_counts: Dict[str, int] = {}
        for r in (await self.db.execute(q)).all():
            overall_counts[r.status] = r.n

        # ---- Query 2: distinct-lead counts per (group, status) ----
        groups: Dict[str, Dict[str, int]] = {}
        if gkey is not None:
            qg = select(gkey, Lead.status, func.count(func.distinct(Lead.id)).label("n"))
            qg = self._apply_joins(qg, group_by == "agent", group_by == "channel",
                                   agent_id is not None, channel is not None)
            qg = qg.where(*where).group_by(gkey, Lead.status)
            for r in (await self.db.execute(qg)).all():
                gval = r.group_key
                status = r.status
                n = r.n
                key = gval if gval not in (None, "") else (
                    UNASSIGNED_AGENT if group_by == "agent" else DIRECT_CHANNEL)
                groups.setdefault(key, {})[status] = n

        # ---- Query 3: conversion-cycle samples (converted leads) ----
        cq = select(
            Lead.id,
            Lead.created_at,
            Lead.updated_at,
            func.min(LifecycleStageLog.created_at).label("stage_ts"),
        ).outerjoin(
            LifecycleStageLog,
            and_(
                LifecycleStageLog.lead_id == Lead.id,
                LifecycleStageLog.new_stage_code == CLOSED_STAGE_CODE,
            ),
        ).where(
            Lead.status == CONVERTED_STATUS,
            Lead.is_deleted == False,  # noqa: E712
        )
        if from_date is not None:
            cq = cq.where(Lead.created_at >= from_date)
        if to_date is not None:
            cq = cq.where(Lead.created_at <= to_date)
        if gkey is not None:
            cq = cq.add_columns(gkey)
        cq = self._apply_joins(cq, group_by == "agent", group_by == "channel",
                               agent_id is not None, channel is not None)
        if agent_id is not None:
            cq = cq.where(AgentCustomerBinding.agent_id == agent_id)
        if channel is not None:
            cq = cq.where(Conversation.channel == channel)
        cq = cq.group_by(Lead.id, Lead.created_at, Lead.updated_at)
        if gkey is not None:
            cq = cq.group_by(gkey)
        rows = (await self.db.execute(cq)).all()

        overall_cycles: List[float] = []
        seen_leads: set = set()
        group_cycles: Dict[str, List[float]] = {}
        for row in rows:
            ts = row.stage_ts if row.stage_ts is not None else row.updated_at
            # Lead/lifecycle timestamps are naive UTC (datetime.utcnow
            # defaults); normalize defensively before subtracting.
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            days = max(0.0, (ts - row.created_at).total_seconds() / 86400.0)
            # A lead bound to two agents appears twice (once per binding);
            # the overall average counts each lead exactly once.
            if row.id not in seen_leads:
                seen_leads.add(row.id)
                overall_cycles.append(days)
            if gkey is not None:
                gval = getattr(row, "group_key", None)
                key = gval if gval not in (None, "") else (
                    UNASSIGNED_AGENT if group_by == "agent" else DIRECT_CHANNEL)
                group_cycles.setdefault(key, []).append(days)

        totals = compute_metrics(
            [_GroupStatusCounts("total", "total", overall_counts)],
            sorted(overall_cycles),
        )

        out_groups: List[Dict[str, Any]] = []
        for key in sorted(groups):
            metrics = compute_metrics(
                [_GroupStatusCounts(key, key, groups[key])],
                group_cycles.get(key),
            )
            out_groups.append({"key": key, "label": key, "metrics": metrics})

        return {
            "filters": {
                "agent_id": str(agent_id) if agent_id else None,
                "channel": channel,
                "from_date": from_date,
                "to_date": to_date,
                "group_by": group_by,
                "window_basis": "lead.created_at",
            },
            "totals": totals,
            "groups": out_groups,
        }
