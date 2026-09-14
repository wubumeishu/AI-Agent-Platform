"""Customer 360 message timeline service (P5MSG-05).

Roadmap Phase 2 Message/Conversation increment — CRM integration half.
Unifies the two message source tables into ONE reverse-chronological
timeline for the Customer 360 message view:

* ``message``  — Phase-2 AI chat transcripts (table ``message``, role + text)
* ``messages`` — P5MSG-01 channel delivery records (table ``messages``,
                 direction/status/content JSONB)

Both hang off ``conversation`` (``Conversation.customer_id`` FK, Phase 3
customer entity), so the customer's conversations are the join root. This
is a pure READ aggregation — no new tables, no schema changes, no writes;
the write-back half (idempotent CRM activity records) lives in
``app/crm/services/message_crm_writeback.py``.

Architecture separation (SOUL):
- The service is the single place that knows how to shape the two source
  tables into timeline entries; the router only maps errors and wraps the
  response envelope.
- P5MSG-02's channel-domain constants (``MESSAGE_CHANNELS``) are *consumed*
  read-only for filter validation — no channel-specific logic is copied
  into this module.

Error mapping (same dialect as the Customer 360 router):
* ``CustomerResourceNotFound`` -> HTTP 404 "客户不存在"
* ``TimelineParameterError``   -> HTTP 400 (out-of-domain filter value)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation, Message
from app.db.models.customer import Customer
from app.db.models.intent import Intent
from app.db.models.messages import ChannelMessage, MESSAGE_DIRECTIONS, MESSAGE_STATUSES
from app.schemas.messages import MESSAGE_CHANNELS

logger = logging.getLogger(__name__)

#: Timeline entry kinds. ``kind`` filter accepts exactly these two values.
TIMELINE_KINDS: Tuple[str, ...] = ("chat", "channel")

#: How many recent intent classifications the payload carries (P5MSG-05 scope:
#: "AI 意图数据落入 conversation/message 字段" — surfaced here so the 360 view
#: shows the customer's latest intent signals alongside their messages).
_RECENT_INTENTS_LIMIT = 20


class CustomerResourceNotFound(Exception):
    """404 — the referenced customer does not exist (or is deleted)."""


class TimelineParameterError(Exception):
    """400 — a filter value is outside its documented domain."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize a possibly-naive timestamp to aware-UTC (or pass through)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    out = _aware(dt)
    return out.isoformat() if out is not None else None


def _validate_filters(
    kind: Optional[str],
    channel: Optional[str],
    direction: Optional[str],
    status: Optional[str],
) -> None:
    """Reject out-of-domain filter values early (4002-class, raised as 400)."""
    if kind is not None and kind not in TIMELINE_KINDS:
        raise TimelineParameterError(
            f"kind must be one of {list(TIMELINE_KINDS)}, got {kind!r}"
        )
    if channel is not None and channel not in MESSAGE_CHANNELS:
        raise TimelineParameterError(
            f"channel must be one of {MESSAGE_CHANNELS}, got {channel!r}"
        )
    if direction is not None and direction not in MESSAGE_DIRECTIONS:
        raise TimelineParameterError(
            f"direction must be one of {MESSAGE_DIRECTIONS}, got {direction!r}"
        )
    if status is not None and status not in MESSAGE_STATUSES:
        raise TimelineParameterError(
            f"status must be one of {sorted(MESSAGE_STATUSES)}, got {status!r}"
        )


# ---------------------------------------------------------------------------
# queries (one per source table; filters applied per-source)
# ---------------------------------------------------------------------------


def _chat_query(
    customer_id: UUID,
    conversation_id: Optional[UUID],
    channel: Optional[str],
    start_time: Optional[datetime],
    end_time: Optional[datetime],
) -> Any:
    """Chat transcripts (table ``message``) for the customer, desc by time.

    ``channel`` filters on the *conversation's* channel (chat transcripts
    carry the channel only via the conversation). Direction/status filters
    are channel-delivery concepts and do not apply to chat entries.
    """
    q = (
        select(Message, Conversation.channel)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.customer_id == customer_id,
            Conversation.is_deleted == False,  # noqa: E712
            Message.is_deleted == False,  # noqa: E712
        )
    )
    if conversation_id is not None:
        q = q.where(Message.conversation_id == conversation_id)
    if channel is not None:
        q = q.where(Conversation.channel == channel)
    if start_time is not None:
        q = q.where(Message.created_at >= start_time)
    if end_time is not None:
        q = q.where(Message.created_at <= end_time)
    return q.order_by(Message.created_at.desc(), Message.id.desc())


def _channel_query(
    customer_id: UUID,
    conversation_id: Optional[UUID],
    channel: Optional[str],
    direction: Optional[str],
    status: Optional[str],
    start_time: Optional[datetime],
    end_time: Optional[datetime],
) -> Any:
    """Channel delivery records (table ``messages``) for the customer, desc."""
    q = (
        select(ChannelMessage)
        .join(Conversation, ChannelMessage.conversation_id == Conversation.id)
        .where(
            Conversation.customer_id == customer_id,
            Conversation.is_deleted == False,  # noqa: E712
            ChannelMessage.is_deleted == False,  # noqa: E712
        )
    )
    if conversation_id is not None:
        q = q.where(ChannelMessage.conversation_id == conversation_id)
    if channel is not None:
        q = q.where(ChannelMessage.channel == channel)
    if direction is not None:
        q = q.where(ChannelMessage.direction == direction)
    if status is not None:
        q = q.where(ChannelMessage.status == status)
    if start_time is not None:
        q = q.where(ChannelMessage.created_at >= start_time)
    if end_time is not None:
        q = q.where(ChannelMessage.created_at <= end_time)
    return q.order_by(ChannelMessage.created_at.desc(), ChannelMessage.id.desc())


