"""P6AN-05 Lead Conversion API schemas.

Response model for ``GET /api/v1/analytics/leads/conversion``.
Mirrors the dict shape produced by
:class:`app.services.lead_conversion_service.LeadConversionService`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class LeadConversionMetrics(BaseModel):
    """Metric block for one cohort (overall totals or one group)."""

    total_leads: int = Field(0, description="Number of distinct leads in the cohort")
    status_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Distinct lead count per status (funnel position)",
    )
    stage_reached_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Distinct leads that have reached each funnel stage "
        "(new / contacted / qualified / converted)",
    )
    conversion_rates: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="Step + overall rates. Values 0.0-1.0; null when the "
        "denominator stage is empty (no data, not 0%)",
    )
    avg_conversion_cycle_days: Optional[float] = Field(
        None,
        description="Mean days from lead.created_at to conversion "
        "(earliest 成交 stage log, else lead.updated_at); null when no "
        "converted leads",
    )


class LeadConversionGroup(BaseModel):
    key: str = Field(..., description="Agent name or lower-cased channel code")
    label: str
    metrics: LeadConversionMetrics


class LeadConversionFilters(BaseModel):
    agent_id: Optional[str] = None
    channel: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    group_by: str = "overall"
    window_basis: str = "lead.created_at"


class LeadConversionResponse(BaseModel):
    filters: LeadConversionFilters
    totals: LeadConversionMetrics
    groups: List[LeadConversionGroup] = Field(
        default_factory=list,
        description="Empty when group_by=overall",
    )
