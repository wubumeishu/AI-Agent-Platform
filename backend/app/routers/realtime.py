"""Realtime channel + conversation-management router — P5MSG-04.

Endpoints (all mounted under ``/api/v1/realtime`` by ``main.py``):

    GET  /api/v1/realtime                      — SSE stream: new-message,
                                                  read-report & delivery-status
                                                  changes, with replay + live.
    GET  /api/v1/realtime/conversations        — active conversation list with
                                                  last-message preview + unread.
    GET  /api/v1/realtime/unread               — unread aggregate.
    GET  /api/v1/realtime/resync              — JSON tail of the replay log
                                                  since a cursor (gap-fill).
    POST /api/v1/realtime/read                — mark a conversation read
                                                  (drives P5MSG-02 receipts +
                                                  emits a channel_message.read
                                                  event so badges clear live).
    POST /api/v1/realtime/publish              — ad-hoc event publish seam.

SSE framing (Phase-1 SSE style, ``text/event-stream``):
    event: hello     {type,head_seq,oldest_seq,gap,ts}
    event: replay    one RealtimeEvent per line (seq > since)
    event: message   one RealtimeEvent per line (live)
    : ping            keep-alive comment every ~15s

Reconnect / offline / dedup semantics:
* the client remembers the highest ``seq`` it has processed;
* on (re)connect it passes ``since`` -> the stream replays log entries with
  ``seq > since`` (the offline catch-up) then continues live;
* every event carries a stable ``seq`` so the client dedupes — an event
  already consumed has ``seq <= since`` and is never re-sent;
* if ``since`` is older than the retained log window, ``hello.gap`` is true
  and the client must fall back to a full REST resync (``/conversations``
  or ``/messages``); live delivery still continues.

No secrets / message PII in frames: events carry ids, a kind and a small
structured payload (ARCHITECTURE rule #16).
"""
import asyncio
import json
import logging
from typing import AsyncGenerator, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.realtime import (
    RealtimeConversationItem,
    RealtimeConversationListResponse,
    RealtimePublishRequest,
    RealtimeReadRequest,
    RealtimeResyncRequest,
    RealtimeUnreadSummary,
)
from app.security import require_trusted_producer
from app.services.realtime_conversation_service import RealtimeConversationService
from app.services.realtime_events import (
    REALTIME_EVENT_KINDS,
    publish_realtime_event,
)
from app.services.realtime_hub import get_realtime_hub

logger = logging.getLogger(__name__)

# How often to emit an SSE keep-alive comment so idle proxies don't drop us.
_SSE_KEEPALIVE_SECONDS = 15.0

router = APIRouter(prefix="/realtime", tags=["Realtime"])


def _sse(event: str, data: str) -> str:
    """One SSE frame: an ``event:`` name line + a ``data:`` JSON line."""
    return f"event: {event}\ndata: {data}\n\n"


def _sse_comment(text: str) -> str:
    return f": {text}\n\n"


# ===========================================================================
# GET /api/v1/realtime  — SSE stream (replay + live)
# ===========================================================================


