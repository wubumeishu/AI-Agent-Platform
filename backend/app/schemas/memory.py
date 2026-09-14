"""Memory Schemas for Phase 2 - Memory System"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field


# ========== Memory Schemas ==========

class MemoryBase(BaseModel):
    """Base Memory schema"""
    memory_type: str = Field(..., pattern="^(preference|fact|history|insight)$")
    category: str = Field(default="general", pattern="^(general|product|service|personal)$")
    content: str = Field(..., min_length=1, max_length=5000)
    source: str = Field(default="conversation", pattern="^(conversation|manual|ai_generated)$")
    importance: int = Field(default=5, ge=1, le=10)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    metadata_: Optional[dict] = Field(None, alias="metadata")


class MemoryCreate(MemoryBase):
    """Schema for creating a new memory"""
    customer_id: UUID = Field(..., description="Customer ID")
    pass


class MemoryUpdate(BaseModel):
    """Schema for updating a memory"""
    memory_type: Optional[str] = Field(None, pattern="^(preference|fact|history|insight)$")
    category: Optional[str] = Field(None, pattern="^(general|product|service|personal)$")
    content: Optional[str] = Field(None, min_length=1, max_length=5000)
    importance: Optional[int] = Field(None, ge=1, le=10)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    tags: Optional[List[str]] = None
    metadata_: Optional[dict] = Field(None, alias="metadata")


class MemoryResponse(MemoryBase):
    """Schema for memory response"""
    id: UUID
    customer_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemoryListResponse(BaseModel):
    """Paginated memory list response"""
    items: List[MemoryResponse]
    total: int
    page: int
    page_size: int


# ========== Memory Fragment Schemas ==========

class MemoryFragmentCreate(BaseModel):
    """Schema for creating a memory fragment"""
    memory_id: UUID
    content: str = Field(..., min_length=1)
    fragment_order: int = Field(default=0, ge=0)
    embedding: Optional[List[float]] = None


class MemoryFragmentResponse(BaseModel):
    """Schema for memory fragment response"""
    id: UUID
    memory_id: UUID
    fragment_order: int
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ========== Conversation Summary Schemas ==========

class ConversationSummaryCreate(BaseModel):
    """Schema for creating a conversation summary"""
    conversation_id: UUID
    summary_type: str = Field(default="brief", pattern="^(brief|detailed|executive)$")
    content: str = Field(..., min_length=1)
    key_points: List[str] = Field(default_factory=list)
    sentiment: Optional[str] = Field(None, pattern="^(positive|neutral|negative)$")
    action_items: List[str] = Field(default_factory=list)


class ConversationSummaryResponse(BaseModel):
    """Schema for conversation summary response"""
    id: UUID
    conversation_id: UUID
    summary_type: str
    content: str
    key_points: List[str]
    sentiment: Optional[str] = None
    action_items: List[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationSummaryListResponse(BaseModel):
    """Paginated conversation summary list response"""
    items: List[ConversationSummaryResponse]
    total: int
    page: int
    page_size: int


# ========== Context Window Schemas ==========

class ContextWindowResponse(BaseModel):
    """Schema for context window response"""
    id: UUID
    conversation_id: UUID
    current_tokens: int
    max_tokens: int
    compressed_count: int
    last_compressed_at: Optional[datetime] = None
    usage_percentage: float = Field(..., ge=0.0, le=100.0)
    needs_compression: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ========== Memory Retrieval Schemas ==========

class MemorySearchRequest(BaseModel):
    """Request schema for memory search"""
    customer_id: UUID
    query: str = Field(..., min_length=1, max_length=500)
    memory_type: Optional[str] = Field(None, pattern="^(preference|fact|history|insight)$")
    category: Optional[str] = Field(None, pattern="^(general|product|service|personal)$")
    relevance_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    limit: int = Field(default=10, ge=1, le=50)


class MemorySearchResponse(BaseModel):
    """Response schema for memory search"""
    query: str
    results: List[Dict[str, Any]] = Field(default_factory=list)
    total: int
    search_time_ms: float = 0.0


class MemoryInjectionRequest(BaseModel):
    """Request schema for memory injection into context"""
    conversation_id: UUID
    customer_id: UUID
    recent_messages: List[Dict[str, Any]] = Field(default_factory=list)
    max_memory_count: int = Field(default=5, ge=1, le=20)


class MemoryInjectionResponse(BaseModel):
    """Response schema for memory injection"""
    conversation_id: UUID
    injected_memories: List[Dict[str, Any]] = Field(default_factory=list)
    injection_count: int
    context_tokens_added: int = 0
