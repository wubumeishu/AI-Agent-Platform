"""Private-Domain Conversion analytics service (Phase 6 / P6AN-06).

Read-only aggregation that turns the Phase-5 private-domain source tables into
the customer funnel (触达 reach → 互动 interact → 成交 convert), an LTV proxy,
and the completion rates P6AN-09 (ROI) needs. It owns **no tables** — it rides
on the P6AN-01 analytics router prefix and the existing Phase-5 ORM models — so
there is no migration on this card.

Layering (API → Service → DB)
------------------------------
- ``PrivateDomainConversionService.collect_raw`` runs a small set of focused,
  对拍-able aggregate queries (one per metric family) and returns a flat dict
  of raw counts/sums. Each query is deliberately simple so a QA reviewer can
  cross-check it by hand against the documented口径.
- ``PrivateDomainConversionService._assemble`` (a *pure* function of the raw
  dict + the effective window) turns those raw numbers into the ``PDCResponse``.
  Keeping the math pure means the rate/rounding/div-by-zero guards are
  unit-testable with no database, and the SQL layer is testable on a live PG
  test DB — the two concerns stay decoupled.

口径 (documented in ``docs/P6AN-06-private-domain-conversion-api.md``)
----------------------------------------------------------------------
- **Window anchor = record ``created_at``** for every source table (uniform,
  non-null, easily对拍'd). The window is ``since`` (inclusive) .. ``until``
  (exclusive). If the caller supplies neither, a 30-day default is applied.
- **Reach** = distinct customers with ≥1 *outbound* private-channel message
  (``messages.direction='out'``) whose delivery is not failed/queued
  (``status IN (sent, delivered, read)``), created in the window.
- **Interact** = distinct customers with ≥1 *inbound* message
  (``direction='in'``) created in the window.
- **Convert** = distinct customers with ≥1 ``won`` deal created in the window.
- **Base** = the scope population: customers bound to ``agent_id`` when an
  agent filter is set, else all live customers.
- **LTV proxy** = value-per-reached-customer over the window
  (``total_won_value_cents / reached_customers``); the single-transaction
  amount (金额/次数) is ``total_won_value_cents / won_deal_count``.
- **NurturePlan execution** = success rate of ``nurture_step_execution``
  attempts (scoped by account only — step rows carry no customer/agent link).
- **FollowUpTask completion** = completed/total for tasks created in the window
  (scoped by account).

Scoping rules: the *customer funnel + LTV* respect both ``agent_id`` (via
``agent_customer_binding``) and ``account_id``; the *nurture + follow-up*
completion rates respect ``account_id`` only (their source rows have no agent
link), and so are unaffected by the agent filter. This is intentional and
documented, not an oversight.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import AgentCustomerBinding
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.messages import ChannelMessage
from app.db.models.nurture_execution import NurtureStepExecution
from app.db.models.private_domain import DealItem, FollowUpTask

logger = logging.getLogger(__name__)

#: Delivery states that mean an outbound message actually reached the customer.
#: ``queued`` (not yet dispatched) and ``failed`` (never reached) are excluded.
_REACHED_MESSAGE_STATUSES = ("sent", "delivered", "read")

#: Default window (days) applied when the caller supplies no since/until.
DEFAULT_WINDOW_DAYS = 30


def _pct(numerator: int, denominator: int) -> float:
    """``numerator / denominator * 100`` rounded to 2 decimals; 0.0 when the
    denominator is 0 (never a division error). Pure — unit-testable."""
    if not denominator:
        return 0.0
    return round(numerator * 100.0 / denominator, 2)


def _coerce_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Attach UTC to a naive datetime (query params may arrive naive)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class PrivateDomainConversionService:
    """Computes the private-domain conversion funnel + LTV proxy + completion
    rates. Depends only on an ``AsyncSession`` so it is testable against a
    live PG test DB (SQL layer) or via the pure ``_assemble`` (math layer).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # window resolution
    # ------------------------------------------------------------------
    def _resolve_window(self, since: Optional[datetime], until: Optional[datetime]
                       ) -> tuple[datetime, datetime, bool]:
        """Return ``(since, until, default_applied)`` with an effective window.

        Rules:
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

    # ------------------------------------------------------------------
    # raw aggregate collection (the SQL / 对拍-able layer)
    # ------------------------------------------------------------------
    async def collect_raw(
        self,
        agent_id: Optional[UUID],
        account_id: Optional[UUID],
        since: datetime,
        until: datetime,
    ) -> Dict[str, Any]:
        """Run the per-metric aggregate queries and return a flat raw dict.

        The dict keys are the raw counts/sums; ``_assemble`` turns them into
        the response. Every query is a single focused aggregate so it maps
        one-to-one to the documented SQL口径.
        """
        db = self.db
        raw: Dict[str, Any] = {}

        # ---- base population (denominator of the funnel) ----
        if agent_id is not None:
            base_q = (
                select(func.count(func.distinct(AgentCustomerBinding.customer_id)))
                .where(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.is_deleted == False,  # noqa: E712
                )
            )
        else:
            base_q = (
                select(func.count(func.distinct(Customer.id)))
                .where(Customer.is_deleted == False)  # noqa: E712
            )
        raw["base_customers"] = int((await db.execute(base_q)).scalar() or 0)

        # ---- reached / interacted (distinct customers via messages) ----
        raw["reached_customers"] = await self._distinct_reached(
            agent_id, account_id, since, until, outbound=True
        )
        raw["interacted_customers"] = await self._distinct_reached(
            agent_id, account_id, since, until, outbound=False
        )

        # ---- converted (distinct customers with a won deal) ----
        raw["converted_customers"] = await self._distinct_converted(
            agent_id, account_id, since, until
        )

        # ---- LTV proxy (won-deal value) ----
        ltv_q = (
            select(
                func.count(DealItem.id),
                func.coalesce(func.sum(DealItem.value), 0),
            )
            .where(
                DealItem.is_deleted == False,  # noqa: E712
                DealItem.status == "won",
                DealItem.created_at >= since,
                DealItem.created_at < until,
            )
        )
        if agent_id is not None:
            ltv_q = ltv_q.where(DealItem.customer_id.is_not(None))
        if account_id is not None:
            ltv_q = ltv_q.where(DealItem.account_id == account_id)
        # Agent scoping: only deals whose customer is bound to the agent.
        if agent_id is not None:
            bound = (
                select(AgentCustomerBinding.customer_id)
                .where(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.is_deleted == False,  # noqa: E712
                )
                .subquery()
            )
            ltv_q = ltv_q.where(DealItem.customer_id.in_(select(bound)))
        row = (await db.execute(ltv_q)).one()
        raw["won_deal_count"] = int(row[0] or 0)
        raw["total_won_value_cents"] = int(row[1] or 0)
        raw["ltv_currencies"] = await self._won_currencies(account_id, since, until)

        # ---- NurturePlan execution completion (account-scoped only) ----
        nse_q = select(NurtureStepExecution.status, func.count(NurtureStepExecution.id))
        nse_q = nse_q.where(
            NurtureStepExecution.is_deleted == False,  # noqa: E712
            NurtureStepExecution.created_at >= since,
            NurtureStepExecution.created_at < until,
        )
        if account_id is not None:
            nse_q = nse_q.where(NurtureStepExecution.account_id == account_id)
        nse_q = nse_q.group_by(NurtureStepExecution.status)
        nse_rows = (await db.execute(nse_q)).all()
        by_status: Dict[str, int] = {}
        for status, cnt in nse_rows:
            by_status[str(status)] = int(cnt or 0)
        executed = sum(
            c for s, c in by_status.items() if s not in ("pending", "running")
        )
        raw["nse_success_attempts"] = by_status.get("success", 0)
        raw["nse_executed_attempts"] = executed

        # ---- FollowUpTask completion (account-scoped only) ----
        fu_q = select(FollowUpTask.status, func.count(FollowUpTask.id))
        fu_q = fu_q.where(
            FollowUpTask.is_deleted == False,  # noqa: E712
            FollowUpTask.created_at >= since,
            FollowUpTask.created_at < until,
        )
        if account_id is not None:
            fu_q = fu_q.where(FollowUpTask.account_id == account_id)
        fu_q = fu_q.group_by(FollowUpTask.status)
        fu_rows = (await db.execute(fu_q)).all()
        fu_by_status: Dict[str, int] = {str(s): int(c or 0) for s, c in fu_rows}
        raw["fu_completed"] = fu_by_status.get("completed", 0)
        raw["fu_total"] = sum(fu_by_status.values())

        return raw

    # --- helper: distinct customers reached/interacted via messages ---
    async def _distinct_reached(
        self,
        agent_id: Optional[UUID],
        account_id: Optional[UUID],
        since: datetime,
        until: datetime,
        outbound: bool,
    ) -> int:
        direction = "out" if outbound else "in"
        # Join to the owning conversation so the DISTINCT targets
        # conversation.customer_id (one customer may have many messages).
        q = (
            select(func.count(func.distinct(Conversation.customer_id)))
            .select_from(ChannelMessage)
            .join(
                Conversation,
                Conversation.id == ChannelMessage.conversation_id,
            )
            .where(
                ChannelMessage.is_deleted == False,  # noqa: E712
                Conversation.is_deleted == False,  # noqa: E712
                Conversation.customer_id.is_not(None),
                ChannelMessage.direction == direction,
                ChannelMessage.created_at >= since,
                ChannelMessage.created_at < until,
            )
        )
        if outbound:
            q = q.where(ChannelMessage.status.in_(_REACHED_MESSAGE_STATUSES))
        if account_id is not None:
            q = q.where(ChannelMessage.account_id == account_id)
        if agent_id is not None:
            bound = (
                select(AgentCustomerBinding.customer_id)
                .where(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.is_deleted == False,  # noqa: E712
                )
                .subquery()
            )
            q = q.where(Conversation.customer_id.in_(select(bound)))

        return int((await self.db.execute(q)).scalar() or 0)

    # --- helper: distinct customers with a won deal ---
    async def _distinct_converted(
        self,
        agent_id: Optional[UUID],
        account_id: Optional[UUID],
        since: datetime,
        until: datetime,
    ) -> int:
        q = (
            select(func.count(func.distinct(DealItem.customer_id)))
            .where(
                DealItem.is_deleted == False,  # noqa: E712
                DealItem.status == "won",
                DealItem.customer_id.is_not(None),
                DealItem.created_at >= since,
                DealItem.created_at < until,
            )
        )
        if account_id is not None:
            q = q.where(DealItem.account_id == account_id)
        if agent_id is not None:
            bound = (
                select(AgentCustomerBinding.customer_id)
                .where(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.is_deleted == False,  # noqa: E712
                )
                .subquery()
            )
            q = q.where(DealItem.customer_id.in_(select(bound)))
        return int((await self.db.execute(q)).scalar() or 0)

    # --- helper: which currencies contributed to won-deal value ---
    async def _won_currencies(
        self, account_id: Optional[UUID], since: datetime, until: datetime
    ) -> list:
        q = (
            select(DealItem.currency)
            .where(
                DealItem.is_deleted == False,  # noqa: E712
                DealItem.status == "won",
                DealItem.created_at >= since,
                DealItem.created_at < until,
            )
            .distinct()
            .order_by(DealItem.currency)
        )
        if account_id is not None:
            q = q.where(DealItem.account_id == account_id)
        rows = (await self.db.execute(q)).scalars().all()
        return [c for c in rows if c]

    # ------------------------------------------------------------------
    # pure assembly (the math / rounding / div-by-zero layer)
    # ------------------------------------------------------------------
    @staticmethod
    def assemble(
        raw: Dict[str, Any],
        agent_id: Optional[UUID],
        account_id: Optional[UUID],
        since: datetime,
        until: datetime,
        default_applied: bool,
    ) -> Dict[str, Any]:
        """Turn the raw aggregate dict into the response payload (pure)."""
        from app.schemas.private_domain_conversion import (
            PDCFollowUp,
            PDCFunnel,
            PDCNurtureExecution,
            PDCROIInputs,
            PDCResponse,
            PDCWindow,
            PCTLV,
        )

        base = int(raw.get("base_customers", 0))
        reached = int(raw.get("reached_customers", 0))
        interacted = int(raw.get("interacted_customers", 0))
        converted = int(raw.get("converted_customers", 0))

        funnel = PDCFunnel(
            base_customers=base,
            reached_customers=reached,
            interacted_customers=interacted,
            converted_customers=converted,
            reach_rate_percent=_pct(reached, base),
            interaction_rate_percent=_pct(interacted, reached),
            conversion_rate_percent=_pct(converted, interacted),
            reach_rate_overall_percent=_pct(reached, base),
            interaction_rate_overall_percent=_pct(interacted, base),
            conversion_rate_overall_percent=_pct(converted, base),
        )

        won_count = int(raw.get("won_deal_count", 0))
        won_value = int(raw.get("total_won_value_cents", 0))
        ltv = PCTLV(
            won_deal_count=won_count,
            total_won_value_cents=won_value,
            avg_won_deal_value_cents=round(won_value / won_count, 2) if won_count else 0.0,
            ltv_proxy_cents_per_reached=round(won_value / reached, 2) if reached else 0.0,
            currencies=list(raw.get("ltv_currencies") or []),
        )

        nse_success = int(raw.get("nse_success_attempts", 0))
        nse_executed = int(raw.get("nse_executed_attempts", 0))
        nurture = PDCNurtureExecution(
            success_attempts=nse_success,
            executed_attempts=nse_executed,
            execution_rate_percent=_pct(nse_success, nse_executed),
        )

        fu_completed = int(raw.get("fu_completed", 0))
        fu_total = int(raw.get("fu_total", 0))
        follow_up = PDCFollowUp(
            completed=fu_completed,
            total=fu_total,
            completion_rate_percent=_pct(fu_completed, fu_total),
        )

        roi = PDCROIInputs(
            total_won_value_cents=won_value,
            won_deal_count=won_count,
            reached_customers=reached,
            base_customers=base,
            ltv_proxy_cents_per_reached=ltv.ltv_proxy_cents_per_reached,
        )

        return PDCResponse(
            window=PDCWindow(since=since, until=until, default_applied=default_applied),
            agent_id=agent_id,
            account_id=account_id,
            funnel=funnel,
            ltv=ltv,
            nurture_execution=nurture,
            follow_up=follow_up,
            roi_inputs=roi,
        ).model_dump()

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------
    async def get_conversion(
        self,
        agent_id: Optional[UUID] = None,
        account_id: Optional[UUID] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Compute the full private-domain conversion payload."""
        win_since, win_until, default_applied = self._resolve_window(since, until)
        raw = await self.collect_raw(agent_id, account_id, win_since, win_until)
        return self.assemble(
            raw, agent_id, account_id, win_since, win_until, default_applied
        )


__all__ = [
    "PrivateDomainConversionService",
    "_pct",
    "_coerce_aware",
    "DEFAULT_WINDOW_DAYS",
    "_REACHED_MESSAGE_STATUSES",
]
