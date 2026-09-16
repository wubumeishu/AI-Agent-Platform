"""Dashboard overview aggregation service (Phase 6 / P6AN-02).

Aggregates Agent / conversation / channel-message / conversion metrics into
one flat overview payload for the frontend Dashboard and external integrations.

Architecture notes
------------------
* API -> Service (this module) -> SQL aggregation. No business rules live in
  route handlers (repo convention, same split as ``analytics_service``).
* Agent dimension: an agent "owns" work through two hard references —
  ``ChannelMessage.agent_id`` (delivery log) and ``AgentCustomerBinding``
  (customer responsibility), plus the AI-tier binding
  ``AgentPersonaBinding.agent_id``. Conversations and leads are scoped to an
  agent through their customers (``Customer.agent_bindings``) when the
  agent filter is set; when no agent owns the customer the conversation/lead
  is excluded from that agent's numbers.
* Conversion follows P6AN-05's source of truth: a lead is "converted"
  (成交) when ``Lead.status == "converted"`` — the CRM lead status state
  machine's terminal state. This keeps the overview number consistent with
  ``GET /analytics/leads/conversion``.
* Response caching: the router consults ``dashboard_cache`` (Redis when
  configured, in-memory fallback) around :func:`DashboardOverviewService.compute`
  with TTL 300 s; the ``cached`` flag is stamped by the server, not stored.

Time window: ``end`` is the **exclusive** upper bound; the default window is
the last ``days`` days ending "now" (UTC), minimum 1 day.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent, AgentCustomerBinding
from app.db.models.conversation import Conversation
from app.db.models.lead import Lead
from app.db.models.messages import ChannelMessage
from app.security.analytics_access import tenant_agent_subquery, tenant_customer_subquery
from app.schemas.dashboard import (
    AgentStat,
    AgentsOverview,
    ConversionOverview,
    ConversationsOverview,
    DashboardRange,
    DashboardOverviewResponse,
    MessagesOverview,
)

logger = logging.getLogger(__name__)

# P6AN-05 source of truth for a converted (成交) lead.
CONVERTED_LEAD_STATUS = "converted"


def _resolve_window(
    start: Optional[datetime],
    end: Optional[datetime],
    days: int,
    now: Optional[datetime] = None,
) -> tuple[datetime, datetime, int]:
    """Resolve the query window to **aware UTC** (start inclusive, end exclusive).

    Returns ``(start, end, days)``; ``days`` is the effective window length
    (0 when an explicit range was supplied).

    Aware UTC is the canonical bound form: it binds to every source
    ``timestamptz`` column (``conversation`` / ``messages`` / ``agent`` /
    ``lead`` / ``customer`` / ...) as an absolute instant. P6AN-17 P2-3
    (ADR-019) unified the whole schema to aware-UTC ``timestamptz``, so no
    per-table naive-UTC stripping is required — a naive bound would be
    session-timezone-dependent, and aware UTC is session-tz independent.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if start is not None and end is not None:
        s, e = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        if s >= e:
            raise ValueError(
                "time_range_start must be strictly before time_range_end"
            )
        return s, e, 0
    e = (end if end is not None else now).astimezone(timezone.utc)
    s = (start if start is not None else e - timedelta(days=days)).astimezone(timezone.utc)
    if s >= e:
        raise ValueError(
            "time_range_start must be strictly before time_range_end"
        )
    return s, e, max((e - s).days, 0)


