"""Domain events package (process-level in-memory bus).

V1 keeps the event bus in-process: CRM services publish typed domain
events after state changes and the workflow-CRM integration subscribes.
The bus is deliberately tiny so it can be swapped for a Redis/queue
backed implementation later without touching publishers or subscribers.
"""
from app.events.domain_events import (
    CONVERSATION_EVENT_TYPES,
    DomainEvent,
    DomainEventBus,
    EVENT_TYPES,
    get_event_bus,
)

__all__ = [
    "DomainEvent",
    "DomainEventBus",
    "get_event_bus",
    "EVENT_TYPES",
    "CONVERSATION_EVENT_TYPES",
]
