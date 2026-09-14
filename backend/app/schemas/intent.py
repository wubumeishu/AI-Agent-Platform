"""Intent schemas for Phase 2 - Intent Recognition System"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field


# ========== Request Schemas ==========

class IntentClassificationRequest(BaseModel):
    """Request schema for intent classification"""
    conversation_id: Optional[UUID] = None
    message: str = Field(..., min_length=1, max_length=2000)
    context: Dict[str, Any] = Field(default_factory=dict)
    previous_intents: List[Dict[str, Any]] = Field(default_factory=list)


class IntentEntityExtractRequest(BaseModel):
    """Request schema for entity extraction"""
    text: str = Field(..., min_length=1)
    intent_type: Optional[str] = None


# ========== Response Schemas ==========

class IntentResult(BaseModel):
    """Single intent classification result"""
    intent_type: str
    intent_name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    entities: Dict[str, Any] = Field(default_factory=dict)
    explanation: Optional[str] = None


class IntentClassificationResponse(BaseModel):
    """Response schema for intent classification"""
    success: bool
    intent: Optional[IntentResult] = None
    alternatives: List[IntentResult] = Field(default_factory=list)
    confidence_threshold: float = 0.7
    processing_time_ms: float = 0.0
    message: Optional[str] = None


class IntentHistoryItem(BaseModel):
    """Single intent history item"""
    id: UUID
    conversation_id: UUID
    intent_type: str
    intent_name: str
    confidence: float
    raw_input: str
    extracted_entities: Dict[str, Any]
    matched_action: Optional[str] = None
    created_at: datetime


class IntentHistoryResponse(BaseModel):
    """Response schema for intent history"""
    conversation_id: UUID
    intents: List[IntentHistoryItem]
    total: int
    summary: Dict[str, Any] = Field(default_factory=dict)


class IntentActionRequest(BaseModel):
    """Request schema for intent-to-action mapping"""
    intent_type: str
    intent_name: str
    entities: Dict[str, Any]
    context: Dict[str, Any]


class IntentActionResponse(BaseModel):
    """Response schema for intent action mapping"""
    success: bool
    action_type: Optional[str] = None
    action_target: Optional[str] = None
    action_params: Dict[str, Any] = Field(default_factory=dict)
    fallback_message: Optional[str] = None


class IntentStatistics(BaseModel):
    """Intent statistics for analytics"""
    total_classifications: int = 0
    avg_confidence: float = 0.0
    top_intents: List[Dict[str, Any]] = Field(default_factory=list)
    intent_distribution: Dict[str, int] = Field(default_factory=dict)
    confidence_distribution: Dict[str, int] = Field(default_factory=dict)


# ========== Validation Schemas ==========

class IntentSchemaUpdate(BaseModel):
    """Schema for updating intent definitions"""
    intent_type: Optional[str] = None
    intent_name: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[List[str]] = None
    category: Optional[str] = None
    priority: Optional[int] = Field(None, ge=1, le=10)


class IntentSchemaCreate(IntentSchemaUpdate):
    """Schema for creating a new intent type"""
    intent_type: str = Field(..., min_length=3, max_length=50)
    intent_name: str = Field(..., min_length=1, max_length=100)
    description: str
    keywords: List[str] = Field(default_factory=list)
    category: str = "default"
    priority: int = Field(default=5, ge=1, le=10)


class IntentSchemaResponse(IntentSchemaCreate):
    """Response schema for intent schema"""
    id: UUID
    created_at: datetime
    updated_at: datetime
    usage_count: int = 0