def _chat_entry(msg: Message, conv_channel: Optional[str]) -> Dict[str, Any]:
    return {
        "kind": "chat",
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "channel": conv_channel,
        "role": msg.role,
        "content": msg.content,
        "created_at": _iso(msg.created_at),
    }


def _channel_entry(cm: ChannelMessage) -> Dict[str, Any]:
    return {
        "kind": "channel",
        "id": str(cm.id),
        "conversation_id": str(cm.conversation_id),
        "channel": cm.channel,
        "direction": cm.direction,
        "status": cm.status,
        "provider_message_id": cm.provider_message_id,
        "sent_at": _iso(cm.sent_at),
        "received_at": _iso(cm.received_at),
        "created_at": _iso(cm.created_at),
    }


def _merge(chat_items: List[Dict[str, Any]], channel_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """K-way merge of two desc-sorted lists (each already ordered by
    created_at desc, id desc). Stable and O(n+m)."""
    i = j = 0
    out: List[Dict[str, Any]] = []
    while i < len(chat_items) and j < len(channel_items):
        a, b = chat_items[i], channel_items[j]
        # Greater timestamp first; tiebreak on the larger UUID (id desc).
        ka, kb = a["_ts"], b["_ts"]
        if ka is None and kb is None:
            take_chat = a["id"] >= b["id"]
        elif ka is None:
            take_chat = False
        elif kb is None:
            take_chat = True
        else:
            take_chat = (ka, a["id"]) > (kb, b["id"])
        if take_chat:
            out.append(chat_items[i])
            i += 1
        else:
            out.append(channel_items[j])
            j += 1
    out.extend(chat_items[i:])
    out.extend(channel_items[j:])
    for entry in out:
        entry.pop("_ts", None)
    return out


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------


async def get_customer_message_timeline(
    db: AsyncSession,
    customer_id: UUID,
    *,
    conversation_id: Optional[UUID] = None,
    kind: Optional[str] = None,
    channel: Optional[str] = None,
    direction: Optional[str] = None,
    status: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 20,
) -> Dict[str, Any]:
    """Return the customer's unified message timeline (time descending).

    Raises ``CustomerResourceNotFound`` when the customer does not exist /
    is deleted, and ``TimelineParameterError`` for out-of-domain filters.
    """
    _validate_filters(kind, channel, direction, status)

    # 1. Customer must exist (live) — otherwise 404, no further work.
    customer_row = (
        await db.execute(
            select(Customer.id).where(
                Customer.id == customer_id,
                Customer.is_deleted == False,  # noqa: E712
            )
        )
    ).first()
    if customer_row is None:
        raise CustomerResourceNotFound(f"Customer not found: {customer_id}")

    # 2. Fetch each source (when the kind filter allows it).
    chat_items: List[Dict[str, Any]] = []
    channel_items: List[Dict[str, Any]] = []
    chat_total = 0
    channel_total = 0

    if kind in (None, "chat"):
        rows = (
            await db.execute(
                _chat_query(customer_id, conversation_id, channel, start_time, end_time)
            )
        ).all()
        for row in rows:
            msg, conv_channel = row[0], row[1]
            entry = _chat_entry(msg, conv_channel)
            entry["_ts"] = _aware(msg.created_at)
            chat_items.append(entry)
        chat_total = len(chat_items)

    if kind in (None, "channel"):
        rows = (
            await db.execute(
                _channel_query(
                    customer_id,
                    conversation_id,
                    channel,
                    direction,
                    status,
                    start_time,
                    end_time,
                )
            )
        ).scalars().all()
        for cm in rows:
            entry = _channel_entry(cm)
            entry["_ts"] = _aware(cm.created_at)
            channel_items.append(entry)
        channel_total = len(channel_items)

    merged = _merge(chat_items, channel_items)
    total = (chat_total if kind == "chat" else 0) + (channel_total if kind == "channel" else 0)
    if kind is None:
        total = chat_total + channel_total

    # 3. Recent intent classifications for this customer (P5MSG-05 scope:
    #    intent data surfaced in the 360 message view).
    intent_rows = (
        await db.execute(
            select(Intent)
            .join(Conversation, Intent.conversation_id == Conversation.id)
            .where(
                Conversation.customer_id == customer_id,
                Conversation.is_deleted == False,  # noqa: E712
                Intent.is_deleted == False,  # noqa: E712
            )
            .order_by(Intent.created_at.desc())
            .limit(_RECENT_INTENTS_LIMIT)
        )
    ).scalars().all()
    recent_intents = [
        {
            "id": str(i.id),
            "conversation_id": str(i.conversation_id),
            "intent_type": i.intent_type,
            "intent_name": i.intent_name,
            "confidence": i.confidence,
            "created_at": _iso(i.created_at),
        }
        for i in intent_rows
    ]

    return {
        "customer_id": str(customer_id),
        "total": total,
        "messages": merged[skip:skip + limit],
        "recent_intents": recent_intents,
        "skip": skip,
        "limit": limit,
    }
