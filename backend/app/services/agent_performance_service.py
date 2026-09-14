"""Agent Performance analytics service (Phase 6 / P6AN-07).

Computes agent-dimension KPIs (conversation volume, message volume, lead
conversion rate, satisfaction proxy, active time-of-day) plus a ranked agent
leaderboard, by aggregating *existing* platform data — no new tables:

    agent  ─<  agent_customer_binding  >─  customer
                                               ├─< conversation <─ message
                                               └─< lead

Metric caliber (documented in ``docs/ANALYTICS-AGENT-PERFORMANCE.md``)
-----------------------------------------------------------------------
* **Agent scoping.** An agent's activity is the union of activity belonging to
  its live-bound customers. A customer shared by N agents contributes its
  activity to each of those N agents (attribute to every live binding).
* **Window.** All *activity* metrics (conversations, messages, leads,
  sentiment, hour histogram) are filtered to the request window on the
  source entity's ``created_at``. Customer counts (``total_customers`` /
  ``active_customers``) are all-time by design (tenure is not meaningful
  inside a short activity window).
* **Volume.** ``conversation_count`` / ``message_count`` count live
  (``is_deleted = false``) rows in window for the agent's customers.
* **Conversion.** ``conversion_rate = converted_lead_count / lead_count``
  where "converted" = lead whose ``lifecycle_stage_code`` reached a won stage
  (``CONVERSION_STAGE_CODES`` = ``{成交}``). ``None`` when ``lead_count == 0``
  so "no leads" is distinguishable from "0% converted".
* **Satisfaction proxy.** ``Conversation.sentiment`` ∈ {positive, neutral,
  negative} is scored {1.0, 0.5, 0.0}; the proxy is the mean over the
  sentiment-carrying conversations in window. ``None`` when no such
  conversation exists. (No explicit rating system yet — this is the proxy the
  card calls for.)
* **Active time-of-day.** 24-bucket histogram of message volume by UTC
  hour-of-day in window; ``peak_hour`` is the busiest hour (``None`` when the
  agent has no in-window messages).

Design notes
------------
* Read-only: no commit. Every metric is a live aggregate over existing rows.
* Set-based: the leaderboard path issues a fixed number of grouped queries
  (≈7) regardless of how many agents match, then merges per-agent in Python —
  no N+1.
* Empty-data agents are *not* errors: they surface as all-zero / ``None``
  metric blocks (acceptance criterion "空数据 Agent 返回 0 而非报错").
* The leaderboard starts from the set of **live agents** matching the filters
  and left-joins the aggregates, so an agent with zero activity still appears
  (with zeros) and is sortable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent, AgentCustomerBinding
from app.db.models.conversation import Conversation, Message
from app.db.models.customer import Customer
from app.db.models.lead import Lead
from app.schemas.agent_performance import (
    AgentPerformanceMetrics,
    AgentPerformanceResponse,
    AgentPerformanceLeaderboardResponse,
    LEADERBOARD_SORT_KEYS,
)

logger = logging.getLogger(__name__)


# ===== metric caliber constants (single source of truth; see docs) =====

#: Lifecycle stage codes that count as "converted / won".
CONVERSION_STAGE_CODES = frozenset({"成交"})

#: Sentiment label -> satisfaction score (mean -> satisfaction_proxy).
SENTIMENT_SCORES: Dict[str, float] = {"positive": 1.0, "neutral": 0.5, "negative": 0.0}
_SENTIMENT_LABELS = tuple(SENTIMENT_SCORES)

#: range preset -> number of days back from ``now``.
_RANGE_PRESETS: Dict[str, int] = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}
#: Full set of legal ``range`` values (presets + ``all``).
VALID_RANGES = tuple(_RANGE_PRESETS) + ("all",)

#: Sort-key -> (label). ``activity`` = conversation_count + message_count
#: (overall interaction volume); numeric keys substitute 0.0 for a null rate
#: so ordering is deterministic.
_SORT_IS_NUMERIC: Dict[str, bool] = {
    "conversations": True,
    "messages": True,
    "activity": True,
    "conversion_rate": True,
    "satisfaction": True,
    "customers": True,
}
_HOURS = 24


class AgentPerformanceError(Exception):
    """Base for agent-performance domain errors (router maps to HTTP)."""


class AgentNotFoundError(AgentPerformanceError):
    """The requested agent does not exist or is soft-deleted."""

    def __init__(self, agent_id: UUID):
        self.agent_id = agent_id
        super().__init__(f"Agent {agent_id} not found")


class InvalidRangeError(AgentPerformanceError):
    """An unknown ``range`` value (or unparseable since/until)."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _empty_metrics(agent: Agent) -> AgentPerformanceMetrics:
    """All-zero / null metric block for an agent with no data (never an error)."""
    return AgentPerformanceMetrics(
        agent_id=agent.id,
        agent_name=agent.name,
        status=agent.status,
        total_customers=0,
        active_customers=0,
        conversation_count=0,
        message_count=0,
        lead_count=0,
        converted_lead_count=0,
        conversion_rate=None,
        satisfaction_proxy=None,
        satisfaction_sample=0,
        sentiment_breakdown={lbl: 0 for lbl in _SENTIMENT_LABELS},
        active_hours=[0] * _HOURS,
        peak_hour=None,
    )