@router.get("", summary="Realtime SSE stream (new messages, read reports, status changes)")
async def realtime_stream(
    conversation_id: Optional[UUID] = Query(
        None, description="Scope the stream to one conversation (omit for all)"
    ),
    since: int = Query(
        0,
        ge=0,
        description="Last seq you processed; 0 = from the oldest retained event",
    ),
):
    """Subscribe to the realtime channel.

    On connect: emits a ``hello`` frame, replays every retained event with
    ``seq > since`` (offline catch-up, dedup cursor), then streams live
    events as they are emitted. Emits a keep-alive comment every ~15s.
    """
    hub = get_realtime_hub()
    conv_scope = str(conversation_id) if conversation_id is not None else None
    sub_id, replay, live_queue = hub.subscribe(conversation_id=conv_scope, since=since)

    oldest = hub.oldest_seq
    head = hub.head_seq
    gap = since > 0 and since < oldest  # asked for something older than we keep

    async def stream() -> AsyncGenerator[str, None]:
        try:
            yield _sse(
                "hello",
                json.dumps(
                    {
                        "type": "hello",
                        "head_seq": head,
                        "oldest_seq": oldest,
                        "gap": gap,
                        "since": since,
                        "conversation_id": conv_scope,
                    }
                ),
            )

            # Offline catch-up: replay retained events with seq > since.
            if not gap:
                for ev in replay:
                    yield _sse("replay", json.dumps(ev.to_sse_dict()))

            # Live fan-out. Poll with a timeout so we can also emit
            # keep-alives; a closed generator (client gone) ends the task.
            while True:
                try:
                    ev = await asyncio.wait_for(
                        live_queue.get(), timeout=_SSE_KEEPALIVE_SECONDS
                    )
                    yield _sse("message", json.dumps(ev.to_sse_dict()))
                except asyncio.TimeoutError:
                    yield _sse_comment("keep-alive")
                except asyncio.CancelledError:
                    raise
        finally:
            hub.unsubscribe(sub_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ===========================================================================
# GET /api/v1/realtime/conversations  — active list + preview + unread
# ===========================================================================


@router.get(
    "/conversations",
    response_model=RealtimeConversationListResponse,
    summary="Active conversation list with last-message preview + unread",
)
async def realtime_conversations(
    customer_id: Optional[UUID] = Query(
        None,
        description="Scope by customer. P5MSG-FIX-2 (P1-3): required — "
        "platform-wide previews are no longer served (cross-customer PII).",
    ),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    redact_preview: bool = Query(
        False,
        description="P5MSG-FIX-2 (P1-3): opt-in PII scrubbing of the "
        "last-message preview (emails -> [EMAIL], CN phones -> [PHONE]).",
    ),
    db: AsyncSession = Depends(get_db),
    _producer=Depends(require_trusted_producer),
):
    """The live conversation list a UI renders and keeps in sync via the
    ``/realtime`` stream: active conversations, latest preview, unread count.

    P5MSG-FIX-2 (P1-3): the preview carries customer message text (PII).
    The endpoint now requires a trusted producer Bearer (401/403 for 异主
    callers) and a *customer-ownership* filter — a platform-wide broadcast
    of every customer's last-message preview is rejected (422), and an
    unknown ``customer_id`` is a 404 (the ownership check below).
    """
    from sqlalchemy import select

    from app.db.models.customer import Customer

    if customer_id is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": 4002,
                "message": (
                    "customer_id is required: cross-customer message previews "
                    "are not served (P1-3 PII scoping)"
                ),
                "data": None,
            },
        )
    exists = (
        await db.execute(
            select(Customer.id).where(
                Customer.id == customer_id, Customer.is_deleted == False  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": 4004,
                "message": f"customer {customer_id} not found",
                "data": None,
            },
        )
    service = RealtimeConversationService(db)
    rows = await service.list_active_conversations(
        customer_id=customer_id,
        channel=channel,
        page=page,
        page_size=page_size,
        redact_preview=redact_preview,
    )
    items = [
        RealtimeConversationItem(
            conversation_id=r.conversation_id,
            customer_id=r.customer_id,
            channel=r.channel,
            subject=r.subject,
            status=r.status,
            last_message_at=r.last_message_at,
            last_message_preview=r.last_message_preview,
            unread_count=r.unread_count,
            message_count=r.message_count,
        )
        for r in rows
    ]
    total_unread = await service.unread_total(customer_id=customer_id)
    return RealtimeConversationListResponse(
        items=items, total_unread=total_unread, page=page, page_size=page_size
    )


# ===========================================================================
# GET /api/v1/realtime/unread  — unread aggregate
# ===========================================================================


@router.get("/unread", response_model=RealtimeUnreadSummary, summary="Unread aggregate")
async def realtime_unread(
    customer_id: Optional[UUID] = Query(
        None,
        description="Scope to one customer. P5MSG-FIX-2 (P1-3): required — "
        "a platform-wide unread view would broadcast every customer's "
        "last-message preview (cross-customer PII).",
    ),
    redact_preview: bool = Query(
        False,
        description="P5MSG-FIX-2 (P1-3): opt-in PII scrubbing of the "
        "last-message preview (emails -> [EMAIL], CN phones -> [PHONE]).",
    ),
    db: AsyncSession = Depends(get_db),
    _producer=Depends(require_trusted_producer),
):
    """Unread aggregate for *one* customer's conversations.

    P5MSG-FIX-2 (P1-3): the response embeds per-conversation
    ``last_message_preview`` text, so it is auth-gated (trusted producer
    Bearer, 401/403 for 异主 callers) and customer-scoped — an absent
    ``customer_id`` is a 422, and an unknown one is a 404.
    """
    from sqlalchemy import select

    from app.db.models.customer import Customer

    if customer_id is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": 4002,
                "message": (
                    "customer_id is required: cross-customer unread/preview "
                    "views are not served (P1-3 PII scoping)"
                ),
                "data": None,
            },
        )
    exists = (
        await db.execute(
            select(Customer.id).where(
                Customer.id == customer_id, Customer.is_deleted == False  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": 4004,
                "message": f"customer {customer_id} not found",
                "data": None,
            },
        )
    service = RealtimeConversationService(db)
    total = await service.unread_total(customer_id=customer_id)
    rows = await service.list_active_conversations(
        customer_id=customer_id, page=1, page_size=100, redact_preview=redact_preview
    )
    with_unread = [
        RealtimeConversationItem(
            conversation_id=r.conversation_id,
            customer_id=r.customer_id,
            channel=r.channel,
            subject=r.subject,
            status=r.status,
            last_message_at=r.last_message_at,
            last_message_preview=r.last_message_preview,
            unread_count=r.unread_count,
            message_count=r.message_count,
        )
        for r in rows
        if r.unread_count > 0
    ]
    return RealtimeUnreadSummary(total_unread=total, by_conversation=with_unread)


# ===========================================================================
# GET /api/v1/realtime/resync  — JSON tail of the replay log (gap-fill)
# ===========================================================================


@router.get("/resync", response_model=dict, summary="Replay retained events since a cursor")
async def realtime_resync(
    since: int = Query(0, ge=0, description="Last seq processed"),
    conversation_id: Optional[UUID] = Query(None, description="Scope to one conversation"),
    limit: int = Query(200, ge=1, le=1000, description="Max events to return"),
):
    """Non-streaming replay of the hub's retained log (offline catch-up for
    clients that prefer a one-shot JSON fetch over an open SSE connection).

    ``gap`` is true when ``since`` predates the retained window — the client
    must then fall back to a full REST resync. Returns the retained events
    (newest bounded by ``limit``) plus the current head/oldest seq so the
    client can advance its cursor.
    """
    hub = get_realtime_hub()
    conv_scope = str(conversation_id) if conversation_id is not None else None
    events = hub._replay_events(conv_scope, since)  # seq > since, oldest first
    gap = since > 0 and since < hub.oldest_seq
    tail = events[-limit:] if limit else events
    return {
        "since": since,
        "head_seq": hub.head_seq,
        "oldest_seq": hub.oldest_seq,
        "gap": gap,
        "count": len(tail),
        "events": [e.to_sse_dict() for e in tail],
    }


# ===========================================================================
# POST /api/v1/realtime/read  — mark a conversation read
# ===========================================================================


@router.post("/read", response_model=dict, summary="Mark a conversation read (drives P5MSG-02 receipts)")
async def realtime_mark_read(
    data: RealtimeReadRequest,
    db: AsyncSession = Depends(get_db),
    _producer=Depends(require_trusted_producer),
):
    """Mark inbound messages in a conversation as read.

    P5MSG-FIX-1 (P0-2): this is a cross-owner write primitive (any caller
    could mark *any* conversation read), so it now requires a trusted
    producer (Bearer). 异主 callers get 401/403.

    For each not-yet-read inbound channel message, drive P5MSG-02's
    delivery state machine to ``read`` (which records the transition in
    the ExecutionLog SoT, ADR-017) and then emit a ``channel_message.read``
    event so every live subscriber clears its unread badge. Illegal
    transitions (e.g. a message stuck in ``queued``) are logged and skipped,
    not fatal — a single anomalous row must not block the whole read action.
    """
    from app.db.models.messages import ChannelMessage
    from app.schemas.messages import MessageStatusUpdateRequest
    from app.services.message_service import (
        IllegalStateTransition,
        MessageService,
    )
    from sqlalchemy import and_, select

    service = MessageService(db)
    base_filter = and_(
        ChannelMessage.conversation_id == data.conversation_id,
        ChannelMessage.is_deleted == False,  # noqa: E712
        ChannelMessage.direction == "in",
        ChannelMessage.status != "read",
    )
    if data.message_ids:
        base_filter = and_(base_filter, ChannelMessage.id.in_(data.message_ids))

    rows = (await db.execute(select(ChannelMessage.id).where(base_filter))).scalars().all()

    marked: List[str] = []
    skipped: List[str] = []
    for msg_id in rows:
        try:
            await service.update_status(
                msg_id,
                MessageStatusUpdateRequest(status="read", source="manual"),
            )
            marked.append(str(msg_id))
        except IllegalStateTransition:
            skipped.append(str(msg_id))
            logger.warning(
                "realtime/read: msg %s not in a read-able state (skipped)", msg_id
            )

    # Live-update every subscriber: badges clear as the event lands.
    payload = {
        "conversation_id": str(data.conversation_id),
        "marked_read": len(marked),
        "skipped": len(skipped),
    }
    seq = publish_realtime_event(
        "channel_message.read",
        conversation_id=str(data.conversation_id),
        payload=payload,
        dedup_id=f"read:{data.conversation_id}",
    )
    return {
        "code": 0,
        "message": "success",
        "data": {
            "conversation_id": str(data.conversation_id),
            "marked_read": len(marked),
            "marked_message_ids": marked,
            "skipped": skipped,
            "emitted_seq": seq,
        },
    }


# ===========================================================================
# POST /api/v1/realtime/publish  — ad-hoc event publish seam
# ===========================================================================


@router.post("/publish", response_model=dict, status_code=202, summary="Publish a realtime event")
async def realtime_publish(
    data: RealtimePublishRequest,
    db: AsyncSession = Depends(get_db),
    _producer=Depends(require_trusted_producer),
):
    """Direct push seam: producers (P5MSG-02/03) that prefer the API over the
    bus can post an event here.

    P5MSG-FIX-1 (P0-3): this seam is now auth-gated (trusted producer Bearer)
    and the payload runs the ``RealtimePublishRequest`` strong schema (bounded
    keys, length caps, PII/secret rejection -> 422), so an attacker can no
    longer pollute every live SSE subscriber + the persistent replay log.
    ``kind`` must be a known realtime kind.
    """
    if data.kind not in REALTIME_EVENT_KINDS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": 4002,
                "message": f"kind must be one of: {', '.join(REALTIME_EVENT_KINDS)}",
            },
        )
    conv = str(data.conversation_id) if data.conversation_id else None
    seq = publish_realtime_event(
        data.kind,
        conversation_id=conv,
        payload=data.payload,
        dedup_id=data.dedup_id,
    )
    return {
        "code": 0,
        "message": "accepted" if seq is not None else "duplicate_dropped",
        "data": {"kind": data.kind, "conversation_id": conv, "emitted_seq": seq},
    }
