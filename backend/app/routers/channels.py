"""Channel router — P5MSG-03 (channel-configuration CRUD + channel delivery).

Replaces the P5MSG-01 skeleton (which answered with the 4001 not-implemented
envelope) with the real behaviour the P5MSG-03 card owns:

    GET    /api/v1/channels            — paginated channel-config list + filters
    GET    /api/v1/channels/{id}       — single channel config
    POST   /api/v1/channels            — create a channel config (201)
    PUT    /api/v1/channels/{id}       — update a channel config
    DELETE /api/v1/channels/{id}       — soft-delete a channel config
    POST   /api/v1/channels/deliver    — deliver a queued message (adapter + retry + rate limit)
    POST   /api/v1/channels/poll       — pull inbound messages for a conversation

Response envelope is the PHASE1-API-SPEC ``{code, message, data}`` form (``ok`` /
local ``biz_error``), the same dialect P5MSG-01/02 established in
``app.schemas.messages``.

Static paths (``/deliver`` / ``/poll``) MUST be registered ahead of the dynamic
``/{channel_id}`` routes (same ordering rule as P5MSG-02's ``/send``): otherwise
the UUID-capture route would swallow them and return 422.

Delivery (``/deliver``) wires the business service to the channel adapter + rate
limiter; the platform *how* (BitBrowser) stays in the adapter, the *what*
(rate gate / retry / state machine / persistence) stays in the service.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.messages import (
    ApiCode,
    ChannelConfigCreate,
    ChannelConfigResponse,
    ChannelConfigUpdate,
    ChannelDeliverRequest,
    ChannelDeliverResponse,
    ChannelPollRequest,
    ChannelPollResponse,
    ok,
)
from app.services.channel_config_service import (
    ChannelConfigConflict,
    ChannelConfigNotFound,
    ChannelConfigParameterError,
    ChannelConfigService,
)
from app.services.channel_delivery_service import (
    ChannelDeliveryError,
    ChannelDeliveryService,
    DeliveryOutcome,
    RateLimitedDelivery,
)
from app.adapters.channel_adapter import UnsupportedChannelError
from app.services.message_service import MessageParameterError, MessageResourceNotFound


router = APIRouter(prefix="/channels", tags=["Channels"])


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------
def get_channel_config_service(db: AsyncSession = Depends(get_db)) -> ChannelConfigService:
    return ChannelConfigService(db)


def get_channel_delivery_service(db: AsyncSession = Depends(get_db)) -> ChannelDeliveryService:
    return ChannelDeliveryService(db)


def biz_error(status_code: int, code: int, message: str) -> HTTPException:
    """4xx whose body is the ``{code, message, data:None}`` error envelope."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "data": None},
    )


# ---------------------------------------------------------------------------
# Static delivery / poll paths — MUST precede the /{channel_id} dynamic routes.
# ---------------------------------------------------------------------------
@router.post("/deliver", summary="投递一条排队中的渠道消息 (P5MSG-03)")
async def deliver_message(
    data: ChannelDeliverRequest,
    service: ChannelDeliveryService = Depends(get_channel_delivery_service),
):
    """Drive one *queued* outbound message through its channel adapter.

    Applies the channel config's rate-limit gate + retry strategy, then advances
    the P5MSG-02 delivery state machine to ``sent`` (success) or ``failed``
    (error recorded). Rate-limited attempts are marked ``failed`` with a
    ``rate_limited`` error so the failure is observable.
    """
    try:
        outcome: DeliveryOutcome = await service.deliver_message(
            data.message_id,
            attempt_backoff=data.attempt_backoff_seconds,
        )
    except MessageResourceNotFound as e:
        raise biz_error(404, ApiCode.NOT_FOUND, str(e))
    except RateLimitedDelivery as e:
        # Defensive: the service currently *returns* a rate-limited attempt as
        # a ``failed`` outcome (handled below) rather than raising this; the
        # branch is kept so a future revert to the raising contract still
        # reports cleanly instead of a 500.
        return ok(_failure_response(data.message_id, e))
    except MessageParameterError as e:
        raise biz_error(400, ApiCode.INVALID_PARAMETER, str(e))
    except UnsupportedChannelError as e:
        raise biz_error(400, ApiCode.INVALID_PARAMETER, str(e))
    except ChannelDeliveryError as e:
        raise biz_error(400, ApiCode.INVALID_PARAMETER, str(e))

    # ``deliver_message`` returns a ``DeliveryOutcome``: the persisted
    # ``ChannelMessage`` plus the adapter-level ``mock`` / ``provider`` flags
    # the DB row does not carry. Rate-limited attempts already land here as a
    # ``failed`` outcome with a structured ``rate_limited`` error, so the
    # response renders them without any special-casing.
    status = outcome.message.status
    response = ChannelDeliverResponse(
        message_id=data.message_id,
        status=status,
        provider_message_id=outcome.provider_message_id,
        error=outcome.error,
        delivered=outcome.delivered,
    )
    response.mock = outcome.mock
    response.provider = outcome.provider
    return ok(response.model_dump(mode="json"))


