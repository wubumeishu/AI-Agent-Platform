"""Message-event -> CRM ActivityLog write-back (P5MSG-05).

Roadmap Phase 2 Message/Conversation increment — the *write-back* half of the
CRM integration: message events become **read-only CRM records** in
``activity_log`` (Customer 360's activity feed). No Phase-3 entity structure
is modified; this module only *consumes* the CRM activity entity.

    message.created (published by app/routers/conversations.py after a
    chat-transcript message commits, on the in-process bus)
        |
        v
    CrmMessageEventWriteback.handle_domain_event
        |  1. ignore anything that is not ``message.created``
        |  2. resolve the conversation's customer (live read, minimal payload)
        |  3. idempotent ActivityLog write (dedup key in metadata_)
        v
    ActivityLog(activity_type="chat_message", metadata_={event_key, ...})

Idempotency (card acceptance: "事件回写幂等（重复事件不重复写入）"):

- The dedup key is ``event_key = "message.created:<message_id>"``, stored in
  ``ActivityLog.metadata_`` (JSONB). Before inserting, the handler checks
  whether an activity with that key already exists for the customer; on a
  hit it is a no-op. A re-delivered / duplicated event therefore never
  produces a second row.
- Within one process the bus is single-writer (in-process V1), so the
  check-then-insert runs inside the handler's own transaction and the
  duplicate-elimination guarantee holds for event re-delivery. A concurrent
  double-insert of the *same* event is not a realistic failure mode in the
  V1 single-process bus (same guarantee shape as the
  ``conversation_lead_bridge`` customer-level dedup).

Architecture separation (SOUL / ARCHITECTURE.md):
- Bus-safe handler: a failing write-back is logged and swallowed, mirroring
  ``ConversationLeadBridge`` — it must never take down the shared
  ``message.created`` delivery for the workflow-conversation bridge.
- CRM write is a plain ``ActivityLog`` insert (the Phase-3 entity is only
  *consumed* here); no workflow/CRM rule engine is involved.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.memory import ActivityLog
from app.events.domain_events import DomainEvent, get_event_bus

logger = logging.getLogger(__name__)


def _coerce_uuid(value) -> Optional[UUID]:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def event_key_for(event: DomainEvent) -> str:
    """Stable dedup key for one ``message.created`` event.

    The bus carries the message id in the payload (falls back to the
    entity id, which the conversations router sets to the message's own
    id), so two deliveries of the same observation map to one key.
    """
    message_id = (event.payload or {}).get("message_id") or event.entity_id
    return f"message.created:{message_id}"


class CrmMessageEventWriteback:
    """Bus-safe handler that records message events as CRM activities.

    Depends only on abstractions (the in-process event bus + the CRM
    ActivityLog entity). No platform / vendor / AI-provider code lives here.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ---------------- pure helpers ----------------

    @staticmethod
    def _activity_for(
        customer_id: UUID,
        event: DomainEvent,
        conv: Conversation,
    ) -> ActivityLog:
        """Shape one ActivityLog row for a message event (no persistence).

        Pure enough to unit-test directly: the direction is derived from the
        message role (user -> inbound, assistant/system -> outbound); the
        dedup key lands in ``metadata_`` for the idempotency check.
        """
        payload = event.payload or {}
        role = str(payload.get("role") or "")
        direction = "inbound" if role == "user" else "outbound"
        title = (
            "新收到客户消息" if direction == "inbound" else "发出客服回复"
        )
        key = event_key_for(event)
        return ActivityLog(
            customer_id=customer_id,
            activity_type="chat_message",
            title=title,
            description=(
                f"channel={conv.channel} conversation={conv.id} "
                f"role={role or 'unknown'}"
            ),
            metadata_={
                "event_key": key,
                "source": "message_event_writeback",
                "event_type": event.event_type,
                "message_id": str(payload.get("message_id") or event.entity_id),
                "conversation_id": str(payload.get("conversation_id") or event.entity_id),
                "channel": conv.channel,
                "role": role or None,
            },
        )

    async def _existing_activity_id(
        self, customer_id: UUID, key: str
    ) -> Optional[UUID]:
        """Return the id of an ActivityLog with this dedup key, if any."""
        result = await self.db.execute(
            select(ActivityLog.id).where(
                ActivityLog.customer_id == customer_id,
                ActivityLog.metadata_["event_key"].astext == key,  # JSONB ->>
            ).limit(1)
        )
        row = result.first()
        return row[0] if row else None

    # ---------------- bus handler ----------------

    async def handle_domain_event(self, event: DomainEvent) -> Optional[Dict[str, object]]:
        """Record one ``message.created`` event as a CRM activity.

        Guaranteed not to raise (bus-safe). Returns the written activity's
        dict on a real insert, ``None`` when skipped (wrong event type,
        missing context, or an idempotent no-op).
        """
        if event.event_type != "message.created":
            return None

        payload = event.payload or {}
        conv_uuid = _coerce_uuid(payload.get("conversation_id"))
        if conv_uuid is None:
            logger.debug(
                "crm message write-back: missing/invalid conversation_id; skipping"
            )
            return None

        try:
            conv_row = (
                await self.db.execute(
                    select(Conversation).where(
                        Conversation.id == conv_uuid,
                        Conversation.is_deleted == False,  # noqa: E712
                    )
                )
            ).scalar_one_or_none()
        except Exception:
            logger.exception("crm message write-back: conversation lookup failed")
            return None
        if conv_row is None:
            # Conversation already deleted after the event was published —
            # nothing to attribute the record to. Silent by design.
            logger.debug(
                "crm message write-back: conversation %s gone; skipping", conv_uuid
            )
            return None

        key = event_key_for(event)
        try:
            existing = await self._existing_activity_id(conv_row.customer_id, key)
        except Exception:
            logger.exception("crm message write-back: dedup check failed")
            return None
        if existing is not None:
            logger.info(
                "crm message write-back: duplicate event skipped (key=%s)", key
            )
            return None

        try:
            activity = self._activity_for(conv_row.customer_id, event, conv_row)
            self.db.add(activity)
            await self.db.commit()
            await self.db.refresh(activity)
        except Exception:
            # A crashing write-back must never disturb the shared event
            # delivery for the workflow-conversation bridge.
            await self.db.rollback()
            logger.exception(
                "crm message write-back: failed to persist activity for event %s",
                key,
            )
            return None

        logger.info(
            "crm message write-back: activity %s (event_key=%s)",
            activity.id, key,
        )
        return {
            "id": str(activity.id),
            "customer_id": str(activity.customer_id),
            "activity_type": activity.activity_type,
            "title": activity.title,
            "event_key": key,
        }

    def health(self) -> Dict[str, object]:
        return {
            "service": "crm-message-event-writeback",
            "event_type": "message.created",
            "dedup_key_prefix": "message.created:",
            "target": "activity_log",
        }


# =====================================================================
# Event-bus wiring
# =====================================================================

_subscribed = False


def register_crm_message_writeback_subscriber() -> int:
    """Subscribe the write-back handler to ``message.created`` (idempotent).

    Mirrors ``register_conversation_lead_subscriber``: each event is handled
    in its own DB session so the CRM side can never hold a publisher's
    transaction open. Returns the number of event types subscribed
    (1 = ``message.created``).
    """
    global _subscribed
    if _subscribed:
        return 1

    from app.db.session import AsyncSessionLocal

    bus = get_event_bus()

    async def _on_event(event: DomainEvent) -> None:
        db = AsyncSessionLocal()
        try:
            await CrmMessageEventWriteback(db).handle_domain_event(event)
        finally:
            await db.close()

    bus.subscribe("message.created", _on_event)
    _subscribed = True
    logger.info("crm-message-writeback: subscribed to message.created")
    return 1


def _is_subscribed() -> bool:
    return _subscribed


def reset_crm_message_writeback_subscriber() -> None:
    """Test helper: forget that the bus was wired."""
    global _subscribed
    _subscribed = False
