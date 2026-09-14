"""Message router — P5MSG-02 (real query / send / delivery-state API).

Populates the P5MSG-01 route skeleton with the actual behaviour:

    GET  /api/v1/messages               — paginated list + channel/direction/status filters
    GET  /api/v1/messages/{id}          — single message
    POST /api/v1/messages/send          — enqueue as ``queued`` (Phase-1 account binding check)
    POST /api/v1/messages/{id}/status   — delivery state machine (4003 on illegal transition)
    GET  /api/v1/messages/{id}/receipt — delivery / read receipt trail

Public paths are ``/api/v1/messages/...``: this router carries only the
``/messages`` sub-path and is included under ``prefix="/api/v1"`` in
``app.main`` (avoids the /api/v1/api/v1 double-prefix defect, t_b6b64212).

Response envelope is the PHASE1-API-SPEC ``{code, message, data}`` form
(``ok`` / local ``biz_error``). P5MSG-03 will add the channel adapters that
actually move ``queued -> sent``; until then the state machine is driven by
the ``/status`` endpoint (``source`` marks provider vs manual transitions).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.security import require_trusted_producer
from app.schemas.messages import (
    ApiCode,
    MessageListResponse,
    MessageReceiptResponse,
    MessageSendRequest,
    MessageStatusUpdateRequest,
    ok,
)
from app.services.message_service import (
    IllegalStateTransition,
    MessageParameterError,
    MessageResourceNotFound,
    MessageService,
    VALID_FILTER_STATUSES,
)

router = APIRouter(prefix="/messages", tags=["Messages"])


def get_message_service(db: AsyncSession = Depends(get_db)) -> MessageService:
    """Dependency for MessageService."""
    return MessageService(db)


def biz_error(status_code: int, code: int, message: str) -> HTTPException:
    """4xx whose body is the ``{code, message, data:None}`` error envelope.

    P5MSG-01 shipped ``ok`` / ``bad_request`` / ``not_implemented``; the
    delivery-state-machine codes (4001 not-found / 4003 illegal transition)
    are wrapped here to keep the envelope uniform.
    """
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "data": None},
    )


# ---------------------------------------------------------------------------
# Static paths MUST be registered ahead of the dynamic /{message_id} routes.
# ---------------------------------------------------------------------------


@router.get("", summary="列出渠道消息 (分页 + 过滤)")
async def list_messages(
    conversation_id: Optional[UUID] = Query(None, description="按会话筛选"),
    channel: Optional[str] = Query(None, description="按渠道筛选"),
    direction: Optional[str] = Query(None, description="in | out"),
    status: Optional[str] = Query(None, description=f"按投递状态筛选: {', '.join(sorted(VALID_FILTER_STATUSES))}"),
    page: int = Query(1, ge=1, description="页码 (1 起)"),
    page_size: int = Query(20, ge=1, le=100, description="页大小 (最大 100)"),
    service: MessageService = Depends(get_message_service),
):
    """Paginated channel-message list with channel/direction/status filters.

    Boundary validation (P5MSG-02 acceptance): page>=1 and 1<=page_size<=100
    are 422'd by FastAPI; out-of-domain filter values return 4002.
    """
    try:
        items, total, p, ps = await service.list_messages(
            page=page,
            page_size=page_size,
            conversation_id=conversation_id,
            channel=channel,
            direction=direction,
            status=status,
        )
    except MessageParameterError as e:
        raise biz_error(400, ApiCode.INVALID_PARAMETER, str(e))

    payload = MessageListResponse(
        items=items,
        total=total,
        page=p,
        page_size=ps,
        conversation_id=conversation_id,
        channel=channel,
        direction=direction,
        status=status,
    )
    return ok(payload.model_dump(mode="json"))


@router.post("/send", status_code=201, summary="发送消息 / 入队")
async def send_message(
    data: MessageSendRequest,
    service: MessageService = Depends(get_message_service),
):
    """Enqueue an outbound channel message (status=queued).

    Phase-1 resource-layer validation: the conversation must exist (4001)
    and a provided ``account_id`` must exist and be bound to the requested
    channel's platform (4002 on mismatch). Actual channel delivery is
    P5MSG-03; the state machine lives on ``/{id}/status``.

    P5MSG-FIX-2 (P1-2 note, owned by P5MSG-03): per-channel anti-abuse
    rate limiting is NOT enforced at this enqueue seam — P5MSG-03 is
    blocked (BitBrowser), so /send can still be enqueued unbounded. When
    P5MSG-03 lands the channel adapters MUST enforce the
    ``channel_config.rate_limit_per_hour`` policy (the
    ``ChannelRateLimiter`` + delivery-side check already exist in
    ``channel_delivery_service``); re-verify P5MSG-11 P1-2 at that time.
    """
    try:
        message = await service.send_message(data)
    except MessageResourceNotFound as e:
        raise biz_error(404, ApiCode.NOT_FOUND, str(e))
    except MessageParameterError as e:
        raise biz_error(400, ApiCode.INVALID_PARAMETER, str(e))
    return ok({"id": str(message.id), "status": message.status, "enqueued": True})


@router.get("/{message_id}", summary="获取单条消息")
async def get_message(message_id: UUID, service: MessageService = Depends(get_message_service)):
    """Fetch one channel message (4001/4004 when it does not exist)."""
    try:
        message = await service.get_message(message_id)
    except MessageResourceNotFound as e:
        raise biz_error(404, ApiCode.NOT_FOUND, str(e))
    from app.schemas.messages import MessageResponse
    return ok(MessageResponse.model_validate(message).model_dump(mode="json"))


@router.get("/{message_id}/receipt", summary="读取已读回执")
async def get_receipt(message_id: UUID, service: MessageService = Depends(get_message_service)):
    """Current delivery state plus the append-only receipt audit trail."""
    try:
        receipt: MessageReceiptResponse = await service.get_receipt(message_id)
    except MessageResourceNotFound as e:
        raise biz_error(404, ApiCode.NOT_FOUND, str(e))
    return ok(receipt.model_dump(mode="json"))


@router.post("/{message_id}/status", summary="推进投递状态机")
async def update_message_status(
    message_id: UUID,
    data: MessageStatusUpdateRequest,
    service: MessageService = Depends(get_message_service),
    _producer=Depends(require_trusted_producer),
):
    """Apply one delivery-state transition.

    P5MSG-FIX-1 (P0-2): driving the delivery state machine (queued->failed /
    read, etc.) is a cross-owner write primitive — any caller could previously
    advance *any* message. It now requires a trusted producer (Bearer); 异主
    callers are rejected (401 / 403).

    Allowed: queued->sent, queued->failed, sent->delivered, sent->read,
    sent->failed, delivered->read. Anything else is rejected with 4003.
    ``failed`` requires ``error`` details (422 when missing). Every accepted
    transition is recorded once in the ExecutionLog SoT
    (execution_type='message_status', ADR-017); the deprecated per-row
    ``receipts`` JSONB is no longer written.
    """
    try:
        message = await service.update_status(message_id, data)
    except MessageResourceNotFound as e:
        raise biz_error(404, ApiCode.NOT_FOUND, str(e))
    except IllegalStateTransition as e:
        raise biz_error(400, ApiCode.ILLEGAL_TRANSITION, str(e))
    from app.schemas.messages import MessageResponse
    return ok(MessageResponse.model_validate(message).model_dump(mode="json"))


__all__ = ["router"]
