"""Realtime conversation-management service — P5MSG-04.

Read-side queries that power the realtime conversation view: the *active*
conversation list with a last-message preview and a per-conversation unread
count. These are the "会话管理: 活跃会话列表、最后消息预览、未读数"
requirement of P5MSG-04 — the live list a UI renders and keeps in sync via
the ``/api/v1/realtime`` stream.

Conventions (platform-wide):
* Business logic lives in the service, not the router (API -> Service ->
  Data layer).
* ``conversation`` is the Phase-2 entity; the unread/preview data comes from
  the P5MSG-01/02 ``ChannelMessage`` (table ``messages``) delivery log, so
  the active list reflects real channel activity, not just AI transcripts.
* Previews are bounded text with no secrets; message *text* is the only PII
  surfaced and it is the preview a user is entitled to see.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.messages import ChannelMessage

logger = logging.getLogger(__name__)

# How much of the message payload to show in the list preview.
PREVIEW_MAX_LEN = 120


@dataclass
class ActiveConversationRow:
    """One row of the active conversation list, ready for the API layer."""

    conversation_id: UUID
    customer_id: UUID
    channel: str
    subject: Optional[str]
    status: str
    last_message_at: Optional[object]
    last_message_preview: Optional[str]
    unread_count: int
    message_count: int

    def to_dict(self) -> dict:
        return {
            "conversation_id": str(self.conversation_id),
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "channel": self.channel,
            "subject": self.subject,
            "status": self.status,
            "last_message_at": (
                self.last_message_at.isoformat()
                if getattr(self.last_message_at, "isoformat", None)
                else None
            ),
            "last_message_preview": self.last_message_preview,
            "unread_count": self.unread_count,
            "message_count": self.message_count,
        }


class RealtimeConversationService:
    """Read-side conversation-list / preview / unread queries (P5MSG-04)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active_conversations(
        self,
        customer_id: Optional[UUID] = None,
        channel: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        redact_preview: bool = False,
    ) -> List[ActiveConversationRow]:
        """Active (status='active', not deleted) conversations, newest activity
        first, each carrying a last-message preview and unread count.

        ``channel``/``customer_id`` filter the result. Unread = inbound
        channel messages (``direction='in'``) not yet marked ``read``; this
        mirrors the P5MSG-02 delivery state machine where ``read`` is the
        terminal acknowledged state.

        P5MSG-FIX-2 (P1-3): ``redact_preview=True`` strips PII-flavoured
        tokens (phone numbers, emails) from the bounded preview text before
        it is returned — the opt-in desensitization for the realtime list
        view. The raw message content is never mutated; only the rendered
        preview string is scrubbed.
        """
        rows = (
            await self.db.execute(
                select(
                    Conversation.id,
                    Conversation.customer_id,
                    Conversation.channel,
                    Conversation.subject,
                    Conversation.status,
                    Conversation.message_count,
                    Conversation.last_message_at,
                )
                .where(
                    and_(
                        Conversation.is_deleted == False,  # noqa: E712
                        Conversation.status == "active",
                    )
                )
                .order_by(func.coalesce(Conversation.last_message_at, Conversation.created_at).desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()

        results: List[ActiveConversationRow] = []
        for r in rows:
            conv_id = r[0]
            # Preview: text of the latest non-deleted channel message.
            # P1-3: optionally scrub PII tokens from the rendered preview.
            preview = await self._latest_preview(conv_id, redact=redact_preview)
            # Unread count.
            unread = await self._unread_count(conv_id)
            results.append(
                ActiveConversationRow(
                    conversation_id=conv_id,
                    customer_id=r[1],
                    channel=r[2],
                    subject=r[3],
                    status=r[4],
                    last_message_at=r[6],
                    last_message_preview=preview,
                    unread_count=unread,
                    message_count=r[5],
                )
            )

        if customer_id is not None or channel is not None:
            results = [
                row
                for row in results
                if (customer_id is None or row.customer_id == customer_id)
                and (channel is None or row.channel == channel)
            ]
        return results

    async def _latest_preview(self, conversation_id: UUID, redact: bool = False) -> Optional[str]:
        """Bounded text preview of the most recent channel message.

        P5MSG-FLAKY: "latest" is defined by ``created_at`` — the *true* most-recent
        message. Distinct inserts normally carry distinct microsecond timestamps,
        so ``created_at desc`` is the decisive key. The fallback chain
        ``updated_at desc, id desc`` only matters when two rows tie on
        ``created_at`` (an edge case, or a test that seeds many rows in a tight
        loop). ``id`` is a random UUID4, so relying on it alone for the "latest"
        row is non-deterministic across runs; keeping it as a *last-resort*
        total-order tie-break makes the ordering reproducible for a given data
        set without pretending it encodes message recency.
        """
        row = (
            await self.db.execute(
                select(ChannelMessage.content)
                .where(
                    and_(
                        ChannelMessage.conversation_id == conversation_id,
                        ChannelMessage.is_deleted == False,  # noqa: E712
                    )
                )
                .order_by(
                    ChannelMessage.created_at.desc(),
                    ChannelMessage.updated_at.desc(),
                    ChannelMessage.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return self._preview_from_content(row, redact=redact)

    @staticmethod
    def _preview_from_content(content: Optional[dict], redact: bool = False) -> Optional[str]:
        """Render a bounded text preview from a JSONB message payload.

        Prefers the platform's ``text`` field (the ``{"text": ...}`` shape
        P5MSG-02's ``MessageSendRequest`` documents), then ``content``, then
        a truncated JSON dump. Never includes secrets — the payload is the
        user's own message.

        P5MSG-FIX-2 (P1-3): with ``redact=True`` PII-flavoured tokens
        (phone numbers, emails) are scrubbed from the rendered preview
        before the length cap is applied. The DB row is never mutated —
        only the preview string returned to callers changes.
        """
        if not content:
            return None
        text = content.get("text") or content.get("content") or content.get("preview")
        if text is None:
            import json

            text = json.dumps(content, ensure_ascii=False)
        text = str(text)
        if redact:
            text = RealtimeConversationService._scrub_pii(text)
        return text if len(text) <= PREVIEW_MAX_LEN else text[: PREVIEW_MAX_LEN - 1] + "…"

    # PII-flavoured token patterns scrubbed from previews (P1-3). Email
    # addresses and CN phone numbers are the PII the P5MSG-11 review called
    # out for the channel-message JSONB payload (wechat/douyin sessions).
    _PII_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    _PII_CN_PHONE_RE = re.compile(
        r"(?<!\d)(?:\+?86-?|1\d{2}-?)?1\d{2}[- ]?\d{4}[- ]?\d{4}(?!\d)"
    )

    @staticmethod
    def _scrub_pii(text: str) -> str:
        """Scrub PII-flavoured tokens from preview text (P1-3)."""
        scrubbed = RealtimeConversationService._PII_EMAIL_RE.sub("[EMAIL]", text)
        scrubbed = RealtimeConversationService._PII_CN_PHONE_RE.sub("[PHONE]", scrubbed)
        return scrubbed

    async def _unread_count(self, conversation_id: UUID) -> int:
        count = (
            await self.db.execute(
                select(func.count())
                .select_from(ChannelMessage)
                .where(
                    and_(
                        ChannelMessage.conversation_id == conversation_id,
                        ChannelMessage.is_deleted == False,  # noqa: E712
                        ChannelMessage.direction == "in",
                        ChannelMessage.status != "read",
                    )
                )
            )
        ).scalar_one()
        return int(count or 0)

    async def unread_total(self, customer_id: Optional[UUID] = None) -> int:
        """Aggregate unread count (optionally scoped to a customer's conversations).

        Unread = inbound channel messages not yet marked ``read``. When
        ``customer_id`` is given the count is restricted to that customer's
        conversations (join ``conversation``); otherwise it is platform-wide.
        """
        from sqlalchemy import join

        q = (
            select(func.count())
            .select_from(ChannelMessage)
            .where(
                and_(
                    ChannelMessage.is_deleted == False,  # noqa: E712
                    ChannelMessage.direction == "in",
                    ChannelMessage.status != "read",
                )
            )
        )
        if customer_id is not None:
            q = (
                select(func.count())
                .select_from(join(Conversation, ChannelMessage, ChannelMessage.conversation_id == Conversation.id))
                .where(
                    and_(
                        ChannelMessage.is_deleted == False,  # noqa: E712
                        ChannelMessage.direction == "in",
                        ChannelMessage.status != "read",
                        Conversation.customer_id == customer_id,
                    )
                )
            )
        total = (await self.db.execute(q)).scalar_one()
        return int(total or 0)
