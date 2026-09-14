"""CRM domain-event publishing (V1, in-process bus).

Publishers (CRM services) call:

- ``capture_lead(old)``  before mutating a lead (pre-commit snapshot of
  status / lifecycle stage)
- ``publish_nowait(event)`` after the mutation commits — the event is
  queued on the bus, never blocked on

The router layer (or any request-scoped flush point) calls
``await flush()`` to dispatch everything queued so far. Because events
are processed on the bus (handlers receive their own DB sessions), a
crashing subscriber can never roll back or delay the publisher's
request.

The publisher is a thin, testable delegate over the module bus — swap the
bus implementation (e.g. Redis queue) and nothing in the CRM services
changes.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.events.domain_events import DomainEvent, DomainEventBus, get_event_bus

logger = logging.getLogger(__name__)


class CrmEventPublisher:
    """Collects CRM domain events and flushes them to the bus."""

    def __init__(self, bus: Optional[DomainEventBus] = None):
        self.bus = bus or get_event_bus()

    # ---------- capture helpers ----------

    def capture_lead(self, lead: Any) -> Dict[str, Any]:
        """Snapshot mutable fields of a lead BEFORE the commit that mutates it."""
        return {
            "status": getattr(lead, "status", None),
            "lifecycle_stage_code": getattr(lead, "lifecycle_stage_code", None),
        }

    # ---------- event construction ----------

    def build(
        self,
        event_type: str,
        entity_type: str,
        entity_id: UUID,
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


_default_publisher: Optional[CrmEventPublisher] = None


def get_crm_publisher() -> CrmEventPublisher:
    """Process-wide publisher singleton (services + routers share one queue)."""
    global _default_publisher
    if _default_publisher is None:
        _default_publisher = CrmEventPublisher()
    return _default_publisher


def reset_crm_publisher() -> None:
    """Test helper: drop the singleton (a new publisher is created on next use)."""
    global _default_publisher
    _default_publisher = None
