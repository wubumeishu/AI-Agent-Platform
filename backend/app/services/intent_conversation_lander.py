"""AI-intent data landing on conversation fields (P5MSG-05, scope item 4).

Roadmap Phase 2 Message/Conversation increment. The Phase-2 intent
classifier (``POST /api/v1/intents/classify``) publishes an
``intent.classified`` event on the in-process bus but does not persist
the classification onto the conversation row. This module closes that
loop: the latest intent classification for a conversation lands in the
conversation's existing ``metadata_`` JSONB field::

    conversation.metadata_["last_intent"] = {
        "intent_type", "intent_name", "confidence",
        "classified_at"
    }

No schema change (the card's out-of-scope list forbids modifying Phase-3
CRM entities; the conversation ``metadata_`` column already exists and is
the documented metadata channel), no new table, no migration.

Idempotency: an upsert of the *identical* classification is a no-op (the
handler skips the write when the stored value already equals the new one);
a newer classification with a different result naturally overwrites it.
So re-delivered events never cause duplicate writes or oscillation.

Architecture separation (SOUL / ARCHITECTURE.md):
- Bus-safe handler (mirrors ``conversation_lead_bridge``): a failing land
  is logged and swallowed, never taking down the shared
  ``intent.classified`` delivery for the lead bridge / workflow bridge.
- It is a SEPARATE subscriber from ``CrmMessageEventWriteback`` and the
  lead bridge — each runs its own handler on its own DB session.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.events.domain_events import DomainEvent, get_event_bus

logger = logging.getLogger(__name__)


def _coerce_uuid(value) -> Optional[UUID]:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


class IntentConversationLander:
    """Bus-safe handler that lands the latest intent on a conversation row.

    Depends only on abstractions (the in-process event bus + the
    conversation entity). No AI-provider / vendor code lives here.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _last_intent_value(payload: Dict[str, object]) -> Dict[str, object]:
        """Shape the stored ``last_intent`` record from an event payload.

        Pure, unit-testable. Missing optional fields are simply absent —
        a degenerate event still lands the type it did carry.
        """
        value: Dict[str, object] = {
            "intent_type": payload.get("intent_type"),
            "classified_at": datetime.now(timezone.utc).isoformat(),
        }
        if payload.get("intent_name") is not None:
            value["intent_name"] = payload["intent_name"]
        if payload.get("confidence") is not None:
            try:
                value["confidence"] = float(payload["confidence"])
            except (TypeError, ValueError):
                value["confidence"] = None
        return value

    async def handle_domain_event(self, event: DomainEvent) -> Optional[Dict[str, object]]:
        """Land one ``intent.classified`` event. Bus-safe (never raises).

        Returns the stored value on a real write, ``None`` when skipped.
        """
        if event.event_type != "intent.classified":
            return None

        payload = event.payload or {}
        conv_uuid = _coerce_uuid(payload.get("conversation_id") or event.entity_id)
        if conv_uuid is None:
            logger.debug("intent lander: missing/invalid conversation_id; skipping")
            return None

        try:
            conv = (
                await self.db.execute(
                    select(Conversation).where(
                        Conversation.id == conv_uuid,
                        Conversation.is_deleted == False,  # noqa: E712
                    )
                )
            ).scalar_one_or_none()
        except Exception:
            logger.exception("intent lander: conversation lookup failed")
            return None
        if conv is None:
            logger.debug("intent lander: conversation %s gone; skipping", conv_uuid)
            return None

        stored = dict(conv.metadata_ or {})
        value = self._last_intent_value(payload)
        # Idempotency: compare the *stable* classification fields. The
        # ``classified_at`` stamp is volatile (set to now on every delivery),
        # so an identical re-delivered event must NOT trigger a rewrite —
        # that is exactly the "重复事件不重复写入" guarantee. A different
        # classification (type/name/confidence) overwrites it.
        stable_keys = ("intent_type", "intent_name", "confidence")
        if all(stored.get("last_intent", {}).get(k) == value.get(k) for k in stable_keys) and stored.get("last_intent"):
            return None

        stored["last_intent"] = value
        # Reassign so SQLAlchemy emits the JSONB update.
        conv.metadata_ = stored
        try:
            self.db.add(conv)
            await self.db.commit()
            await self.db.refresh(conv)
        except Exception:
            await self.db.rollback()
            logger.exception("intent lander: failed to persist last_intent (%s)", conv_uuid)
            return None

        logger.info(
            "intent lander: conversation %s last_intent=%s (confidence=%s)",
            conv_uuid,
            value.get("intent_type"),
            value.get("confidence"),
        )
        return value

    def health(self) -> Dict[str, object]:
        return {
            "service": "intent-conversation-lander",
            "event_type": "intent.classified",
            "target_field": "conversation.metadata_.last_intent",
        }


# =====================================================================
# Event-bus wiring
# =====================================================================

_subscribed = False


def register_intent_conversation_lander() -> int:
    """Subscribe the lander to ``intent.classified`` (idempotent).

    Own DB session per event (same isolation as the lead bridge and the
    workflow-conversation bridge). Returns the number of event types
    subscribed (1).
    """
    global _subscribed
    if _subscribed:
        return 1

    from app.db.session import AsyncSessionLocal

    bus = get_event_bus()

    async def _on_event(event: DomainEvent) -> None:
        db = AsyncSessionLocal()
        try:
            await IntentConversationLander(db).handle_domain_event(event)
        finally:
            await db.close()

    bus.subscribe("intent.classified", _on_event)
    _subscribed = True
    logger.info("intent-lander: subscribed to intent.classified")
    return 1


def _is_subscribed() -> bool:
    return _subscribed


def reset_intent_conversation_lander() -> None:
    """Test helper: forget that the bus was wired."""
    global _subscribed
    _subscribed = False
