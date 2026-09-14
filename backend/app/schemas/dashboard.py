"""Dashboard overview response schemas (Phase 6 / P6AN-02).

The overview endpoint returns one stable, flat schema consumed by the
frontend Dashboard and by external integrations. All ratio fields are
nullable (``None``) when the denominator is zero — the payload never
contains ``Infinity`` or ``NaN``.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DashboardRange(BaseModel):
    """Resolved query window (UTC, tz-aware)."""

    start: datetime
    end: datetime
    days: int = Field(
        default=0,
        description="Effective window length in days (0 when an explicit range was given)",
    )


class AgentsOverview(BaseModel):
    total: int = Field(description="Live agents (not deleted)")
    active: int = Field(description="Agents with status 'active'")


class ConversationsOverview(BaseModel):
    new: int = Field(description="Conversations created inside the window")
    active: int = Field(description="Conversations currently in 'active' status")
    total_messages: int = Field(
        description="Messages inside the window (agent-scoped when filtered)"
    )
    avg_messages_per_new_conversation: Optional[float] = Field(
        default=None,
        description="Average message_count over conversations created in the window",
    )


class MessagesOverview(BaseModel):
    total: int
    sent: int = Field(description="Outbound channel messages inside the window")
    delivered: int = Field(description="Messages whose status is 'delivered' or 'read'")
    failed: int
    success_rate: Optional[float] = Field(
        default=None,
        description="delivered / (delivered + failed), None when no completed/failed messages",
    )


class ConversionOverview(BaseModel):
    new_leads: int = Field(description="Leads created inside the window (agent-scoped when filtered)")
    total_leads: int = Field(description="All live leads")
    closed_leads: int = Field(
        description="Converted leads (Lead.status == 'converted', P6AN-05 source of truth)"
    )
    conversion_rate: Optional[float] = Field(
        default=None, description="closed_leads / total_leads, None when there are no leads"
    )


class AgentStat(BaseModel):
    agent_id: UUID
    agent_name: Optional[str] = Field(
        default=None, description="Null when the agent row was deleted meanwhile"
    )
    conversations: int
    messages: int
    message_success_rate: Optional[float] = Field(
        default=None,
        description="delivered / (delivered + failed) for this agent's channel messages, None when no denominator",
    )


class DashboardOverviewResponse(BaseModel):
    """Unified dashboard overview payload (P6AN-02)."""

    range: DashboardRange
    agents: AgentsOverview
    conversations: ConversationsOverview
    messages: MessagesOverview
    conversion: ConversionOverview
    by_agent: List[AgentStat] = Field(
        default_factory=list,
        description=(
            "Top agents by channel-message volume (max 10); the single entry "
            "when the agent_id filter is set"
        ),
    )
    computed_at: datetime
    cached: bool = Field(default=False, description="True when served from the response cache")
    cache_ttl_seconds: int = 300
