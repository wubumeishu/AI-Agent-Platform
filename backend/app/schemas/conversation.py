"""Pydantic schemas for Conversation module"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.messages import MESSAGE_CHANNELS

#: Channel value domain for the conversation layer.
#:
#: Full set of the message-layer ``MESSAGE_CHANNELS`` domain
#: (``web|wechat|wechat_work|email|sms|whatsapp|line|douyin|xiaohongshu|other``),
#: plus legacy ``phone`` / ``dingtalk`` values that already exist in seeded
#: conversation rows. Any value in this domain is valid both on create
#: (``ConversationCreate``) and on serialization (``ConversationResponse``);
#: everything else is rejected so the response layer cannot 500 on a row
#: written by another module (P5MSG-D2).
CONVERSATION_CHANNELS = sorted(set(MESSAGE_CHANNELS) | {"phone", "dingtalk"})
_CHANNEL_PATTERN = "^(" + "|".join(CONVERSATION_CHANNELS) + ")$"


class ConversationBase(BaseModel):
    """Base Conversation schema"""
    customer_id: UUID = Field(..., description="Customer ID")
    channel: str = Field(default="web", pattern=_CHANNEL_PATTERN, description=f"Communication channel; one of {CONVERSATION_CHANNELS}")
    subject: Optional[str] = Field(None, max_length=200, description="Conversation subject")
    status: str = Field(default="active", pattern="^(active|closed|archived)$", description="Conversation status")
    summary: Optional[str] = Field(None, description="Conversation summary")
    sentiment: Optional[str] = Field(None, pattern="^(positive|neutral|negative)$", description="Conversation sentiment")
    tags: List[str] = Field(default_factory=list, description="Conversation tags")
    metadata_: Optional[dict] = Field(None, alias="metadata", description="Additional metadata")


class ConversationCreate(ConversationBase):
    """Schema for creating a new conversation"""
    pass


class ConversationUpdate(BaseModel):
    """Schema for updating a conversation"""
    subject: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = Field(None, pattern="^(active|closed|archived)$")
    summary: Optional[str] = None
    sentiment: Optional[str] = Field(None, pattern="^(positive|neutral|negative)$")
    duration_seconds: Optional[int] = Field(None, ge=0)
    tags: Optional[List[str]] = None
    metadata_: Optional[dict] = Field(None, alias="metadata")


class MessageBase(BaseModel):
    """Base Message schema"""
    role: str = Field(..., pattern="^(user|assistant|system)$", description="Message role")
    content: str = Field(..., min_length=1, max_length=10000, description="Message content (max 10000 chars)")
    parent_id: Optional[UUID] = Field(None, description="Parent message ID for threading")
    metadata_: Optional[dict] = Field(None, alias="metadata", description="Additional metadata")

    @field_validator('content')
    @classmethod
    def sanitize_content(cls, v: str) -> str:
        """XSS防护：移除HTML标签"""
        import re
        # 移除所有HTML标签
        sanitized = re.sub(r'<[^>]+>', '', v)
        # 移除script标签和内容
        sanitized = re.sub(r'<script.*?>.*?</script>', '', sanitized, flags=re.IGNORECASE | re.DOTALL)
        # 移除javascript:协议
        sanitized = re.sub(r'javascript:', '', sanitized, flags=re.IGNORECASE)
        return sanitized.strip()


class MessageCreate(MessageBase):
    """Schema for creating a new message"""
    conversation_id: UUID = Field(..., description="Conversation ID")


class MessageUpdate(BaseModel):
    """Schema for updating a message"""
    content: Optional[str] = Field(None, min_length=1, max_length=10000)
    metadata_: Optional[dict] = Field(None, alias="metadata")


class MessageResponse(MessageBase):
    """Schema for message response"""
    id: UUID
    conversation_id: UUID
    edit_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ConversationResponse(ConversationBase):
    """Schema for conversation response"""
    id: UUID
    duration_seconds: Optional[int] = None
    message_count: int = 0
    last_message_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    """Paginated conversation list response"""
    items: List[ConversationResponse]
    total: int
    page: int
    page_size: int


class MessageListResponse(BaseModel):
    """Paginated message list response"""
    items: List[MessageResponse]
    total: int
    page: int
    page_size: int


class ConversationStats(BaseModel):
    """Conversation statistics"""
    conversation_id: UUID
    total_messages: int
    user_messages: int
    assistant_messages: int
    system_messages: int
    first_message_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    avg_response_time_seconds: Optional[float] = None


class RedoResponse(BaseModel):
    """Redo operation response"""
    original_id: UUID
    new_id: UUID
    original_role: str
    new_content: str
    status: str
    created_at: datetime
