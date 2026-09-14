"""Schemas for Phase 5 AI Content Generation + Nurture Automation.

These power:
- AI content generation (personalized, customer-segment / lifecycle-stage aware)
- Quality + relevance evaluation of generated content
- Content injection into a NurturePlan step
- Generation-history query
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field


# ========== Quality evaluation ==========

class QualityEvaluation(BaseModel):
    """Deterministic quality + relevance score for a generated content item."""
    score: float = Field(..., ge=0.0, le=5.0)
    passed: bool
    threshold: float = 4.0
    # Per-dimension scores, each 0.0-1.0 (relevance, completeness, personalization, safety, consistency)
    dimensions: Dict[str, float] = Field(default_factory=dict)
    issues: List[str] = Field(default_factory=list)


class ContentEvaluationRequest(BaseModel):
    """Request to evaluate a piece of content against an intended context."""
    content: str = Field(..., min_length=1)
    title: Optional[str] = None
    # Optional context used to judge relevance/personalization:
    objective: Optional[str] = None          # e.g. "welcome", "reactivation"
    segment_name: Optional[str] = None
    stage_name: Optional[str] = None
    expected_tags: List[str] = Field(default_factory=list)
    persona_name: Optional[str] = None
    max_length: int = Field(default=2000, ge=1)


# ========== Content generation ==========

class ContentGenerationRequest(BaseModel):
    """Describe the customer context to personalize content against."""
    account_id: UUID
    content_type: str = Field(default="text", pattern="^(text|image|video|pdf|html)$")
    objective: Optional[str] = None            # welcome | reactivation | nurture | cross_sell | support
    channel: Optional[str] = None             # wechat | wechat_work | email | sms | ...
    persona_name: Optional[str] = None
    segment_id: Optional[UUID] = None
    segment_name: Optional[str] = None
    stage_code: Optional[str] = None          # lifecycle stage code
    stage_name: Optional[str] = None
    customer_tags: List[str] = Field(default_factory=list)
    customer_name: Optional[str] = None
    tone: Optional[str] = None               # warm | professional | playful
    length: str = Field(default="medium", pattern="^(short|medium|long)$")
    language: str = Field(default="zh")
    include_cta: bool = True
    # Where the result goes:
    save_to_library: bool = False
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class GeneratedContent(BaseModel):
    """A single AI-generated (or template-generated) content result."""
    generation_id: Optional[UUID] = None
    content_item_id: Optional[UUID] = None     # set when persisted to the library
    title: str
    body: str
    summary: Optional[str] = None
    content_type: str
    tags: List[str] = Field(default_factory=list)
    category: Optional[str] = None
    quality: QualityEvaluation
    strategy: str = Field(default="template")  # llm | template
    fallback_used: bool = False
    fallback_reason: Optional[str] = None


# ========== Nurture plan content injection ==========

class ContentInjectionRequest(BaseModel):
    """Generate (or reuse) content and attach it to a NurturePlan step."""
    plan_id: UUID
    account_id: UUID
    # Step placement (defaults to append / given step_order)
    step_order: Optional[int] = None
    trigger_type: str = Field(default="time_based", pattern="^(time_based|event_based|behavior_based|manual)$")
    delay_hours: int = Field(default=0, ge=0)
    # Reuse an existing library item, or generate a new one via `generate`:
    content_id: Optional[UUID] = None
    generate: Optional[ContentGenerationRequest] = None
    # Optional extra config stored on the step:
    config: Dict[str, Any] = Field(default_factory=dict)


class ContentInjectionResponse(BaseModel):
    """Result of injecting content into a nurture plan step."""
    generation_id: Optional[UUID] = None
    content_item_id: Optional[UUID] = None
    step_id: Optional[UUID] = None
    step_order: int
    content: GeneratedContent
    created_step: bool


# ========== Generation history ==========

class GenerationHistoryItem(BaseModel):
    """One row of the content-generation audit log."""
    id: UUID
    account_id: UUID
    source: str
    content_type: str
    strategy: str
    fallback_used: bool
    fallback_reason: Optional[str]
    segment_id: Optional[UUID]
    stage_code: Optional[str]
    content_id: Optional[UUID]
    nurture_plan_id: Optional[UUID]
    plan_step_id: Optional[UUID]
    quality_score: Optional[float]
    quality_passed: Optional[bool]
    input_snapshot: Dict[str, Any] = Field(default_factory=dict)
    output_snapshot: Dict[str, Any] = Field(default_factory=dict)
    processing_time_ms: Optional[float]
    created_at: Optional[datetime]


class GenerationHistoryResponse(BaseModel):
    items: List[GenerationHistoryItem]
    total: int
    limit: int
    offset: int
