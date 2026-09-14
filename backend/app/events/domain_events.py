"""In-process domain event bus (V1).

Design notes
------------
- V1 keeps the bus in-memory so the Workflow-CRM integration (t_4f31af5e)
  can be tested without a queue infrastructure. The surface is deliberately
  small (``subscribe`` / ``publish`` / ``publish_nowait`` / ``dispatch_pending``
  / ``reset``) so it can be swapped for a Redis/queue backed implementation
  later without touching publishers or subscribers.
- Two dispatch styles:
  - ``publish(event)``  — await handlers inline (used by tests / callers
    that can block).
  - ``publish_nowait(event)`` + ``dispatch_pending()`` — queue the event and
    flush it as ``asyncio.create_task`` handlers at a controlled point.
    CRM services queue after their commit, routers flush after the response
    is ready, so a subscriber's failure can never delay or roll back the
    publisher's request.
- Handler exceptions are NEVER propagated to publishers: a crashing
  subscriber must not take down the API request that produced the event.
  ``dispatch_pending`` returns per-handler outcomes; ``publish`` likewise.
- Event types are a flat, stable vocabulary (see ``EVENT_TYPES``). CRM
  services publish AFTER their own commit, with the affected entity id in the
  payload; the workflow executor re-reads current state at match time so the
  payload stays minimal.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Stable event-type vocabulary.
#
# ``EVENT_TYPES`` are the CRM domain events, owned by the workflow-CRM
# executor (t_4f31af5e) and published by the CRM services after their commit.
EVENT_TYPES = (
    "lead.created",
    "lead.status_changed",
    "lead.stage_changed",
    "lead.tags_changed",
    "customer.tag_changed",
    "customer.created",
)
# Conversation-module domain events (t_cc6aa406), published by the
# conversation / intent producers after their commit and consumed by the
# workflow-conversation bridge. Kept as a *separate* tuple so the CRM
# executor and the conversation bridge each subscribe only to their own
# domain and never fire on each other's events (architecture separation).
CONVERSATION_EVENT_TYPES = (
    "conversation.created",
    "message.created",
    "intent.classified",
)
# Alias so both naming schemes in the codebase work. In V1 the CRM event
# vocabulary IS ``EVENT_TYPES``; conversation events are kept separate.
CRM_EVENT_TYPES = EVENT_TYPES

Handler = Callable[["DomainEvent"], Any]  # sync or async


@dataclass
class DomainEvent:
    """A single domain event observation."""

    event_type: str
    entity_type: str
    entity_id: UUID
    payload: Dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DomainEventBus:
    """Minimal in-process pub/sub bus.

    ``subscribe(event_type, handler)`` registers for an exact event type;
    passing ``None`` registers a wildcard subscriber that sees every event.
    """

    def __init__(self) -> None:
        # event_type -> [handlers]  (None key = wildcard)
        self._subscribers: Dict[Optional[str], List[Handler]] = {}
        # queued, not-yet-dispatched events (publish_nowait / dispatch_pending)
        self._pending: List[DomainEvent] = []

    def subscribe(self, event_type: Optional[str], handler: Handler) -> Handler:
        """Register ``handler`` for ``event_type`` (or all events if None)."""
        self._subscribers.setdefault(event_type, []).append(handler)
        return handler

    def unsubscribe(self, event_type: Optional[str], handler: Handler) -> bool:
        """Remove a previously registered handler. Returns True if found."""
        handlers = self._subscribers.get(event_type)
        if handlers and handler in handlers:
            handlers.remove(handler)
            return True
        return False

    def reset(self) -> None:
        """Drop all subscriptions and queued events (test helper)."""
        self._subscribers = {}
        self._pending = []

    @property
    def subscriber_count(self) -> int:
        return sum(len(v) for v in self._subscribers.values())

    async def publish(self, event: DomainEvent) -> List[Dict[str, Any]]:
        """Dispatch ``event`` to its subscribers.

        Wildcard subscribers run before type-specific ones. Each handler is
        awaited when it is a coroutine function. Exceptions are captured and
        logged, never raised; the return value reports per-handler outcomes
        so the caller can observe failures without the publisher dying.
        """
        results: List[Dict[str, Any]] = []
        handlers: List[Handler] = list(
            self._subscribers.get(None, []) + self._subscribers.get(event.event_type, [])
        )
        for handler in handlers:
            outcome: Dict[str, Any] = {
                "handler": getattr(handler, "__qualname__", repr(handler)),
                "ok": True,
                "error": None,
            }
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    result = await result
                outcome["result"] = result
            except Exception as exc:  # noqa: BLE001 - bus must not break publishers
                outcome["ok"] = False
                outcome["error"] = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Domain event handler %s failed for %s: %s",
                    outcome["handler"], event.event_type, outcome["error"],
                )
            results.append(outcome)
        return results

    # ---------------- fire-and-forget queue ----------------

    def publish_nowait(self, event: DomainEvent) -> None:
        """Queue ``event`` for later dispatch (``dispatch_pending``).

        The event is stored, not executed. This is the pattern CRM
        services use: after their own commit they queue the domain event,
        and the request-level flush point (router / app startup hook)
        triggers ``dispatch_pending``.
        """
        self._pending.append(event)

    async def dispatch_pending(self) -> List[List[Dict[str, Any]]]:
        """Run handlers for every queued event, in order.

        Each queued event's handlers are awaited sequentially (one bus
        event at a time) so the ordering a publisher observed is preserved.
        Callers that cannot block (request-scoped flush points) may wrap
        this in their own task and fire-and-forget; the return value
        reports the per-event handler outcomes. Swaps the pending list
        atomically, so events queued during a dispatch are picked up on
        the next call.
        """
        events, self._pending = self._pending, []
        all_outcomes: List[List[Dict[str, Any]]] = []
        for event in events:
            outcomes = await self.publish(event)
            all_outcomes.append(outcomes)
        return all_outcomes

    @property
    def pending(self) -> List[DomainEvent]:
        """Currently queued, not-yet-dispatched events (read-only view)."""
        return list(self._pending)


# --------------------------------------------------------------------------
# Module-level default bus (process singleton)
# --------------------------------------------------------------------------
_default_bus = DomainEventBus()


def get_event_bus() -> DomainEventBus:
    """Return the process-default bus.

    Callers should prefer ``get_event_bus`` over constructing their own so
    publishers and subscribers share one wiring point. Tests may call
    ``bus.reset()`` between cases.
    """
    return _default_bus
