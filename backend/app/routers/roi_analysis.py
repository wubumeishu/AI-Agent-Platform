"""ROI Analysis endpoint (Phase 6 / P6AN-09).

Single read-only endpoint::

    GET /api/v1/analytics/roi
        ?dimension=agent|campaign|private-domain
        [&agent_id=<uuid>&account_id=<uuid>&since=<iso8601>&until=<iso8601>]

Computes 投入产出 ROI (output = won-deal value; input = a configurable
operations cost-proxy) across three dimensions:

- ``agent``          per-agent ROI (revenue via agent_customer_binding)
- ``campaign``       per-campaign ROI (leads with source_type='campaign',
                     revenue via the deal_item.lead_id link)
- ``private-domain`` a single account-scoped aggregate

The router self-carries its full ``/api/v1/analytics/roi`` prefix and is
therefore mounted BARE in ``main.py`` (the P6AN-06 / P6AN-07 convention —
mounting it under an outer ``/api/v1`` would double the prefix, the same
class of defect as the P1-2 CRM bug). It rides on the P6AN-01 analytics
surface but is a separate module so the CRUD definitions layer and this
computation layer stay decoupled.

Error semantics:
- 422 on an unknown ``dimension``, an unparseable ``since`` / ``until``, or a
  malformed ``agent_id`` / ``account_id`` (clean, never a mid-DB 500).
- A zero input (no cost basis configured, or no observable activity) is **not**
  an error: every ``roi`` / ``roi_percent`` is ``None`` (undefined) and the
  response still carries the revenue + ``net_cents``.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.config import roi_cost_rates
from app.db.session import get_db
from app.schemas.roi_analysis import ROIResponse
from app.services.roi_analysis import DIMENSIONS, ROIService

router = APIRouter(
    prefix="/api/v1/analytics/roi",
    tags=["Analytics - ROI"],
)


def _parse_window_bound(name: str, value: Optional[str]) -> Optional[datetime]:
    """Parse an optional ISO-8601 window bound into a datetime (422 on bad).

    A trailing ``Z`` is normalised to ``+00:00`` for ``fromisoformat``; naive
    values are treated as UTC downstream by the service's window resolution.
    """
    if value is None or value.strip() == "":
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid ISO-8601 timestamp {value!r} for the time window "
                f"({name}). Expected e.g. 2026-08-01T00:00:00Z."
            ),
        )


@router.get("", response_model=ROIResponse)
async def get_roi(
    dimension: str = Query(
        "private-domain",
        pattern="^(agent|campaign|private-domain)$",
        description="ROI dimension: agent | campaign | private-domain.",
    ),
    agent_id: Optional[UUID] = Query(
        None,
        description="For the ``agent`` dimension: narrow the report to this one "
                    "agent. Ignored by the other dimensions.",
    ),
    account_id: Optional[UUID] = Query(
        None,
        description="For the ``private-domain`` dimension: scope the aggregate to "
                    "one account. Omit for all accounts.",
    ),
    since: Optional[str] = Query(
        None,
        description="UTC window start, inclusive (ISO-8601). Omitted -> the window "
                    "defaults to the last 30 days.",
    ),
    until: Optional[str] = Query(
        None,
        description="UTC window end, exclusive (ISO-8601). Omitted -> the window "
                    "defaults to the last 30 days.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Compute the ROI report for one dimension (read-only aggregation).

    Output = total won-deal value in the window; input = a configurable
    operations cost-proxy (env rates via ``roi_cost_rates``). The data口径 is
    documented in ``docs/P6AN-09-roi-analysis-api.md``. No write, no new
    table — it aggregates the existing Phase-4 / Phase-5 source tables.
    """
    if dimension not in DIMENSIONS:
        # The Query pattern normally rejects this; keep a service-side guard so
        # a programmatic caller can never slip an unknown dimension through.
        raise HTTPException(
            status_code=422,
            detail=f"Unknown dimension {dimension!r}; expected one of {list(DIMENSIONS)}.",
        )

    since_dt = _parse_window_bound("since", since)
    until_dt = _parse_window_bound("until", until)

    svc = ROIService(db)
    return await svc.get_roi(
        dimension=dimension,
        agent_id=agent_id,
        account_id=account_id,
        since=since_dt,
        until=until_dt,
        rates=roi_cost_rates(),
    )


__all__ = ["router", "get_roi"]
