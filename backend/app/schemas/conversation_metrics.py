"""Conversation Metrics schemas (Phase 6 / P6AN-04).

Response models for ``GET /api/v1/analytics/conversations`` — the AI
conversation quality & efficiency surface.

The five headline metrics and the per-dimension breakdowns are defined here;
the actual SQL that produces the numbers lives in
``app.services.conversation_metrics_service``. Metric *formulas* are
documented alongside each field so the API contract stays self-describing
(Definition of Done: 指标计算文档化).
"""
from __future__ import annotations

from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# Intent-level accuracy threshold default. Mirrors the intent-classifier's
# confidence floor (``IntentClassificationResponse.confidence_threshold`` = 0.7):
# an intent counts as "accurate/confident" when its confidence clears this bar
# AND an action was actually matched. This is a *proxy* — no ground-truth
# labels are recorded in V1.
DEFAULT_INTENT_ACCURACY_THRESHOLD = 0.7

# High-stakes intents that force a human handoff in the decision engine
# (mirrors ``app.services.decision_engine.ESCALATING_INTENTS``). A
# conversation counts as "handed off" when any of its intents is one of these
# or matched the ``escalate`` action.
ESCALATING_INTENT_TYPES = ("complaint", "escalation", "callback_request")


class PlatformMetric(BaseModel):
    """Conversation metrics aggregated per platform (channel)."""

    channel: str = Field(..., description="Platform / channel code (conversation.channel).")
    conversations: int = 0
    user_messages: int = Field(0, description="User-role messages (≈ conversation rounds).")
    avg_duration_seconds: float = 0.0
    positive_sentiment: int = 0
    with_sentiment: int = 0
    # Derived (computed in the service; safe when denominator is 0):
    avg_rounds: float = Field(0.0, description="user_messages / conversations (0 when no conversations).")
    satisfaction_rate: float = Field(0.0, description="positive_sentiment / with_sentiment proxy (0 when none).")


class AgentMetric(BaseModel):
    """Conversation volume aggregated per Agent (via customer binding)."""

    agent_id: UUID
    agent_name: Optional[str] = None
    conversations: int = 0
    user_messages: int = 0
    avg_rounds: float = 0.0


class IntentMetric(BaseModel):
    """Per-intent classification quality (proxy accuracy)."""

    intent_type: str
    total: int = 0
    accurate: int = Field(0, description="Intents with confidence >= threshold AND a matched action.")
    avg_confidence: float = 0.0
    accuracy: float = Field(0.0, description="accurate / total proxy (0 when total is 0).")
    is_escalating: bool = Field(False, description="True when this intent type forces a human handoff.")


class ConversationMetricsResponse(BaseModel):
    """AI conversation quality & efficiency metrics (P6AN-04).

    Empty-data safety: when no conversations fall in scope, ``sample_size`` is
    0, ``has_data`` is False, every headline metric is 0.0, and the
    breakdown lists are empty — consumers never see a division-by-zero.
    """

    sample_size: int = Field(0, description="Number of conversations in scope (denominator base).")
    has_data: bool = False
    window: Dict[str, str] = Field(default_factory=dict, description="Resolved time window {start,end,window}.")
    filters: Dict[str, Optional[str]] = Field(
        default_factory=dict, description="Effective filters {agent_id,intent_type,channel}."
    )

    # ---- headline metrics (the five in scope) ----
    total_conversations: int = 0
    avg_response_time_seconds: float = Field(
        0.0,
        description="Mean seconds between a user message and the following assistant message "
                    "(assistant.created_at - preceding user.created_at). 0.0 when no such pair.",
    )
    avg_conversation_rounds: float = Field(
        0.0, description="User-role messages / conversations (each user turn = one round). 0.0 when no data."
    )
    intent_accuracy: float = Field(
        0.0,
        description="PROXY: intents with confidence >= threshold AND a matched action / total intents. 0.0 when none.",
    )
    human_handoff_rate: float = Field(
        0.0,
        description="Conversations with at least one escalating intent / total conversations. 0.0 when no data.",
    )
    satisfaction_rate: float = Field(
        0.0,
        description="PROXY: positive-sentiment conversations / conversations carrying a sentiment label. 0.0 when none.",
    )

    # ---- supporting counts (raw ingredients of the rates above) ----
    total_messages: int = 0
    total_user_messages: int = 0
    total_intents: int = 0
    confident_intents: int = 0
    accurate_intents: int = Field(
        0,
        description="Raw numerator of intent_accuracy: intents with confidence >= threshold AND a matched action.",
    )
    escalating_intents: int = 0
    handoff_conversations: int = 0
    positive_sentiment: int = 0
    with_sentiment: int = 0
    avg_confidence: float = 0.0
    avg_duration_seconds: float = 0.0
    accuracy_threshold: float = Field(DEFAULT_INTENT_ACCURACY_THRESHOLD,
                                      description="Confidence bar used for the intent-accuracy proxy.")

    # ---- per-dimension breakdowns ----
    by_platform: List[PlatformMetric] = Field(default_factory=list)
    by_agent: List[AgentMetric] = Field(default_factory=list)
    by_intent: List[IntentMetric] = Field(default_factory=list)
