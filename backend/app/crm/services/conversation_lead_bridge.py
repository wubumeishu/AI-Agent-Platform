"""CRM Conversation -> Lead auto-generation bridge (t_crm_007).

This module closes the **automatic** half of the CRM + Conversation
integration: when the intent classifier emits an ``intent.classified``
domain event whose signal is "high intent", a CRM Lead is auto-created for
the conversation's customer — without a human clicking the manual
``POST /crm/leads/from-conversation`` trigger.

    intent.classified (published by app/routers/intents.py, in-process bus)
        |
        v
    ConversationLeadBridge.handle_domain_event
        |  1. ignore anything that is not ``intent.classified``
        |  2. evaluate the trigger rule (HIGH_VALUE_INTENT + confidence floor)
        |  3. if it fires, delegate to the CRM lead service
        |     ``create_lead_from_conversation`` (customer auto-link + dedup
        |     live there, so persistence rules stay in ONE place)
        v
    Lead (source_type="conversation", source_id=<conversation_id>,
         customer_id=<conversation.customer_id>)

Architecture-separation rules (SOUL / ARCHITECTURE.md):
- This bridge owns ONLY the *trigger decision* (which intents, at what
  confidence, promote a conversation into a Lead). It delegates the actual
  Lead row to ``app.crm.services.lead`` so every write of a Lead is defined
  in a single service.
- It is a SEPARATE subscriber from ``WorkflowConversationBridge``. Both
  subscribe to the same ``intent.classified`` event type but run
  independent handlers on their own DB sessions: the workflow bridge drives
  auto-reply / tag actions, this bridge captures the CRM lead. The in-process
  bus already isolates handler exceptions, so a failing lead capture can
  never break the workflow auto-reply (and vice-versa).
- A full rules engine / lead-quality scoring is explicitly out of scope
  (t_crm_007 "Out of Scope"); this is a single, documented, tunable
  high-intent heuristic.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.domain_events import DomainEvent, get_event_bus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunable trigger configuration (defaults are sensible, overridable at the
# process level via env so ops can tune without a code change).
# ---------------------------------------------------------------------------

# Intent types that, when classified above the confidence floor, are strong
# enough to turn a conversation into a CRM lead. A *conservative* set by
# default: explicit buying / contact / retention signals.
DEFAULT_HIGH_VALUE_INTENTS: FrozenSet[str] = frozenset(
    {"command", "callback_request", "escalation", "complaint"}
)

# The intent classifier reports confidence in [0.0, 1.0]; a signal is only
# trusted above this floor (matches IntentService's own 0.7 confidence
# threshold, so we only act on classifications the classifier itself trusts).
DEFAULT_CONFIDENCE_FLOOR: float = 0.7


def _env_high_value_intents() -> FrozenSet[str]:
    """Read ``LEAD_BRIDGE_HIGH_VALUE_INTENTS`` (comma-separated) or default."""
    raw = os.getenv("LEAD_BRIDGE_HIGH_VALUE_INTENTS")
    if not raw:
        return DEFAULT_HIGH_VALUE_INTENTS
    values = {v.strip().lower() for v in raw.split(",") if v.strip()}
    return frozenset(values) or DEFAULT_HIGH_VALUE_INTENTS


def _env_confidence_floor() -> float:
    """Read ``LEAD_BRIDGE_CONFIDENCE_FLOOR`` or default."""
    raw = os.getenv("LEAD_BRIDGE_CONFIDENCE_FLOOR")
    if not raw:
        return DEFAULT_CONFIDENCE_FLOOR
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "LEAD_BRIDGE_CONFIDENCE_FLOOR=%r is not a float; using default %s",
            raw, DEFAULT_CONFIDENCE_FLOOR,
        )
        return DEFAULT_CONFIDENCE_FLOOR


# ---------------------------------------------------------------------------
# Trigger decision (pure, unit-testable — no DB)
# ---------------------------------------------------------------------------

@dataclass
class LeadTriggerDecision:
    """Result of evaluating one ``intent.classified`` event as a lead signal."""

    should_create: bool
    reason: str
    intent_type: Optional[str] = None
    confidence: Optional[float] = None
    conversation_id: Optional[str] = None


class ConversationLeadBridge:
    """Bus-safe handler that captures high-intent conversations as CRM Leads.

    Depends only on abstractions (the in-process event bus + the CRM lead
    service). No BitBrowser / vendor / AI-provider code lives here.
    """

    def __init__(
        self,
        db: AsyncSession,
        high_value_intents: Optional[FrozenSet[str]] = None,
        confidence_floor: Optional[float] = None,
    ) -> None:
        self.db = db
        self.high_value_intents = high_value_intents or _env_high_value_intents()
        self.confidence_floor = (
            confidence_floor if confidence_floor is not None else _env_confidence_floor()
        )

    # ---------------- pure rule ----------------

    @staticmethod
    def _coerce_uuid(value) -> Optional[UUID]:
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            return None

    def evaluate_intent_event(
        self, payload: Dict[str, object]
    ) -> LeadTriggerDecision:
        """Decide whether one ``intent.classified`` payload promotes a Lead.

        Pure function of the payload + this bridge's config. It never touches
        the DB, so it is directly unit-testable.
        """
        payload = payload or {}
        intent_type = str(payload.get("intent_type") or "").lower()
        conv_id = payload.get("conversation_id")
        conv_id_str = str(conv_id) if conv_id is not None else None

        try:
            confidence = float(payload.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0

        base = LeadTriggerDecision(
            should_create=False,
            reason="unspecified",
            intent_type=intent_type or None,
            confidence=confidence,
            conversation_id=conv_id_str,
        )

        if not conv_id_str:
            return LeadTriggerDecision(
                should_create=False,
                reason="payload has no conversation_id",
                intent_type=base.intent_type,
                confidence=confidence,
            )

        if intent_type and intent_type not in self.high_value_intents:
            return LeadTriggerDecision(
                should_create=False,
                reason=f"intent '{intent_type}' not in high-value set",
                intent_type=intent_type,
                confidence=confidence,
                conversation_id=conv_id_str,
            )

        if confidence < self.confidence_floor:
            return LeadTriggerDecision(
                should_create=False,
                reason=(
                    f"confidence {confidence} below floor "
                    f"{self.confidence_floor}"
                ),
                intent_type=intent_type or None,
                confidence=confidence,
                conversation_id=conv_id_str,
            )

        return LeadTriggerDecision(
            should_create=True,
            reason="high-value intent at/above confidence floor",
            intent_type=intent_type or None,
            confidence=confidence,
            conversation_id=conv_id_str,
        )

    # ---------------- bus handler ----------------

    async def handle_domain_event(self, event: DomainEvent) -> Optional[Dict[str, object]]:
        """Bus handler: capture a high-intent conversation as a Lead.

        Guaranteed not to raise (bus-safe): a failing capture is logged and
        swallowed so the shared event delivery for the workflow bridge is
        never disturbed.
        """
        if event.event_type != "intent.classified":
            return None

        payload = event.payload or {}
        decision = self.evaluate_intent_event(payload)
        if not decision.should_create:
            logger.debug(
                "intent lead bridge: not a lead (%s)", decision.reason
            )
            return None

        conv_uuid = self._coerce_uuid(
            payload.get("conversation_id") or event.entity_id
        )
        if conv_uuid is None:
            logger.debug("intent lead bridge: missing/invalid conversation_id; skipping")
            return None

        try:
            # Delegate persistence + customer auto-link + per-conversation
            # dedup to the CRM lead service (single source of truth).
            from app.crm.services.lead import create_lead_from_conversation

            # allow_customer_duplicate=False => 自动触发路径做客户级去重：
            # 该客户已有 conversation 来源 Lead 时复用，不再新建
            # （保证「同一客户不会因多轮高意向对话被反复创建 Lead」）。
            lead = await create_lead_from_conversation(
                self.db,
                conv_uuid,
                auto_link_customer=True,
                allow_customer_duplicate=False,
            )
        except Exception:
            # A missing conversation (already deleted) or a concurrent commit
            # must never take down event delivery for the workflow bridge.
            logger.exception(
                "intent lead bridge: failed to create lead for conversation %s",
                conv_uuid,
            )
            return None

        logger.info(
            "intent lead bridge: %s (intent=%s confidence=%s) -> lead %s",
            "created" if lead and lead.get("id") else "no-op",
            decision.intent_type,
            decision.confidence,
            lead.get("id") if lead else None,
        )
        return lead

    def health(self) -> Dict[str, object]:
        return {
            "service": "conversation-lead-bridge",
            "event_type": "intent.classified",
            "high_value_intents": sorted(self.high_value_intents),
            "confidence_floor": self.confidence_floor,
        }


# =====================================================================
# Event-bus wiring
# =====================================================================

_subscribed = False


def register_conversation_lead_subscriber() -> int:
    """Subscribe the lead bridge to ``intent.classified`` (idempotent).

    Mirrors ``register_workflow_conversation_subscriber``: each event is
    handled in its own DB session so the CRM side can never hold a
    publisher's transaction open. Returns the number of event types
    subscribed (1 = ``intent.classified``).
    """
    global _subscribed
    if _subscribed:
        return 1

    from app.db.session import AsyncSessionLocal

    bus = get_event_bus()

    async def _on_event(event: DomainEvent) -> None:
        db = AsyncSessionLocal()
        try:
            await ConversationLeadBridge(db).handle_domain_event(event)
        finally:
            await db.close()

    bus.subscribe("intent.classified", _on_event)
    _subscribed = True
    logger.info(
        "conversation-lead-bridge: subscribed to intent.classified "
        "(intents=%s floor=%.2f)",
        sorted(_env_high_value_intents()),
        _env_confidence_floor(),
    )
    return 1


def _is_subscribed() -> bool:
    return _subscribed


def reset_conversation_lead_subscriber() -> None:
    """Test helper: forget that the bus was wired."""
    global _subscribed
    _subscribed = False
