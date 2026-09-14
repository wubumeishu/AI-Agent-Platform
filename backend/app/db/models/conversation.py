"""Conversation Model"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from .base import Base


class Conversation(Base):
    """Conversation (对话) 实体"""
    __tablename__ = "conversation"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    customer_id = Column(PGUUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(50), nullable=False, default="web")  # web, email, phone, wechat, etc.
    subject = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="active")  # active, closed, archived
    summary = Column(Text, nullable=True)
    sentiment = Column(String(20), nullable=True)  # positive, neutral, negative
    duration_seconds = Column(Integer, nullable=True)  # 对话时长（秒）
    message_count = Column(Integer, nullable=False, default=0)  # 消息总数（用于快速查询）
    last_message_at = Column(DateTime(timezone=True), nullable=True)  # 最后一条消息时间
    tags = Column(JSON, nullable=False, default=list)
    metadata_ = Column(JSON, nullable=True, default=dict)  # 元数据
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    is_deleted = Column(Boolean, nullable=False, default=False)

    # 关系
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", lazy="selectin")
    # Channel message dispatch / delivery records (table: messages) — P5MSG-01.
    # Distinct from the AI chat-transcript ``messages`` above. Cascade to the
    # conversation: deleting a conversation removes its channel delivery log.
    channel_messages = relationship(
        "ChannelMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="ChannelMessage.conversation_id",
    )
    intents = relationship("Intent", back_populates="conversation", cascade="all, delete-orphan", lazy="selectin")
    decision_logs = relationship(
        "DecisionLog",
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="DecisionLog.conversation_id",
    )

    __table_args__ = (
        Index('idx_conversation_customer', 'customer_id'),
        Index('idx_conversation_status', 'status'),
        Index('idx_conversation_created', 'created_at'),
        Index('idx_conversation_last_message', 'last_message_at'),
    )

    class Config:
        arbitrary_types_allowed = True


class Message(Base):
    """Message (消息) 实体"""
    __tablename__ = "message"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(PGUUID(as_uuid=True), ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = Column(PGUUID(as_uuid=True), ForeignKey("message.id", ondelete="SET NULL"), nullable=True, index=True)  # 引用父消息
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    edit_count = Column(Integer, nullable=False, default=0)  # 编辑次数（最多允许3次）
    metadata_ = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    is_deleted = Column(Boolean, nullable=False, default=False)

    # 关系
    conversation = relationship("Conversation", back_populates="messages")
    parent = relationship("Message", remote_side=[id], backref="replies")

    __table_args__ = (
        Index('idx_message_conversation', 'conversation_id'),
        Index('idx_message_created', 'created_at'),
        Index('idx_message_role', 'role'),
        Index('idx_message_parent', 'parent_id'),
    )

    class Config:
        arbitrary_types_allowed = True
