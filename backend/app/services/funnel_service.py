"""Acquisition funnel computation (Phase 6 / P6AN-03).

Computes per-stage conversion volumes and rates for the acquisition funnel
(``new -> contacted -> qualified -> converted``) from ``Lead`` lifecycle
data, with optional agent / platform / time-range filtering.

``FunnelStep`` *definitions* (CRUD) were shipped by P6AN-01
(``funnel_step`` table + ``/analytics/funnel-steps``). This module is the
*compute* layer: when a registered custom ``funnel_code`` is supplied it
reads those step definitions to drive stage order, but the numbers always
come from ``Lead`` rows, not from the definition catalog. Keeping the two
separate means the catalog can register stages the data layer does not yet
track without the funnel endpoint returning 500.

Stage semantics ("reached" / cumulative)
----------------------------------------
A lead currently in stage ``s`` is counted as having *reached* every stage
at or before ``s`` in the funnel order. So for the built-in acquisition
stages ``[new, contacted, qualified, converted]``:

    reached(converted)   = leads whose status == 'converted'
    reached(qualified)   = leads whose status in ('qualified', 'converted')
    reached(contacted)   = leads whose status in ('contacted', 'qualified', 'converted')
    reached(new)         = total live leads (every lead entered at 'new')

This is the classic funnel view: each stage's "reached" count is cumulative,
so stage-to-stage conversion rates are well-defined and monotone.

Per-stage rates (``None`` when the denominator is zero -- no 0/0, no crash):

    conversion_rate = reached(this) / reached(previous)   # adjacent stage
    overall_rate    = reached(this) / reached(top)         # end-to-end

Filters
-------
* ``agent_id`` (UUID ``agent.id``): restricts to leads whose customer is
  bound to that agent (``agent_customer_binding``).
* ``platform_id`` (UUID ``platform.id``): restricts to leads whose customer
  is bound to an agent operating under an account of that platform
  (``platform -> account -> agent_persona_binding -> agent_customer_binding``).
  When both are supplied they are ANDed.
* ``range`` (``7d``/``30d``/``90d``/``365d``/``all``) sets the lead-entry
  window on ``lead.created_at`` (UTC). Explicit ``from_date``/``to_date``
  override the range window.

Every filter is composed into a single ``GROUP BY status`` query, so a
request is O(1) lead queries regardless of how many filters are supplied.
An empty result set yields a funnel whose stages all report ``count=0`` and
rates ``None`` -- the endpoint returns 200 with an empty funnel, never a 500.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import Account, AgentPersonaBinding
from app.db.models.agent import AgentCustomerBinding
from app.db.models.analytics import FunnelStep
from app.db.models.lead import Lead

logger = logging.getLogger(__name__)

# The built-in acquisition funnel (matches VALID_STATUS_TRANSITIONS in
# app.crm.services.lead). Ordered least -> most advanced; a lead in a later
# stage has "reached" every earlier stage.
DEFAULT_FUNNEL_CODE = "acquisition"
ACQUISITION_STAGES: Tuple[Tuple[str, str], ...] = (
    ("new", "New"),
    ("contacted", "Contacted"),
    ("qualified", "Qualified"),
    ("converted", "Converted"),
)

# Accepted ``range`` presets -> days. ``all`` means no window.
RANGE_PRESETS: Dict[str, Optional[int]] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "365d": 365,
    "all": None,
}
DEFAULT_RANGE = "30d"


@dataclass
class _Stage:
    """One resolved funnel stage (order position + the status it maps to)."""

    key: str
    name: str
    status: Optional[str]  # None => no resolvable Lead.status; reports 0


@dataclass
class _FunnelCtx:
    """Everything the count query needs for one funnel request."""

    stages: List[_Stage]
    funnel_code: str
    filters: Dict[str, Any]
    start: Optional[datetime]
    end: Optional[datetime]


def _parse_range_days(range_value: Optional[str]) -> Optional[int]:
    """Resolve a ``range`` preset to a day count (None = no window).

    Unknown values fall back to the default rather than raising, so the
    endpoint degrades to a sensible window instead of a 4xx on a typo.
    """
    if not range_value:
        return RANGE_PRESETS[DEFAULT_RANGE]
    return RANGE_PRESETS.get(range_value.strip().lower(), RANGE_PRESETS[DEFAULT_RANGE])


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 (or date-only) string to a naive-UTC datetime.

    ``Lead.created_at`` is a naive-UTC column (``datetime.utcnow`` default),
    so the bounds are kept naive-UTC to stay comparable in the DB without a
    timezone-cast failure.
    """
    if not value:
        return None
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _stages_from_funnel_steps(steps: List[Any]) -> List[_Stage]:
    """Build ordered stages from a set of ``funnel_step`` rows (by seq).

    A step's status comes from ``config.status`` (falling back to
    ``entry_criteria.status``). A step with no resolvable status is kept in
    order but reports a zero count.
    """
    stages: List[_Stage] = []
    for step in sorted(steps, key=lambda s: s.seq):
        status: Optional[str] = None
        cfg = step.config or {}
        if isinstance(cfg, dict) and cfg.get("status"):
            status = str(cfg["status"])
        if status is None:
            ec = step.entry_criteria or {}
            if isinstance(ec, dict) and ec.get("status"):
                status = str(ec["status"])
        stages.append(_Stage(key=step.name, name=step.name, status=status))
    return stages


