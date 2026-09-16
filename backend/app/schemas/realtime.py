"""Pydantic schemas for the P5MSG-04 realtime + conversation-management API.

Covers:
* the REST conversation-management read endpoints (active list / preview /
  unread / totals) that P5MSG-04 adds to the existing conversation module;
* request bodies for the realtime channel (resync, mark-read, subscribe).

The realtime *stream* itself is SSE (``/api/v1/realtime``) and its frame
shape is defined by :mod:`app.services.realtime_hub` (``RealtimeEvent``),
not a Pydantic model.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class RealtimeConversationItem(BaseModel):
    """One active conversation in the realtime list view."""

    conversation_id: UUID
    customer_id: Optional[UUID] = None
    channel: str
    subject: Optional[str] = None
    status: str
    last_message_at: Optional[datetime] = None
    last_message_preview: Optional[str] = Field(None, description="Bounded text preview of the latest message")
    unread_count: int = 0
    message_count: int = 0


class RealtimeConversationListResponse(BaseModel):
    """Paginated active-conversation list (GET /api/v1/realtime/conversations)."""

    items: List[RealtimeConversationItem]
    total_unread: int = 0
    page: int
    page_size: int


class RealtimeUnreadSummary(BaseModel):
    """Unread aggregate (GET /api/v1/realtime/unread)."""

    total_unread: int
    by_conversation: List[RealtimeConversationItem] = Field(default_factory=list)


class RealtimeResyncRequest(BaseModel):
    """Client -> realtime channel: ask for the tail since a cursor."""

    since: int = Field(0, ge=0, description="Last seq processed; 0 = from the oldest retained")
    conversation_id: Optional[UUID] = Field(None, description="Scope the replay to one conversation")
    limit: int = Field(200, ge=1, le=1000, description="Max events to return")


class RealtimeReadRequest(BaseModel):
    """Mark a conversation read (POST /api/v1/realtime/read) — drives
    P5MSG-02's ``read`` receipt state machine per inbound message and emits
    a ``channel_message.read`` event so the unread badge clears live."""

    conversation_id: UUID
    # Optional explicit message ids; when omitted, all unread inbound
    # messages in the conversation are marked read.
    message_ids: Optional[List[UUID]] = None


class RealtimePublishRequest(BaseModel):
    """Ad-hoc event publish (POST /api/v1/realtime/publish) — used by the
    P5MSG-02/03 producers that prefer the API over the bus. ``kind`` is one
    of ``REALTIME_EVENT_KINDS``; payload carries ids/status only.

    P5MSG-FIX-1 (P0-3): ``payload`` is no longer an unvalidated ``dict``.
    A model validator runs it through :func:`app.security.validate_publish_payload`
    so the seam cannot be used to pollute live SSE frames or the persistent
    replay log with unbounded / PII / secret-bearing payloads.
    """

    kind: str = Field(..., description="channel_message.created|channel_message.status|channel_message.read|conversation.updated")
    conversation_id: Optional[UUID] = None
    payload: Dict[str, Any] = Field(default_factory=dict, description="ids/status/channel — no message text or secrets")
    dedup_id: Optional[str] = Field(None, max_length=128, description="Idempotency key; duplicate emits are dropped")

    @model_validator(mode="after")
    def _enforce_payload_schema(self) -> "RealtimePublishRequest":
        from app.security import validate_publish_payload

        validate_publish_payload(self.payload)
        return self
