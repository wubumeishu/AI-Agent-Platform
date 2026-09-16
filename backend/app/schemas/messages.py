"""Pydantic schemas + standard API envelope for the Message module (P5MSG-01).

Two responsibilities:

1. *Channel-message schemas* — the request / response / list models for the
   ``messages`` delivery-record table (Roadmap Phase-2 Message/Conversation
   increment). P5MSG-02 drives the real query/send API on top of the
   ``Message*`` shapes below; P5MSG-03 owns channel adapters.

2. *Standard ``{code, message, data}`` envelope* — the PHASE1-API-SPEC common
   response contract used across the CRM routers, promoted here as a small
   reusable helper so the Message / Channel routers speak the same dialect as
   the rest of the platform. Business codes:

     0    success
     4001 not-implemented / resource-missing
     4002 parameter / validation error
     4003 illegal state transition

The envelope helpers are framework-agnostic: they return plain dicts on the
success path and raise a FastAPI ``HTTPException`` whose ``detail`` is the
error envelope on the failure path, so a global error handler can render it
uniformly without per-router duplication.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, model_validator, field_validator

from app.db.models.messages import (
    MESSAGE_DIRECTIONS,
    MESSAGE_STATUSES,
)

# ---------------------------------------------------------------------------
# Business error-code constants (shared platform contract)
# ---------------------------------------------------------------------------
class ApiCode:
    """Business error codes carried inside the ``code`` field of the envelope."""
    SUCCESS = 0
    NOT_IMPLEMENTED = 4001   # skeleton endpoint / not yet built (P5MSG-01..04)
    NOT_FOUND = 4004
    INVALID_PARAMETER = 4002
    ILLEGAL_TRANSITION = 4003


# ---------------------------------------------------------------------------
# Envelope helpers ({code, message, data})
# ---------------------------------------------------------------------------
def ok(data=None, message: str = "success") -> dict:
    """Success envelope: ``{"code": 0, "message": "success", "data": ...}``."""
    return {"code": ApiCode.SUCCESS, "message": message, "data": data}


def not_implemented(feature: str) -> HTTPException:
    """Raise a 501 whose body is the ``{code:4001,...}`` error envelope.

    P5MSG-01 ships *route skeletons only* — the concrete query/send logic is
    P5MSG-02..04. The skeleton endpoint is registered and reachable (so
    clients and the OpenAPI docs see it), but it answers with a well-formed
    envelope carrying the unified not-implemented business code 4001 rather
    than an ad-hoc 501 body.
    """
    detail = {"code": ApiCode.NOT_IMPLEMENTED,
              "message": f"{feature}: not implemented yet (P5MSG-01 skeleton)",
              "data": None}
    return HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                         detail=detail)


def bad_request(message: str) -> HTTPException:
    """Raise a 400 whose body is the ``{code:4002,...}`` error envelope."""
    detail = {"code": ApiCode.INVALID_PARAMETER, "message": message, "data": None}
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# ---------------------------------------------------------------------------
# Channel-message request / response schemas (P5MSG-02 shapes)
# ---------------------------------------------------------------------------

#: Channel value domain. Superset of the Phase-1 ChannelType seeds
#: (wechat / wechat_work / email / sms / whatsapp / line / other) plus the
#: generic ``web`` channel the platform defaults to.
MESSAGE_CHANNELS = [
    "web",
    "wechat",
    "wechat_work",
    "email",
    "sms",
    "whatsapp",
    "line",
    "douyin",
    "xiaohongshu",
    "other",
]

#: Who reports a delivery-state transition (receipt ``source``).
MESSAGE_RECEIPT_SOURCES = ["provider", "manual"]


class MessageSendRequest(BaseModel):
    """Enqueue an outbound channel message (status starts ``queued``)."""
    conversation_id: UUID = Field(..., description="Owning conversation (must exist)")
    account_id: Optional[UUID] = Field(None, description="Sending account (Phase-1 resource-layer validation)")
    agent_id: Optional[UUID] = Field(None, description="Acting agent")
    channel: str = Field("web", description=f"Channel code; one of {MESSAGE_CHANNELS}")
    direction: str = Field("out", description=f"Message direction; one of {MESSAGE_DIRECTIONS}")
    content: Dict[str, object] = Field(
        ..., min_length=1,
        description="Structured payload (text, media refs, platform fields); must be non-empty",
    )
    provider_message_id: Optional[str] = Field(None, max_length=200, description="Provider-side message id")

    @field_validator("channel")
    @classmethod
    def _channel_in_domain(cls, v: str) -> str:
        if v not in MESSAGE_CHANNELS:
            raise ValueError(f"channel must be one of {MESSAGE_CHANNELS}, got {v!r}")
        return v

    @field_validator("direction")
    @classmethod
    def _direction_in_domain(cls, v: str) -> str:
        if v not in MESSAGE_DIRECTIONS:
            raise ValueError(f"direction must be one of {MESSAGE_DIRECTIONS}, got {v!r}")
        return v


class MessageStatusUpdateRequest(BaseModel):
    """One delivery-state transition (see MessageService state machine).

    ``failed`` REQUIRES ``error`` details (422 when missing).
    """
    status: str = Field(..., description=f"Target status; one of {MESSAGE_STATUSES}")
    source: str = Field("manual", description=f"Who reports the transition; one of {MESSAGE_RECEIPT_SOURCES}")
    error: Optional[Dict[str, object]] = Field(None, description="Failure details (REQUIRED when status=failed)")
    provider_message_id: Optional[str] = Field(None, max_length=200, description="Provider-side message id (optional stamp)")

    @field_validator("status")
    @classmethod
    def _status_in_domain(cls, v: str) -> str:
        if v not in MESSAGE_STATUSES:
            raise ValueError(f"status must be one of {MESSAGE_STATUSES}, got {v!r}")
        return v

    @field_validator("source")
    @classmethod
    def _source_in_domain(cls, v: str) -> str:
        if v not in MESSAGE_RECEIPT_SOURCES:
            raise ValueError(f"source must be one of {MESSAGE_RECEIPT_SOURCES}, got {v!r}")
        return v

    @model_validator(mode="after")
    def _failed_requires_error(self) -> "MessageStatusUpdateRequest":
        if self.status == "failed" and not self.error:
            raise ValueError("error details are required when status='failed'")
        return self


class MessageResponse(BaseModel):
    """Read model for one channel-message delivery record (table ``messages``)."""
    id: UUID
    conversation_id: UUID
    account_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    channel: str
    direction: str
    status: str
    content: Dict[str, object] = Field(default_factory=dict)
    provider_message_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    error: Optional[Dict[str, object]] = None
    created_at: datetime
    updated_at: datetime
    is_deleted: bool = False

    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    """Paginated channel-message list (P5MSG-02 GET /api/v1/messages)."""
    items: List[MessageResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20

    # filter echoes so clients can verify their query was applied
    conversation_id: Optional[UUID] = None
    channel: Optional[str] = None
    direction: Optional[str] = None
    status: Optional[str] = None


class MessageReceipt(BaseModel):
    """One entry of the append-only receipt audit trail."""
    status: str
    at: Optional[datetime] = None
    source: str = "manual"
    error: Optional[Dict[str, object]] = None
    provider_message_id: Optional[str] = None


class MessageReceiptResponse(BaseModel):
    """GET /api/v1/messages/{id}/receipt — current state + full audit trail."""
    message_id: UUID
    status: str
    error: Optional[Dict[str, object]] = None
    provider_message_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    last_receipt_at: Optional[datetime] = None
    receipts: List[MessageReceipt] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Channel config (P5MSG-03) — the real CRUD + delivery request/response shapes.
# P5MSG-01 shipped ``ChannelConfigResponse`` as the documented *skeleton* read
# shape; P5MSG-03 extends it to the full read model and adds the write +
# delivery request/response models the channel router implements.
# ---------------------------------------------------------------------------

#: Channel capability types. V1 ships ``messaging`` delivery; ``comment`` and
#: ``web`` are permitted by schema but their adapters are not wired yet.
CHANNEL_TYPES = ["messaging", "comment", "web"]


class ChannelConfigResponse(BaseModel):
    """A configured channel binding (type + account + rate limit + retry).

    P5MSG-03 read model backed by the ``channel_config`` table.
    """
    id: Optional[UUID] = None
    channel: str
    type: str = Field("messaging", description=f"Channel type; one of {CHANNEL_TYPES}")
    platform_code: Optional[str] = None
    account_id: Optional[UUID] = None
    rate_limit_per_hour: int = Field(60, ge=0)
    retry_max_attempts: int = Field(3, ge=1)
    retry_backoff_seconds: int = Field(5, ge=0)
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_deleted: bool = False

    model_config = {"from_attributes": True}

    @field_validator("channel")
    @classmethod
    def _channel_in_domain(cls, v: str) -> str:
        if v not in MESSAGE_CHANNELS:
            raise ValueError(f"channel must be one of {MESSAGE_CHANNELS}, got {v!r}")
        return v

    @field_validator("type")
    @classmethod
    def _type_in_domain(cls, v: str) -> str:
        if v not in CHANNEL_TYPES:
            raise ValueError(f"type must be one of {CHANNEL_TYPES}, got {v!r}")
        return v


class ChannelConfigCreate(BaseModel):
    """POST /api/v1/channels — create a channel delivery config."""
    channel: str
    type: str = Field("messaging", description=f"one of {CHANNEL_TYPES}")
    platform_code: Optional[str] = Field(None, max_length=50)
    account_id: Optional[UUID] = None
    rate_limit_per_hour: int = Field(60, ge=0)
    retry_max_attempts: int = Field(3, ge=1)
    retry_backoff_seconds: int = Field(5, ge=0)
    enabled: bool = True

    @field_validator("channel")
    @classmethod
    def _channel_in_domain(cls, v: str) -> str:
        if v not in MESSAGE_CHANNELS:
            raise ValueError(f"channel must be one of {MESSAGE_CHANNELS}, got {v!r}")
        return v

    @field_validator("type")
    @classmethod
    def _type_in_domain(cls, v: str) -> str:
        if v not in CHANNEL_TYPES:
            raise ValueError(f"type must be one of {CHANNEL_TYPES}, got {v!r}")
        return v


class ChannelConfigUpdate(BaseModel):
    """PUT /api/v1/channels/{id} — partial update (only set fields applied)."""
    channel: Optional[str] = None
    type: Optional[str] = None
    platform_code: Optional[str] = None
    account_id: Optional[UUID] = None
    rate_limit_per_hour: Optional[int] = Field(None, ge=0)
    retry_max_attempts: Optional[int] = Field(None, ge=1)
    retry_backoff_seconds: Optional[int] = Field(None, ge=0)
    enabled: Optional[bool] = None

    @field_validator("channel")
    @classmethod
    def _channel_in_domain(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in MESSAGE_CHANNELS:
            raise ValueError(f"channel must be one of {MESSAGE_CHANNELS}, got {v!r}")
        return v

    @field_validator("type")
    @classmethod
    def _type_in_domain(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in CHANNEL_TYPES:
            raise ValueError(f"type must be one of {CHANNEL_TYPES}, got {v!r}")
        return v


# --- delivery request / response (POST /api/v1/channels/deliver) -----------

class ChannelDeliverRequest(BaseModel):
    """POST /api/v1/channels/deliver — deliver a queued outbound message.

    The message's ``channel`` + ``account_id`` select the channel config whose
    rate-limit and retry strategy are applied.
    """
    message_id: UUID
    attempt_backoff_seconds: Optional[int] = Field(
        None, ge=0,
        description="Override the configured retry backoff (seconds) for this delivery",
    )


class ChannelDeliverResponse(BaseModel):
    """Outcome of one delivery run."""
    message_id: UUID
    status: str  # "sent" | "failed"
    provider_message_id: Optional[str] = None
    error: Optional[Dict[str, object]] = None
    mock: bool = False
    provider: str = "bitbrowser"
    delivered: bool  # True when the final status is "sent"


class ChannelPollRequest(BaseModel):
    """POST /api/v1/channels/poll — pull inbound messages for a conversation."""
    channel: str
    conversation_id: UUID
    account_id: Optional[UUID] = None
    limit: int = Field(20, ge=1, le=100)
    since: Optional[datetime] = None

    @field_validator("channel")
    @classmethod
    def _channel_in_domain(cls, v: str) -> str:
        if v not in MESSAGE_CHANNELS:
            raise ValueError(f"channel must be one of {MESSAGE_CHANNELS}, got {v!r}")
        return v


class ChannelPollResponse(BaseModel):
    """How many inbound messages were newly captured by the poll."""
    channel: str
    conversation_id: UUID
    polled: int
    provider_message_ids: List[str] = Field(default_factory=list)


# Backward-compatible P5MSG-01 aliases (P5MSG-01 originally named the message
# shapes ``ChannelMessage*``; P5MSG-02 established the canonical ``Message*``
# names and its service + whole tree import those. The aliases keep the
# P5MSG-01 names resolving so either spelling works; new code uses the
# canonical ``Message*`` names).
ChannelMessageBase = MessageSendRequest
ChannelMessageCreate = MessageSendRequest
ChannelMessageResponse = MessageResponse
ChannelMessageListResponse = MessageListResponse

__all__ = [
    "ApiCode",
    "ok",
    "not_implemented",
    "bad_request",
    "MESSAGE_CHANNELS",
    "MESSAGE_RECEIPT_SOURCES",
    "MessageSendRequest",
    "MessageStatusUpdateRequest",
    "MessageResponse",
    "MessageListResponse",
    "MessageReceipt",
    "MessageReceiptResponse",
    "CHANNEL_TYPES",
    "ChannelConfigResponse",
    "ChannelConfigCreate",
    "ChannelConfigUpdate",
    "ChannelDeliverRequest",
    "ChannelDeliverResponse",
    "ChannelPollRequest",
    "ChannelPollResponse",
    "ChannelMessageBase",
    "ChannelMessageCreate",
    "ChannelMessageResponse",
    "ChannelMessageListResponse",
]
