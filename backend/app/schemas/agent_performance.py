"""Pydantic schemas for the Agent Performance analytics surface (P6AN-07).

Phase-6 analytics card: agent-dimension KPIs (conversation volume, message
volume, lead conversion rate, satisfaction proxy, active time-of-day) plus an
agent leaderboard (configurable sort key / time range).

This is the *compute* layer on top of the P6AN-01 analytics foundation: it
aggregates over the Phase-1 resource layer (``agent`` / ``agent_customer_binding``),
Phase-2 conversation/message data, and Phase-4 CRM lead data. No new tables —
every metric is a live aggregation over existing entities, so there is nothing
to migrate (see the card's DoD: metric caliber is documented in
``docs/ANALYTICS-AGENT-PERFORMANCE.md``).

Conventions:
- All counts are int; rates / proxies are float in [0, 1] (``None`` when the
  denominator is empty, so callers can distinguish "no data" from "0").
- Leaderboard ranking re-uses the same scalar values but substitutes ``0.0``
  for a null rate so ordering is deterministic (documented in the router).
"""
from __future__ import annotations

from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ----- Sort / order value domains (shared by schema + router validation) -----
LEADERBOARD_SORT_KEYS = (
    "conversations",
    "messages",
    "activity",
    "conversion_rate",
    "satisfaction",
    "customers",
    "name",
    "created_at",
)
LEADERBOARD_ORDERS = ("asc", "desc")


class AgentPerformanceMetrics(BaseModel):
    """Per-agent KPI block (windowed unless noted).

    All time-windowed counts use the request's ``range`` window. The
    ``*customers`` figures are *all-time* (not windowed) because a customer's
    tenure is not meaningful within a short activity window.
    """

    agent_id: UUID
    agent_name: str
    status: Optional[str] = Field(
        None, description="Agent status (active / inactive / paused)."
    )

    # ----- volume (all-time, live bindings) -----
    total_customers: int = Field(0, description="All-time customers bound to this agent (live).")
    active_customers: int = Field(
        0,
        description="Customers with at least one live, non-terminal lead (all-time).",
    )

    # ----- windowed activity -----
    conversation_count: int = Field(0, description="Conversations in window belonging to the agent's customers.")
    message_count: int = Field(0, description="Messages in window within those conversations.")
    lead_count: int = Field(0, description="Leads created in window for the agent's customers.")
    converted_lead_count: int = Field(
        0,
        description="Leads in window that reached a converted / won stage.",
    )
    conversion_rate: Optional[float] = Field(
        None,
        description="converted_lead_count / lead_count in [0,1]; None when lead_count == 0.",
    )

    # ----- windowed satisfaction proxy -----
    # Conversation.sentiment ∈ {positive, neutral, negative}; score map
    # positive=1.0, neutral=0.5, negative=0.0; average over conversations that
    # carry a sentiment. Null when no sentiment-carrying conversation exists.
    satisfaction_proxy: Optional[float] = Field(
        None, description="Mean sentiment score in [0,1]; None when no sentiment data in window."
    )
    satisfaction_sample: int = Field(
        0, description="Number of window conversations that carry a sentiment value."
    )
    sentiment_breakdown: Dict[str, int] = Field(
        default_factory=lambda: {"positive": 0, "neutral": 0, "negative": 0},
        description="Window sentiment counts by label.",
    )

    # ----- windowed active time-of-day (UTC hour histogram over messages) -----
    active_hours: List[int] = Field(
        default_factory=lambda: [0] * 24,
        description="24 buckets of message volume by UTC hour-of-day in the window.",
    )
    peak_hour: Optional[int] = Field(
        None,
        description="UTC hour (0-23) with the most messages; None when no messages in window.",
    )


class AgentPerformanceResponse(BaseModel):
    """Envelope for a single agent's performance (also used per row of the leaderboard)."""

    metrics: AgentPerformanceMetrics
    window: Dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="ISO-8601 window actually applied (since / until), or {'range': preset} for all-time.",
    )


class AgentPerformanceLeaderboardResponse(BaseModel):
    """Configurable agent leaderboard (P6AN-07 goal: 活跃排名)."""

    items: List[AgentPerformanceMetrics]
    total_agents: int = Field(
        ...,
        description="Number of live agents matched by the filters (before paging).",
    )
    sort_key: str = Field("conversations", description="Sort key actually applied.")
    order: str = Field("desc", description="Sort direction actually applied.")
    page: int
    page_size: int
    window: Dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="ISO-8601 window actually applied (since / until), or {'range': preset} for all-time.",
    )


class AgentPerformanceSingleResponse(AgentPerformanceMetrics):
    """Convenience alias for ``GET /agents/{id}/performance`` (bare KPI block)."""