@router.post("/poll", summary="拉取渠道入站消息 (P5MSG-03)")
async def poll_inbound(
    data: ChannelPollRequest,
    service: ChannelDeliveryService = Depends(get_channel_delivery_service),
):
    """Pull inbound messages for a conversation via the channel adapter.

    Persisted as inbound ``in`` channel records (deduped by provider id). V1
    mock adapters return an empty poll (no inbound source) — the endpoint is
    still exercised end-to-end and reports ``polled: 0``.
    """
    try:
        records = await service.poll_inbound(
            data.channel,
            conversation_id=data.conversation_id,
            account_id=data.account_id,
            limit=data.limit,
            since=data.since,
        )
    except UnsupportedChannelError as e:
        raise biz_error(400, ApiCode.INVALID_PARAMETER, str(e))
    except MessageResourceNotFound as e:
        raise biz_error(404, ApiCode.NOT_FOUND, str(e))

    response = ChannelPollResponse(
        channel=data.channel,
        conversation_id=data.conversation_id,
        polled=len(records),
        provider_message_ids=[
            r.provider_message_id for r in records if r.provider_message_id
        ],
    )
    return ok(response.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Dynamic /{channel_id} CRUD (registered AFTER the static paths above).
# ---------------------------------------------------------------------------
@router.get("", summary="列出渠道配置 (分页 + 过滤)")
async def list_channels(
    channel: Optional[str] = Query(None, description=f"按渠道类型筛选"),
    account_id: Optional[UUID] = Query(None, description="按绑定账号筛选"),
    enabled: Optional[bool] = Query(None, description="按启用状态筛选"),
    page: int = Query(1, ge=1, description="页码 (1 起)"),
    page_size: int = Query(20, ge=1, le=100, description="页大小 (最大 100)"),
    service: ChannelConfigService = Depends(get_channel_config_service),
):
    """Paginated channel-config list with channel / account / enabled filters."""
    try:
        items, total, p, ps = await service.list_configs(
            page=page, page_size=page_size,
            channel=channel, account_id=account_id, enabled=enabled,
        )
    except ChannelConfigParameterError as e:
        raise biz_error(400, ApiCode.INVALID_PARAMETER, str(e))

    payload = {
        "items": [ChannelConfigResponse.model_validate(i).model_dump(mode="json") for i in items],
        "total": total,
        "page": p,
        "page_size": ps,
        "channel": channel,
        "account_id": account_id,
        "enabled": enabled,
    }
    return ok(payload)


@router.get("/{channel_id}", summary="获取单个渠道配置")
async def get_channel(
    channel_id: UUID,
    service: ChannelConfigService = Depends(get_channel_config_service),
):
    """Fetch one channel config (4001 when it does not exist)."""
    try:
        config = await service.get_config(channel_id)
    except ChannelConfigNotFound as e:
        raise biz_error(404, ApiCode.NOT_FOUND, str(e))
    return ok(ChannelConfigResponse.model_validate(config).model_dump(mode="json"))


@router.post("", status_code=201, summary="创建渠道配置")
async def create_channel(
    payload: ChannelConfigCreate,
    service: ChannelConfigService = Depends(get_channel_config_service),
):
    """Create a channel delivery config (201). Duplicate live binding -> 4002."""
    try:
        config = await service.create_config(payload)
    except ChannelConfigParameterError as e:
        raise biz_error(400, ApiCode.INVALID_PARAMETER, str(e))
    except ChannelConfigConflict as e:
        raise biz_error(400, ApiCode.INVALID_PARAMETER, str(e))
    return ok(ChannelConfigResponse.model_validate(config).model_dump(mode="json"))


@router.put("/{channel_id}", summary="更新渠道配置")
async def update_channel(
    channel_id: UUID,
    payload: ChannelConfigUpdate,
    service: ChannelConfigService = Depends(get_channel_config_service),
):
    """Partially update a channel config (only set fields applied)."""
    try:
        config = await service.update_config(channel_id, payload)
    except ChannelConfigNotFound as e:
        raise biz_error(404, ApiCode.NOT_FOUND, str(e))
    except ChannelConfigParameterError as e:
        raise biz_error(400, ApiCode.INVALID_PARAMETER, str(e))
    except ChannelConfigConflict as e:
        raise biz_error(400, ApiCode.INVALID_PARAMETER, str(e))
    return ok(ChannelConfigResponse.model_validate(config).model_dump(mode="json"))


@router.delete("/{channel_id}", summary="软删除渠道配置")
async def delete_channel(
    channel_id: UUID,
    service: ChannelConfigService = Depends(get_channel_config_service),
):
    """Soft-delete a channel config (idempotent within a live config)."""
    try:
        deleted = await service.delete_config(channel_id)
    except ChannelConfigNotFound as e:
        raise biz_error(404, ApiCode.NOT_FOUND, str(e))
    return ok({"id": str(channel_id), "deleted": deleted})


def _failure_response(message_id: UUID, exc: RateLimitedDelivery) -> dict:
    """Build the deliver response body when the attempt was rate-limited."""
    return {
        "message_id": str(message_id),
        "status": "failed",
        "provider_message_id": None,
        "error": {
            "code": "rate_limited",
            "message": f"channel is rate-limited at {exc.limit}/h",
            "limit_per_hour": exc.limit,
        },
        "mock": False,
        "provider": "bitbrowser",
        "delivered": False,
    }


__all__ = ["router"]