async def _load_stages(db: AsyncSession, funnel_code: Optional[str]) -> List[_Stage]:
    """Resolve the ordered stage list for a request.

    * ``funnel_code`` is None / the default code -> the built-in acquisition
      stages (guaranteed, never empty).
    * a registered custom code -> its live ``funnel_step`` rows in ``seq``
      order. If none are registered, fall back to the built-in stages so the
      endpoint still returns a well-formed (default) funnel instead of 500.
    """
    code = funnel_code or DEFAULT_FUNNEL_CODE
    if funnel_code is None or funnel_code == DEFAULT_FUNNEL_CODE:
        return [_Stage(key=k, name=n, status=k) for k, n in ACQUISITION_STAGES]
    rows = (
        await db.execute(
            select(FunnelStep)
            .where(
                FunnelStep.funnel_code == code,
                FunnelStep.is_deleted == False,  # noqa: E712
            )
            .order_by(FunnelStep.seq.asc())
        )
    ).scalars().all()
    stages = _stages_from_funnel_steps(list(rows))
    return stages or [_Stage(key=k, name=n, status=k) for k, n in ACQUISITION_STAGES]


def _lead_customer_subquery(agent_id: Optional[UUID], platform_id: Optional[UUID]):
    """Return a scalar subquery of in-scope customer ids, or None (all).

    Both filters compose onto the same ``agent_customer_binding`` row set:
    agent -> that agent's bindings; platform -> bindings of agents that
    operate under an account of the platform. ANDed when both are supplied.
    """
    if agent_id is None and platform_id is None:
        return None

    preds: List[Any] = []
    if agent_id is not None:
        preds.append(AgentCustomerBinding.agent_id == agent_id)
    if platform_id is not None:
        platform_agents = (
            select(AgentPersonaBinding.agent_id)
            .where(
                AgentPersonaBinding.account_id.in_(
                    select(Account.id).where(
                        Account.platform_id == platform_id,
                        Account.is_deleted == False,  # noqa: E712
                    )
                )
            )
        )
        preds.append(AgentCustomerBinding.agent_id.in_(platform_agents))
    preds.append(AgentCustomerBinding.is_deleted == False)  # noqa: E712
    return select(AgentCustomerBinding.customer_id).where(and_(*preds))


async def _count_reached_by_stage(
    db: AsyncSession, ctx: _FunnelCtx, agent_id: Optional[UUID], platform_id: Optional[UUID]
) -> Dict[str, int]:
    """Single GROUP BY over in-scope live leads -> "reached" count per stage.

    Returns ``{stage.key: reached_count}``. The reached count for a stage is
    the sum of leads whose status is at-or-past that stage on the ladder.
    """
    q = select(Lead.status, func.count(Lead.id)).where(
        Lead.is_deleted == False  # noqa: E712
    )
    cust = _lead_customer_subquery(agent_id, platform_id)
    if cust is not None:
        q = q.where(Lead.customer_id.in_(cust))
    if ctx.start is not None:
        q = q.where(Lead.created_at >= ctx.start)
    if ctx.end is not None:
        q = q.where(Lead.created_at < ctx.end)

    counts: Dict[str, int] = {
        status: int(n) for status, n in (await db.execute(q.group_by(Lead.status))).all()
    }
    return _reached_from_counts(ctx.stages, counts)