def _window_filters(ts: Any, since: Optional[datetime], until: Optional[datetime]) -> List[Any]:
    """Equality-free window predicates for a timestamp column (``None`` -> unbounded)."""
    out: List[Any] = []
    if since is not None:
        out.append(ts >= since)
    if until is not None:
        out.append(ts <= until)
    return out


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Strip tzinfo to a naive-UTC wall clock (exact for aware-UTC inputs).

    The codebase mixes naive (``lead.created_at``, ``customer.created_at``) and
    aware (``conversation``/``message``) timestamp columns. Window bounds are
    canonical aware-UTC; naive-tz columns need the naive wall clock so a
    Postgres ``timestamp`` (no tz) column is compared against a matching literal
    regardless of the session TZ.
    """
    return dt.replace(tzinfo=None) if dt is not None else None


class AgentPerformanceService:
    """Compute agent KPIs and the ranked agent leaderboard (read-only)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ----------------------------------------------------------------- range

    @staticmethod
    def resolve_window(
        range_: Optional[str],
        since: Optional[datetime],
        until: Optional[datetime],
        now: Optional[datetime] = None,
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Turn a ``range`` preset (+ optional explicit since/until) into a window.

        * ``range`` in ``7d/30d/90d/365d`` -> ``(now - N days, now)``.
        * ``range == 'all'`` (or omitted)   -> ``(None, None)`` = unbounded.
        * Explicit ``since`` / ``until`` override the corresponding bound.

        Raises :class:`InvalidRangeError` for an unknown preset or a
        naive/non-ISO bound.
        """
        now = now or datetime.now(timezone.utc)
        if since is not None and since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        if until is not None and until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)

        win_since: Optional[datetime] = None
        win_until: Optional[datetime] = None

        if range_ is None or range_ == "all":
            pass
        elif range_ in _RANGE_PRESETS:
            win_since = now - timedelta(days=_RANGE_PRESETS[range_])
            win_until = now
        else:
            raise InvalidRangeError(
                f"Unknown range {range_!r}; expected one of {list(VALID_RANGES)}."
            )

        if since is not None:
            win_since = since
        if until is not None:
            win_until = until
        return win_since, win_until

    # ------------------------------------------------------------- aggregates

    async def _fetch_agent(self, agent_id: UUID) -> Optional[Agent]:
        res = await self.db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.is_deleted.is_(False))
        )
        return res.scalar_one_or_none()

    async def _aggregates_for(
        self, agent_ids: List[UUID], since: Optional[datetime], until: Optional[datetime]
    ) -> Dict[UUID, Dict[str, Any]]:
        """Run the fixed set of grouped queries; return per-agent metric cells.

        Keys per agent: conversation_count, message_count, lead_count,
        converted_lead_count, sentiment (dict by label), active_hours (list).
        """
        out: Dict[UUID, Dict[str, Any]] = {
            aid: {
                "conversation_count": 0,
                "message_count": 0,
                "lead_count": 0,
                "converted_lead_count": 0,
                "sentiment": {lbl: 0 for lbl in _SENTIMENT_LABELS},
                "active_hours": [0] * _HOURS,
            }
            for aid in agent_ids
        }
        if not agent_ids:
            return out

        ids = list(agent_ids)
        live_binding = AgentCustomerBinding.is_deleted.is_(False)
        live_customer = Customer.is_deleted.is_(False)

        # (1) conversation volume, grouped by agent.
        conv = (
            select(AgentCustomerBinding.agent_id, func.count(Conversation.id).label("n"))
            .join(Conversation, and_(
                Conversation.customer_id == AgentCustomerBinding.customer_id,
                Conversation.is_deleted.is_(False),
            ))
            .join(Customer, and_(
                Customer.id == AgentCustomerBinding.customer_id, live_customer,
            ))
            .where(
                live_binding,
                AgentCustomerBinding.agent_id.in_(ids),
                *_window_filters(Conversation.created_at, since, until),
            )
            .group_by(AgentCustomerBinding.agent_id)
        )
        for agent_id, n in (await self.db.execute(conv)).all():
            out[agent_id]["conversation_count"] = int(n or 0)

        # (2) message volume, grouped by agent (join via conversation). Join
        # conversation BEFORE message so the ON clause can reference it.
        msg = (
            select(AgentCustomerBinding.agent_id, func.count(Message.id).label("n"))
            .join(Conversation, and_(
                Conversation.customer_id == AgentCustomerBinding.customer_id,
                Conversation.is_deleted.is_(False),
            ))
            .join(Message, and_(
                Message.conversation_id == Conversation.id,
                Message.is_deleted.is_(False),
            ))
            .join(Customer, and_(
                Customer.id == AgentCustomerBinding.customer_id, live_customer,
            ))
            .where(
                live_binding,
                AgentCustomerBinding.agent_id.in_(ids),
                *_window_filters(Message.created_at, since, until),
            )
            .group_by(AgentCustomerBinding.agent_id)
        )
        for agent_id, n in (await self.db.execute(msg)).all():
            out[agent_id]["message_count"] = int(n or 0)

        # (3) lead volume in window, grouped by agent. Lead.created_at is a
        # naive ``timestamp`` column, so the window bounds must be naive-UTC
        # (exact for aware-UTC inputs) to compare cleanly regardless of TZ.
        lead_since, lead_until = _naive_utc(since), _naive_utc(until)
        leads = (
            select(AgentCustomerBinding.agent_id, func.count(Lead.id).label("n"))
            .join(Customer, and_(
                Customer.id == AgentCustomerBinding.customer_id, live_customer,
            ))
            .join(Lead, and_(
                Lead.customer_id == Customer.id, Lead.is_deleted.is_(False),
            ))
            .where(
                live_binding,
                AgentCustomerBinding.agent_id.in_(ids),
                *_window_filters(Lead.created_at, lead_since, lead_until),
            )
            .group_by(AgentCustomerBinding.agent_id)
        )
        for agent_id, n in (await self.db.execute(leads)).all():
            out[agent_id]["lead_count"] = int(n or 0)

        # (4) converted leads in window, grouped by agent.
        converted = (
            select(AgentCustomerBinding.agent_id, func.count(Lead.id).label("n"))
            .join(Customer, and_(
                Customer.id == AgentCustomerBinding.customer_id, live_customer,
            ))
            .join(Lead, and_(
                Lead.customer_id == Customer.id,
                Lead.is_deleted.is_(False),
                Lead.lifecycle_stage_code.in_(CONVERSION_STAGE_CODES),
            ))
            .where(
                live_binding,
                AgentCustomerBinding.agent_id.in_(ids),
                *_window_filters(Lead.created_at, lead_since, lead_until),
            )
            .group_by(AgentCustomerBinding.agent_id)
        )
        for agent_id, n in (await self.db.execute(converted)).all():
            out[agent_id]["converted_lead_count"] = int(n or 0)

        # (5) sentiment counts by label, grouped by (agent, sentiment).
        sent = (
            select(
                AgentCustomerBinding.agent_id,
                Conversation.sentiment.label("s"),
                func.count(Conversation.id).label("n"),
            )
            .join(Conversation, and_(
                Conversation.customer_id == AgentCustomerBinding.customer_id,
                Conversation.is_deleted.is_(False),
                Conversation.sentiment.is_not(None),
            ))
            .join(Customer, and_(
                Customer.id == AgentCustomerBinding.customer_id, live_customer,
            ))
            .where(
                live_binding,
                AgentCustomerBinding.agent_id.in_(ids),
                *_window_filters(Conversation.created_at, since, until),
            )
            .group_by(AgentCustomerBinding.agent_id, Conversation.sentiment)
        )
        for agent_id, label, n in (await self.db.execute(sent)).all():
            if label in out[agent_id]["sentiment"]:
                out[agent_id]["sentiment"][label] = int(n or 0)

        # (6) hour-of-day histogram of messages, grouped by (agent, hour).
        hour_expr = func.date_part("hour", func.timezone("UTC", Message.created_at))
        hours_q = (
            select(AgentCustomerBinding.agent_id, hour_expr.label("h"), func.count(Message.id).label("n"))
            .join(Conversation, and_(
                Conversation.customer_id == AgentCustomerBinding.customer_id,
                Conversation.is_deleted.is_(False),
            ))
            .join(Message, and_(
                Message.conversation_id == Conversation.id,
                Message.is_deleted.is_(False),
            ))
            .join(Customer, and_(
                Customer.id == AgentCustomerBinding.customer_id, live_customer,
            ))
            .where(
                live_binding,
                AgentCustomerBinding.agent_id.in_(ids),
                *_window_filters(Message.created_at, since, until),
            )
            .group_by(AgentCustomerBinding.agent_id, hour_expr)
        )
        for agent_id, hour, n in (await self.db.execute(hours_q)).all():
            h = int(hour)
            if 0 <= h < _HOURS:
                out[agent_id]["active_hours"][h] = int(n or 0)

        return out

    async def _customer_counts_for(self, agent_ids: List[UUID]) -> Dict[UUID, Dict[str, int]]:
        """All-time ``total_customers`` / ``active_customers`` per agent."""
        out: Dict[UUID, Dict[str, int]] = {
            aid: {"total_customers": 0, "active_customers": 0} for aid in agent_ids
        }
        if not agent_ids:
            return out
        ids = list(agent_ids)
        live_binding = AgentCustomerBinding.is_deleted.is_(False)
        live_customer = Customer.is_deleted.is_(False)

        total = (
            select(
                AgentCustomerBinding.agent_id,
                func.count(func.distinct(AgentCustomerBinding.customer_id)).label("n"),
            )
            .join(Customer, and_(
                Customer.id == AgentCustomerBinding.customer_id, live_customer,
            ))
            .where(live_binding, AgentCustomerBinding.agent_id.in_(ids))
            .group_by(AgentCustomerBinding.agent_id)
        )
        for agent_id, n in (await self.db.execute(total)).all():
            out[agent_id]["total_customers"] = int(n or 0)

        # Active = customer has ≥1 live, not-yet-converted lead (open pipeline).
        active = (
            select(
                AgentCustomerBinding.agent_id,
                func.count(func.distinct(AgentCustomerBinding.customer_id)).label("n"),
            )
            .join(Customer, and_(
                Customer.id == AgentCustomerBinding.customer_id, live_customer,
            ))
            .join(Lead, and_(
                Lead.customer_id == Customer.id,
                Lead.is_deleted.is_(False),
                Lead.lifecycle_stage_code.is_distinct_from("成交"),
            ))
            .where(live_binding, AgentCustomerBinding.agent_id.in_(ids))
            .group_by(AgentCustomerBinding.agent_id)
        )
        for agent_id, n in (await self.db.execute(active)).all():
            out[agent_id]["active_customers"] = int(n or 0)

        return out

    # ------------------------------------------------------------- assembly

    @staticmethod
    def _assemble(
        agent: Agent,
        agg: Dict[str, Any],
        cust: Dict[str, int],
        since: Optional[datetime],
        until: Optional[datetime],
    ) -> AgentPerformanceMetrics:
        lead_count = agg["lead_count"]
        converted = agg["converted_lead_count"]
        conversion_rate = (converted / lead_count) if lead_count > 0 else None

        sent = agg["sentiment"]
        sample = sum(sent.values())
        if sample > 0:
            proxy = sum(SENTIMENT_SCORES[k] * v for k, v in sent.items()) / sample
        else:
            proxy = None

        active_hours = list(agg["active_hours"])
        peak = None
        if any(active_hours):
            peak = max(range(_HOURS), key=lambda i: active_hours[i])

        return AgentPerformanceMetrics(
            agent_id=agent.id,
            agent_name=agent.name,
            status=agent.status,
            total_customers=cust.get("total_customers", 0),
            active_customers=cust.get("active_customers", 0),
            conversation_count=agg["conversation_count"],
            message_count=agg["message_count"],
            lead_count=lead_count,
            converted_lead_count=converted,
            conversion_rate=conversion_rate,
            satisfaction_proxy=proxy,
            satisfaction_sample=sample,
            sentiment_breakdown=dict(sent),
            active_hours=active_hours,
            peak_hour=peak,
        )

    @staticmethod
    def _window_label(since: Optional[datetime], until: Optional[datetime],
                      range_: Optional[str]) -> Dict[str, Optional[str]]:
        if since is None and until is None:
            return {"range": range_ or "all"}
        return {
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        }

    # ------------------------------------------------------------- endpoints

    async def single(
        self, agent_id: UUID,
        range_: Optional[str] = "30d",
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> AgentPerformanceResponse:
        """One agent's KPI block (0-block when it has no data, 404 if absent)."""
        agent = await self._fetch_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError(agent_id)

        since, until = self.resolve_window(range_, since, until)
        agg = await self._aggregates_for([agent.id], since, until)
        cust = await self._customer_counts_for([agent.id])
        metrics = self._assemble(agent, agg[agent.id], cust[agent.id], since, until)
        return AgentPerformanceResponse(
            metrics=metrics,
            window=self._window_label(since, until, range_),
        )

    async def leaderboard(
        self,
        range_: Optional[str] = "30d",
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        sort_key: str = "conversations",
        order: str = "desc",
        status: Optional[str] = None,
        name: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> AgentPerformanceLeaderboardResponse:
        """Ranked agent leaderboard (all live agents, zeros for empty ones)."""
        if sort_key not in LEADERBOARD_SORT_KEYS:
            raise InvalidRangeError(
                f"Unknown sort_key {sort_key!r}; expected one of {list(LEADERBOARD_SORT_KEYS)}."
            )
        order = (order or "desc").lower()
        if order not in ("asc", "desc"):
            raise InvalidRangeError(f"Unknown order {order!r}; expected 'asc' or 'desc'.")
        page = max(1, page)
        page_size = max(1, min(page_size, 200))

        since, until = self.resolve_window(range_, since, until)

        # Live agents matching the optional status / name filters.
        q = select(Agent).where(Agent.is_deleted.is_(False))
        if status:
            q = q.where(Agent.status == status)
        if name:
            q = q.where(Agent.name.ilike(f"%{name}%"))
        q = q.order_by(Agent.created_at.asc(), Agent.name.asc())
        agents: List[Agent] = list((await self.db.execute(q)).scalars().all())

        if not agents:
            return AgentPerformanceLeaderboardResponse(
                items=[], total_agents=0, sort_key=sort_key, order=order,
                page=page, page_size=page_size,
                window=self._window_label(since, until, range_),
            )

        ids = [a.id for a in agents]
        aggs = await self._aggregates_for(ids, since, until)
        custs = await self._customer_counts_for(ids)
        by_id = {a.id: a for a in agents}

        # Build a metric block per agent (zeros when empty) + a sortable key.
        entries: List[Tuple[Agent, AgentPerformanceMetrics, Any]] = []
        for a in agents:
            m = self._assemble(a, aggs[a.id], custs[a.id], since, until)
            entries.append((a, m, self._sort_value(a, m, sort_key)))

        reverse = order == "desc"
        # Deterministic tie-break: sort key, then name, then created_at.
        entries.sort(
            key=lambda e: (e[2], e[1].agent_name, e[0].created_at),
            reverse=reverse,
        )

        total_agents = len(agents)
        start = (page - 1) * page_size
        paged = entries[start : start + page_size]

        logger.info(
            "Agent performance leaderboard: range=%s since=%s until=%s sort=%s order=%s "
            "status=%s name=%s -> %d agents, page=%d/%d",
            range_, since, until, sort_key, order, status, name,
            total_agents, page, total_agents,
        )
        return AgentPerformanceLeaderboardResponse(
            items=[m for _, m, _ in paged],
            total_agents=total_agents,
            sort_key=sort_key,
            order=order,
            page=page,
            page_size=page_size,
            window=self._window_label(since, until, range_),
        )

    @staticmethod
    def _sort_value(agent: Agent, m: AgentPerformanceMetrics, sort_key: str) -> Any:
        # Explicit mapping: the public sort keys are shorter labels that do not
        # always match a metric field name verbatim ("conversations" ->
        # conversation_count, "messages" -> message_count). The old getattr
        # fallback silently returned 0 for these, so the default
        # "conversations" sort was effectively a no-op — now each key maps to
        # a real, comparable value.
        if sort_key == "name":
            return m.agent_name.lower()
        if sort_key == "created_at":
            # Agent.created_at is naive (datetime.utcnow default); keep the
            # fallback naive so the comparator never mixes tz-aware/naive.
            return agent.created_at or datetime.min
        if sort_key == "activity":
            return m.conversation_count + m.message_count
        if sort_key == "conversations":
            return m.conversation_count
        if sort_key == "messages":
            return m.message_count
        if sort_key == "conversion_rate":
            return m.conversion_rate if m.conversion_rate is not None else 0.0
        if sort_key == "satisfaction":
            return m.satisfaction_proxy if m.satisfaction_proxy is not None else 0.0
        if sort_key == "customers":
            return m.total_customers
        # Defensive fallback: unknown-but-validated keys still order by
        # conversation volume rather than silently 0.
        return m.conversation_count
