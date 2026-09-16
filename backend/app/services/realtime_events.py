"""Realtime event source + shared-bus bridge — P5MSG-04.

Two complementary ways to get an event onto the realtime hub:

1. **Direct seam (primary, decoupled):** ``publish_realtime_event``.
   Producers — P5MSG-02's message router (after its commit), P5MSG-03's
   channel adapter, any business action — call this directly. It needs no
   shared-bus wiring and is the stable contract P5MSG-04 owns.

2. **Shared-bus bridge (redundant, event-driven):**
   ``register_realtime_bus_bridge`` subscribes the platform's in-process
   domain bus (``app.events.domain_events``) for the channel-message event
   vocabulary (``channel_message.*``) and forwards each to the hub. This
   mirrors the existing ``register_workflow_*_subscriber`` bridge pattern
   and lets P5MSG-02/03 publish events on the bus (the same way
   ``app.routers.conversations`` already publishes ``message.created``)
   without knowing about the hub.

Both paths land in the same hub, so a client subscribed to
``/api/v1/realtime`` sees new messages, read receipts and delivery-status
changes whether the producer used the direct seam or the bus.

Event vocabulary (SSE ``kind`` values the client switches on):
    channel_message.created   — a new channel message was enqueued/delivered
    channel_message.status    — a delivery state changed (queued→sent→…)
    channel_message.read     — a read receipt was recorded
    conversation.updated      — a conversation's activity changed

Payloads carry ids / status / channel only — never message text, PII or
credentials (ARCHITECTURE rule #16).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.events.domain_events import DomainEvent, get_event_bus
from app.services.realtime_hub import RealtimeHub, get_realtime_hub

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event vocabulary (kept local to P5MSG-04 so the shared bus module is not
# edited; reconcile with P5MSG-02 if it introduces its own event names.)
# ---------------------------------------------------------------------------
REALTIME_EVENT_KINDS = (
    "channel_message.created",
    "channel_message.status",
    "channel_message.read",
    "conversation.updated",
)


def _dedup_key(event_type: str, entity_id: Optional[str], payload: Dict[str, Any]) -> str:
    """Best-effort dedup identity for an event.

    Uses the most specific stable field available (provider message id,
    then a status/receipt marker, then the entity id) so a producer that
    republishes the same transition (retry / idempotent re-flush) does not
    push a duplicate to live clients.
    """
    status = payload.get("status")
    prov = payload.get("provider_message_id") or payload.get("message_id")
    marker = status or prov or "na"
    return f"{event_type}:{entity_id or 'na'}:{marker}"


# ---------------------------------------------------------------------------
# 1. Direct public seam
# ---------------------------------------------------------------------------


def publish_realtime_event(
    kind: str,
    conversation_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    dedup_id: Optional[str] = None,
    hub: Optional[RealtimeHub] = None,
) -> Optional[int]:
    """Push one realtime event to all live subscribers (+ replay log).

    ``conversation_id`` scopes the event; pass ``None`` for a global event.
    Returns the event ``seq`` (usable as a client reconnect cursor) or
    ``None`` if the event was dropped as a duplicate.

    Best-effort: a hub failure is logged, never raised, so a business
    action is never lost because the push layer hiccuped.
    """
    hub = hub or get_realtime_hub()
    try:
        seq = hub.emit(kind, conversation_id, payload or {}, dedup_id)
        if seq is not None:
            logger.info(
                "realtime: pushed %s conv=%s seq=%s",
                kind, conversation_id, seq,
            )
        return seq
    except Exception:  # noqa: BLE001 - push layer must not break the caller
        logger.exception("realtime: failed to push event kind=%s", kind)
        return None


# ---------------------------------------------------------------------------
# 2. Shared-bus bridge (redundant, event-driven)
# ---------------------------------------------------------------------------

_bus_wired = False


def register_realtime_bus_bridge(hub: Optional[RealtimeHub] = None) -> int:
    """Subscribe the hub to channel-message events on the shared bus.

    Idempotent (module flag), mirroring ``register_workflow_crm_subscriber``
    / ``register_workflow_conversation_subscriber``. Returns the number of
    event types wired.
    """
    global _bus_wired
    if _bus_wired:
        return len(REALTIME_EVENT_KINDS)

    hub = hub or get_realtime_hub()
    bus = get_event_bus()

    async def _forward(event: DomainEvent) -> None:
        """Bus handler: forward a channel-message event to the hub.

        Bus-safe: never raises. Entity type tells us the scoping conversation
        (a channel-message event's payload carries ``conversation_id``).
        """
        if event.event_type not in REALTIME_EVENT_KINDS:
            return
        payload = dict(event.payload or {})
        # Prefer an explicit conversation scoping from the payload.
        conv = payload.get("conversation_id")
        if conv is None and event.entity_id is not None:
            conv = str(event.entity_id)
        dedup = _dedup_key(event.event_type, conv, payload)
        hub.emit(event.event_type, conv, payload, dedup)

    for event_type in REALTIME_EVENT_KINDS:
        bus.subscribe(event_type, _forward)
    _bus_wired = True
    logger.info(
        "realtime: bus bridge wired to %d channel-message event types",
        len(REALTIME_EVENT_KINDS),
    )
    return len(REALTIME_EVENT_KINDS)


def reset_realtime_bus_bridge() -> None:
    """Test helper: forget the wiring flag so a fresh bridge can be created."""
    global _bus_wired
    _bus_wired = False
