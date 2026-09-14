"""Conversation domain-event publishing (V1, in-process bus).

Mirrors ``app/services/crm_events.py`` for the conversation module
(t_cc6aa406): publishers call ``publish_nowait(event)`` after their own
commit and a flush point dispatches via the shared bus. Conversation
producers publish conversation / message / intent events so that
event-triggered workflows (auto-reply, follow-up) can react.

The publisher is a thin, testable delegate over the module bus — swap the
bus implementation (e.g. Redis queue) and nothing in the conversation
routers changes.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.events.domain_events import DomainEvent, DomainEventBus, get_event_bus

logger = logging.getLogger(__name__)


class ConversationEventPublisher:
    """Collects conversation domain events and flushes them to the bus."""

    def __init__(self, bus: Optional[DomainEventBus] = None):
        self.bus = bus or get_event_bus()

    # ---------- event construction ----------

    def build(
        self,
        event_type: str,
        entity_type: str,
        entity_id: Optional[UUID],
        payload: Optional[Dict[str, Any]] = None,
    ) -> DomainEvent:
        return DomainEvent(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )

    # ---------- queue / flush ----------

    def publish_nowait(self, event: DomainEvent) -> None:
        """Queue an event; dispatch happens at the next ``flush()``."""
        self.bus.publish_nowait(event)

    async def flush(self) -> int:
        """Dispatch everything queued so far. Returns the event count."""
        dispatched = await self.bus.dispatch_pending()
        return len(dispatched)

    @property
    def pending(self) -> List[DomainEvent]:
        return self.bus.pending


_default_publisher: Optional[ConversationEventPublisher] = None


def get_conversation_publisher() -> ConversationEventPublisher:
    """Process-wide publisher singleton (conversation producers share one queue)."""
    global _default_publisher
    if _default_publisher is None:
        _default_publisher = ConversationEventPublisher()
    return _default_publisher


def reset_conversation_publisher() -> None:
    """Test helper: drop the singleton (a new publisher is created on next use)."""
    global _default_publisher
    _default_publisher = None