def _reached_from_counts(stages: List[_Stage], counts: Dict[str, int]) -> Dict[str, int]:
    """Pure reached-math: given the ordered stages and a status->count map,
    return ``{stage.key: reached}``.

    A lead at the most-advanced status present counts toward every stage at
    or before it. This is the testable core of the funnel computation -- the
    SQL layer only produces the raw status counts; all rate math happens here
    so it can be 对撞 (cross-checked) without a live DB.
    """
    # Ordered, de-duplicated status ladder (later index = more advanced).
    ladder: List[str] = []
    for s in stages:
        if s.status and s.status not in ladder:
            ladder.append(s.status)
    # suffix[i] = sum of counts for ladder[i:]
    suffix: List[int] = []
    running = 0
    for status in reversed(ladder):
        running += counts.get(status, 0)
        suffix.append(running)
    suffix.reverse()  # now suffix[i] == total of ladder[i:]

    reached: Dict[str, int] = {}
    for s in stages:
        if s.status:
            reached[s.key] = suffix[ladder.index(s.status)]
        else:
            reached[s.key] = 0
    return reached


async def compute_funnel(
    db: AsyncSession,
    *,
    agent_id: Optional[UUID] = None,
    platform_id: Optional[UUID] = None,
    range: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    funnel_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute per-stage funnel counts + conversion rates.

    Returns a JSON-ready dict with:

    * ``stages``: ordered list, each ``{key, name, status, count,
      conversion_rate, overall_rate}``.
    * ``total``: the top-of-funnel "reached" count (0 when empty).
    * ``conversion_rate``: end-to-end top->bottom rate (None when empty).
    * ``filters``: the normalized request filters (for audit/UI echo).

    Empty input -> every stage ``count=0`` and rates ``None``; never raises.
    """
    days = _parse_range_days(range)
    start = _parse_date(from_date)
    end = _parse_date(to_date)
    if start is None and days is not None:
        start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    stages = await _load_stages(db, funnel_code)
    code = funnel_code or DEFAULT_FUNNEL_CODE
    ctx = _FunnelCtx(
        stages=stages,
        funnel_code=code,
        filters={
            "agent_id": str(agent_id) if agent_id else None,
            "platform_id": str(platform_id) if platform_id else None,
            "range": range or DEFAULT_RANGE,
            "from": start.isoformat() if start else None,
            "to": end.isoformat() if end else None,
        },
        start=start,
        end=end,
    )
    reached = await _count_reached_by_stage(db, ctx, agent_id, platform_id)
    return _assemble(ctx, reached)


def _assemble(ctx: _FunnelCtx, reached: Dict[str, int]) -> Dict[str, Any]:
    """Turn the reached-count map into the JSON funnel response."""
    top = reached.get(ctx.stages[0].key, 0) if ctx.stages else 0
    stages_out: List[Dict[str, Any]] = []
    prev_reached: Optional[int] = None
    for i, s in enumerate(ctx.stages):
        cnt = reached.get(s.key, 0)
        conv_rate: Optional[float] = None
        overall_rate: Optional[float] = None
        if i > 0 and prev_reached:
            conv_rate = round(cnt / prev_reached, 4)
        if top:
            overall_rate = round(cnt / top, 4)
        stages_out.append(
            {
                "key": s.key,
                "name": s.name,
                "status": s.status,
                "count": cnt,
                "conversion_rate": conv_rate,
                "overall_rate": overall_rate,
            }
        )
        prev_reached = cnt
    bottom = reached.get(ctx.stages[-1].key, 0) if ctx.stages else 0
    end_to_end = round(bottom / top, 4) if top and ctx.stages else None
    return {
        "funnel_code": ctx.funnel_code,
        "stages": stages_out,
        "total": top,
        "conversion_rate": end_to_end,
        "filters": ctx.filters,
    }


def funnel_summary(funnel: Dict[str, Any]) -> Dict[str, Any]:
    """A compact one-line digest (used in tests / log summaries)."""
    stages = {s["key"]: s["count"] for s in funnel.get("stages", [])}
    return {"funnel": funnel.get("funnel_code"), "stages": stages, "total": funnel.get("total")}
