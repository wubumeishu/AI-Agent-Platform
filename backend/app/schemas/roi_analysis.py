"""Pydantic schemas for the ROI Analysis endpoint (Phase 6 / P6AN-09).

``GET /api/v1/analytics/roi?dimension=agent|campaign|private-domain``

The response is a *uniform envelope* for all three dimensions so a single
client / dashboard can render any of them:

- ``summary``  — the aggregate ROI block for the requested scope. For
  ``agent`` / ``campaign`` this is the sum over the reported items (the
  ``summary == Σ items`` invariant); for ``private-domain`` it IS the whole
  answer (a single aggregate, so ``items`` is empty).
- ``items``    — per-entity (per-agent / per-campaign) ROI cells; empty for
  ``private-domain``.
- ``cost_rates`` + ``cost_basis_configured`` — an echo of the cost-proxy
  rates actually used, for transparency (the input side is a configurable
  proxy; a deployment that never sets a rate reports ``cost_basis_configured
  = false`` and every ``roi`` / ``roi_percent`` is ``None`` rather than a
  fabricated figure).

Caliber (full doc: ``docs/P6AN-09-roi-analysis-api.md``):
- **Output** = total won-deal value (``deal_item.value`` in cents, status
  ``won``) created in the window. ``ltv_proxy_cents_per_reached`` (value ÷
  distinct reached customers) is carried as *auxiliary context* — the same
  LTV proxy P6AN-06 documented.
- **Input** = an operations **cost proxy** = Σ(volume × per-unit rate) over
  observable activity (outbound messages / nurture executions / follow-up
  tasks / active agents / campaign leads). No finance system is wired up yet,
  so the rates are the only knobs; they are env-configurable and default to
  0 ("no cost basis configured").
- **ROI** = ``(output − input) / input``. When ``input == 0`` the ratio is
  *undefined*, not ``0``: both ``roi`` and ``roi_percent`` are ``None`` (the
  acceptance criterion "分母为 0 时安全处理"). ``net_cents`` (output − input)
  is always reported.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ROIFilters(BaseModel):
    """Query-param echo for ``GET /api/v1/analytics/roi``."""

    dimension: str = Field(..., description="agent | campaign | private-domain")
    agent_id: Optional[UUID] = None
    account_id: Optional[UUID] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None


class ROIWindow(BaseModel):
    """The effective time window actually queried (after defaults applied)."""

    since: datetime
    until: datetime
    default_applied: bool = Field(
        False,
        description="True when the caller supplied no since/until and the 30-day "
                    "default window was used.",
    )


class ROICostRates(BaseModel):
    """The cost-proxy rates used for this response (echoed for transparency).

    All values are **cents per unit**. ``configured`` is true when *any* rate
    is non-zero — i.e. a real cost basis was supplied by the deployment.
    """

    cost_per_outbound_message_cents: int = 0
    cost_per_nurture_execution_cents: int = 0
    cost_per_followup_task_cents: int = 0
    cost_per_active_agent_cents: int = 0
    cost_per_campaign_lead_cents: int = 0
    configured: bool = Field(
        False,
        description="True when at least one rate is non-zero (a cost basis is "
                    "configured). False -> every ROI ratio is None (undefined).",
    )


class ROIValue(BaseModel):
    """One ROI block (used by ``summary`` and by each ``item``)."""

    revenue_cents: int = Field(0, description="Output: total won-deal value in cents (window).")
    won_deal_count: int = Field(0, description="Number of distinct won deals counted into revenue.")
    input_cents: int = Field(0, description="Input: operations cost proxy (Σ volume × rate), in cents.")
    net_cents: int = Field(0, description="revenue − input (always reported, even when input=0).")
    roi: Optional[float] = Field(
        None,
        description="(revenue − input) / input. None when input == 0 (undefined, "
                    "NOT 0%). Rounded to 4 decimals.",
    )
    roi_percent: Optional[float] = Field(
        None, description="roi × 100 (None when roi is None). Rounded to 2 decimals."
    )
    # Auxiliary context (same LTV proxy P6AN-06 documented) — never used to
    # compute ROI itself, just reported for the caller's reference.
    ltv_proxy_cents_per_reached: float = Field(
        0.0,
        description="Auxiliary: total won value ÷ distinct reached customers. "
                    "Context only; ROI uses revenue (total won value) as output.",
    )
    reached_customers: int = Field(
        0, description="Distinct customers reached (outbound delivered) in window."
    )
    # Per-source transparency for the input side.
    activity: Dict[str, int] = Field(
        default_factory=dict,
        description="The activity volumes counted into the input side, e.g. "
                    "{'outbound_messages': 12, 'follow_up_tasks': 3}.",
    )
    input_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="Per-source input cost in cents (volume × rate), e.g. "
                    "{'outbound_messages': 240}.",
    )


class ROIItem(ROIValue):
    """A per-entity ROI cell (per-agent / per-campaign)."""

    entity_id: Optional[str] = Field(
        None, description="The entity's id (agent UUID, or campaign source_id)."
    )
    entity_label: Optional[str] = Field(
        None, description="The entity's human label (agent name, campaign id)."
    )


class ROIResponse(BaseModel):
    """Response envelope for ``GET /api/v1/analytics/roi``."""

    dimension: str
    window: ROIWindow
    filters: ROIFilters
    cost_rates: ROICostRates
    cost_basis_configured: bool = False
    summary: ROIValue
    items: List[ROIItem] = Field(default_factory=list)