def _naive_utc(dt: datetime) -> datetime:
    """Kept for backward-compatible imports; **no longer used** for lead/customer
    window bounds.

    P6AN-17 P2-3 unified the Phase 1-5 source columns (``lead``/``customer``/
    ...) to aware-UTC ``timestamptz``, so query bounds are now aware-UTC and
    bind directly as absolute instants — no naive stripping is required. The
    platform-wide ``timestamptz`` convention (ADR-019) supersedes the
    per-table naive ``timestamp`` handling this helper once implemented.
    """
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class DashboardOverviewService:
    """Compute the dashboard overview aggregate (single DB round-trip per section)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ----- helpers ----------------------------------------------------------

    async def _scalar(self, expr: Any) -> Any:
        """Execute a scalar aggregate: pass either a bare column expression
        (wrapped in ``select``) or an already-built select statement."""
        from sqlalchemy.sql.selectable import Select

        if not isinstance(expr, Select):
            expr = select(expr)
        return (await self.db.execute(expr)).scalar()

    def _count(self, entity_id: Any, *criteria: Any) -> Any:
        """``select(func.count(entity_id)).where(*criteria)`` aggregate query."""
        q = select(func.count(entity_id))
        if criteria:
            q = q.where(*criteria)
        return q

    # ----- sections ---------------------------------------------------------

    async def _agents(self, account_id: Optional[UUID] = None) -> AgentsOverview:
        preds = [Agent.is_deleted == False]  # noqa: E712
        if account_id is not None:
            preds.append(Agent.id.in_(tenant_agent_subquery(account_id)))
        total = await self._scalar(self._count(Agent.id, *preds))
        active = await self._scalar(
            self._count(Agent.id, *preds, Agent.status == "active")
        )
        return AgentsOverview(total=int(total or 0), active=int(active or 0))

    async def _conversations(
        self,
        start: datetime,
        end: datetime,
        agent_id: Optional[UUID],
        channel: Optional[str],
        account_id: Optional[UUID] = None,
    ) -> ConversationsOverview:
        base = and_(
            Conversation.is_deleted == False,  # noqa: E712
            Conversation.created_at >= start,
            Conversation.created_at < end,
        )
        conditions = [base]
        if account_id is not None:
            # P6AN-16: tenant sees only conversations of its own customers.
            conditions.append(
                Conversation.customer_id.in_(tenant_customer_subquery(account_id))
            )
        if channel is not None:
            conditions.append(Conversation.channel == channel)
        if agent_id is not None:
            bound = (
                select(AgentCustomerBinding.customer_id)
                .where(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.is_deleted == False,  # noqa: E712
                )
                .scalar_subquery()
            )
            conditions.append(Conversation.customer_id.in_(bound))

        where = and_(*conditions)
        new_count = int(
            await self._scalar(self._count(Conversation.id, where)) or 0
        )
        avg_msgs = await self._scalar(
            select(func.avg(Conversation.message_count)).where(
                where,
                Conversation.message_count > 0,
            )
        )
        # "Active" = currently open, regardless of creation window.
        active_conditions = [
            Conversation.is_deleted == False,  # noqa: E712
            Conversation.status == "active",
        ]
        if account_id is not None:
            active_conditions.append(
                Conversation.customer_id.in_(tenant_customer_subquery(account_id))
            )
        if channel is not None:
            active_conditions.append(Conversation.channel == channel)
        if agent_id is not None:
            active_conditions.append(
                Conversation.customer_id.in_(
                    (
                        select(AgentCustomerBinding.customer_id)
                        .where(
                            AgentCustomerBinding.agent_id == agent_id,
                            AgentCustomerBinding.is_deleted == False,  # noqa: E712
                        )
                        .scalar_subquery()
                    )
                )
            )
        active = int(
            await self._scalar(
                self._count(Conversation.id, and_(*active_conditions))
            )
            or 0
        )
        # Window messages (agent-scoped via the message table itself).
        msg_conditions = [
            ChannelMessage.is_deleted == False,  # noqa: E712
            ChannelMessage.created_at >= start,
            ChannelMessage.created_at < end,
        ]
        if account_id is not None:
            # Tenant sees only its own channel-message rows.
            msg_conditions.append(ChannelMessage.account_id == account_id)
        if channel is not None:
            msg_conditions.append(ChannelMessage.channel == channel)
        if agent_id is not None:
            msg_conditions.append(ChannelMessage.agent_id == agent_id)
        total_messages = int(
            await self._scalar(
                self._count(ChannelMessage.id, and_(*msg_conditions))
            )
            or 0
        )
        return ConversationsOverview(
            new=new_count,
            active=active,
            total_messages=total_messages,
            avg_messages_per_new_conversation=(
                round(float(avg_msgs), 2) if avg_msgs is not None else None
            ),
        )

    async def _messages(
        self,
        start: datetime,
        end: datetime,
        agent_id: Optional[UUID],
        channel: Optional[str],
        account_id: Optional[UUID] = None,
    ) -> MessagesOverview:
        conditions = [
            ChannelMessage.is_deleted == False,  # noqa: E712
            ChannelMessage.created_at >= start,
            ChannelMessage.created_at < end,
        ]
        if account_id is not None:
            # P6AN-16: tenant sees only its own channel-message rows.
            conditions.append(ChannelMessage.account_id == account_id)
        if channel is not None:
            conditions.append(ChannelMessage.channel == channel)
        if agent_id is not None:
            conditions.append(ChannelMessage.agent_id == agent_id)
        where = and_(*conditions)

        total = int(
            await self._scalar(self._count(ChannelMessage.id, where)) or 0
        )
        delivered = int(
            await self._scalar(
                self._count(
                    ChannelMessage.id,
                    where, ChannelMessage.status.in_(("delivered", "read")),
                )
            )
            or 0
        )
        failed = int(
            await self._scalar(
                self._count(
                    ChannelMessage.id, where, ChannelMessage.status == "failed"
                )
            )
            or 0
        )
        outbound = int(
            await self._scalar(
                self._count(
                    ChannelMessage.id, where, ChannelMessage.direction == "out"
                )
            )
            or 0
        )
        completed = delivered + failed
        success_rate = round(delivered / completed, 4) if completed else None
        return MessagesOverview(
            total=total, sent=outbound, delivered=delivered, failed=failed,
            success_rate=success_rate,
        )

    async def _conversion(
        self,
        start: datetime,
        end: datetime,
        agent_id: Optional[UUID],
        account_id: Optional[UUID] = None,
    ) -> ConversionOverview:
        # ``lead`` / ``customer`` are aware-UTC ``timestamptz`` (P6AN-17 P2-3):
        # bind the aware-UTC window bounds directly as absolute instants.
        lead_start, lead_end = start, end
        base = and_(
            Lead.is_deleted == False,  # noqa: E712
            Lead.created_at >= lead_start,
            Lead.created_at < lead_end,
        )
        conditions = [base]
        # P6AN-16: tenant sees only leads belonging to its own customers.
        tenant_cust = (
            Lead.customer_id.in_(tenant_customer_subquery(account_id))
            if account_id is not None
            else None
        )
        if tenant_cust is not None:
            conditions.append(tenant_cust)
        if agent_id is not None:
            bound = (
                select(AgentCustomerBinding.customer_id)
                .where(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.is_deleted == False,  # noqa: E712
                )
                .scalar_subquery()
            )
            # Leads without a customer are not attributed to any agent.
            conditions.append(Lead.customer_id.in_(bound))
        new_leads = int(
            await self._scalar(
                self._count(Lead.id, and_(*conditions))
            )
            or 0
        )
        all_live_conditions = [Lead.is_deleted == False]  # noqa: E712
        if tenant_cust is not None:
            all_live_conditions.append(tenant_cust)
        all_live = int(
            await self._scalar(
                self._count(Lead.id, *all_live_conditions)
            )
            or 0
        )
        converted_conditions = [
            Lead.is_deleted == False,  # noqa: E712
            Lead.status == CONVERTED_LEAD_STATUS,
        ]
        if tenant_cust is not None:
            converted_conditions.append(tenant_cust)
        converted = int(
            await self._scalar(
                self._count(Lead.id, *converted_conditions)
            )
            or 0
        )
        rate = round(converted / all_live, 4) if all_live else None
        return ConversionOverview(
            new_leads=new_leads,
            total_leads=all_live,
            closed_leads=converted,
            conversion_rate=rate,
        )

    async def _by_agent(
        self,
        start: datetime,
        end: datetime,
        agent_id: Optional[UUID],
        limit: int = 10,
        account_id: Optional[UUID] = None,
    ) -> List[AgentStat]:
        conditions = [
            ChannelMessage.is_deleted == False,  # noqa: E712
            ChannelMessage.agent_id.isnot(None),
            ChannelMessage.created_at >= start,
            ChannelMessage.created_at < end,
        ]
        # P6AN-16: tenant sees only its own channel-message rows.
        if account_id is not None:
            conditions.append(ChannelMessage.account_id == account_id)
        if agent_id is not None:
            conditions.append(ChannelMessage.agent_id == agent_id)
            limit = 1

        grouped = (
            select(
                ChannelMessage.agent_id.label("agent_id"),
                func.count(ChannelMessage.id).label("messages"),
            )
            .where(and_(*conditions))
            .group_by(ChannelMessage.agent_id)
            .order_by(func.count(ChannelMessage.id).desc())
            .limit(limit)
        )
        rows = (await self.db.execute(grouped)).all()

        # Per-agent delivered/failed for the success rate (bounded dict of ids).
        # Postgres has no ``filter()`` aggregate helper — use
        # ``COUNT(CASE WHEN <cond> THEN 1 END)`` conditional counts.
        agent_ids = [r.agent_id for r in rows]
        rates: Dict[UUID, Optional[float]] = {}
        if agent_ids:
            delivered_case = case(
                (
                    or_(
                        ChannelMessage.status == "delivered",
                        ChannelMessage.status == "read",
                    ),
                    1,
                ),
                else_=None,
            )
            failed_case = case(
                (ChannelMessage.status == "failed", 1),
                else_=None,
            )
            rate_rows = (
                await self.db.execute(
                    select(
                        ChannelMessage.agent_id,
                        func.count(delivered_case).label("delivered"),
                        func.count(failed_case).label("failed"),
                    )
                    .where(
                        ChannelMessage.agent_id.in_(agent_ids),
                        ChannelMessage.is_deleted == False,  # noqa: E712
                        ChannelMessage.created_at >= start,
                        ChannelMessage.created_at < end,
                    )
                    .group_by(ChannelMessage.agent_id)
                )
            ).all()
            for rr in rate_rows:
                completed = int(rr.delivered) + int(rr.failed)
                rates[rr.agent_id] = (
                    round(int(rr.delivered) / completed, 4) if completed else None
                )

        # Agent names (one IN-query for the bounded set).
        names: Dict[UUID, Optional[str]] = {}
        if agent_ids:
            name_rows = (
                await self.db.execute(
                    select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
                )
            ).all()
            names = {r.id: r.name for r in name_rows}

        # Conversations per agent: distinct conversations that have at least
        # one in-window channel message from that agent.
        conv_counts: Dict[UUID, int] = {}
        if agent_ids:
            conv_rows = (
                await self.db.execute(
                    select(
                        ChannelMessage.agent_id,
                        func.count(func.distinct(ChannelMessage.conversation_id)),
                    )
                    .where(
                        ChannelMessage.agent_id.in_(agent_ids),
                        ChannelMessage.is_deleted == False,  # noqa: E712
                        ChannelMessage.created_at >= start,
                        ChannelMessage.created_at < end,
                    )
                    .group_by(ChannelMessage.agent_id)
                )
            ).all()
            conv_counts = {r[0]: int(r[1]) for r in conv_rows}

        return [
            AgentStat(
                agent_id=r.agent_id,
                agent_name=names.get(r.agent_id),
                conversations=conv_counts.get(r.agent_id, 0),
                messages=int(r.messages),
                message_success_rate=rates.get(r.agent_id),
            )
            for r in rows
        ]

    # ----- composition ------------------------------------------------------

    async def compute(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        days: int = 30,
        agent_id: Optional[UUID] = None,
        channel: Optional[str] = None,
        now: Optional[datetime] = None,
        account_id: Optional[UUID] = None,
    ) -> DashboardOverviewResponse:
        """Compute the full overview (no caching — the router owns that).

        P6AN-16: ``account_id`` (the caller's tenant, from the token) scopes
        every section to that tenant's visible data; ``None`` = unscoped
        (platform-wide actor).
        """
        days = max(1, min(int(days), 365))
        s, e, eff_days = _resolve_window(start, end, days, now=now)
        rng = DashboardRange(start=s, end=e, days=eff_days)

        agents = await self._agents(account_id)
        conversations = await self._conversations(s, e, agent_id, channel, account_id)
        messages = await self._messages(s, e, agent_id, channel, account_id)
        conversion = await self._conversion(s, e, agent_id, account_id)
        by_agent = await self._by_agent(s, e, agent_id, account_id=account_id)

        payload = DashboardOverviewResponse(
            range=rng,
            agents=agents,
            conversations=conversations,
            messages=messages,
            conversion=conversion,
            by_agent=by_agent,
            computed_at=datetime.now(timezone.utc),
        )
        logger.info(
            "dashboard overview computed: window=%s..%s days=%d agent=%s channel=%s "
            "agents=%d conv_new=%d msgs=%d leads_new=%d",
            s.date(), e.date(), eff_days, agent_id, channel,
            agents.total, conversations.new, messages.total, conversion.new_leads,
        )
        return payload
