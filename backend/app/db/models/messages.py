"""Channel Message model — P5MSG-01 (Roadmap Phase 2 Message/Conversation increment).

This is the *channel message dispatch / delivery record* — deliberately distinct
from the Phase-2 AI chat-transcript ``Message`` (singular, table ``message``,
role + text). See the migration ``022_messages_channel`` for the full
justification and column reference.

ORM convention notes:
  * ``content`` is JSONB (structured payload) — contrast with ``message.content``
    which is Text.
  * ``conversation_id`` is a hard FK; ``account_id`` / ``agent_id`` are
    nullable SET-NULL so delivery history survives the deletion of the
    producing account/agent.
  * The status / direction / channel value domains are enforced here (enums)
    and in the Pydantic schemas, not by DB CHECK constraints (matches the
    platform convention used by ``conversation``).
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Boolean, DateTime, JSON, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship

from .base import Base


class MessageDirection(str, Enum):
    """Inbound (received) vs outbound (sent) channel message."""
    IN = "in"
    OUT = "out"


class MessageStatus(str, Enum):
    """Delivery lifecycle. P5MSG-02 owns the state machine (transitions)."""
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    READ = "read"


# Canonical value domains (kept as module constants so routers/services/tests
# share one source of truth without importing the Enum twice).
MESSAGE_DIRECTIONS = [d.value for d in MessageDirection]
MESSAGE_STATUSES = [s.value for s in MessageStatus]


class ChannelMessage(Base):
    """Channel message dispatch / delivery record (table: ``messages``)."""
    __tablename__ = "messages"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    # Hard FK: a channel message MUST attach to a real conversation.
    conversation_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable logical identity; ON DELETE SET NULL preserves history.
    account_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("account.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("agent.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel = Column(String(50), nullable=False, default="web")
    direction = Column(String(10), nullable=False, default=MessageDirection.OUT.value)
    status = Column(String(20), nullable=False, default=MessageStatus.QUEUED.value)
    # Structured payload (text, media refs, platform-specific fields).
    content = Column(JSONB, nullable=False, default=dict, server_default="{}")
    # The provider/platform's own message id (e.g. wechat msg id).
    provider_message_id = Column(String(200), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    # Failure details (provider error code/message) when status == failed.
    error = Column(JSONB, nullable=True)
    # P5MSG-02 delivery/read receipts.
    #
    # ADR-017 (dual-write SoT convergence): the append-only ``receipts``
    # JSONB is **DEPRECATED** — it was a duplicate of the execution_log
    # audit trail (execution_type='message_status'), which is now the single
    # source of truth. New transitions no longer write to this column; it is
    # kept read-only for legacy rows only. ``get_receipt`` projects the trail
    # from the ExecutionLog instead. A follow-up tech-debt migration will
    # backfill legacy rows from the log and drop the column.
    receipts = Column(JSONB, nullable=True)
    # Lightweight denormalized "when was it last acknowledged" scalar
    # (kept for cheap API reads; the authoritative trail is execution_log).
    last_receipt_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        default=datetime.now(timezone.utc),
                        onupdate=datetime.now(timezone.utc))
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    conversation = relationship("Conversation", back_populates="channel_messages")

    __table_args__ = (
        Index("idx_messages_conversation", "conversation_id"),
        Index("idx_messages_conversation_status", "conversation_id", "status"),
        Index("idx_messages_channel", "channel"),
        Index("idx_messages_created", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChannelMessage(id={self.id}, conversation={self.conversation_id}, "
            f"channel={self.channel}, direction={self.direction}, status={self.status})>"
        )
