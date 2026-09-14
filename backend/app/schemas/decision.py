"""Decision Engine schemas for Phase 2 - AI Decision & Persona Generation"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


# ========== Decision Request / Response ==========

class DecisionRequest(BaseModel):
    """Request to make a decision"""
    conversation_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    persona_id: Optional[UUID] = None
    message: str = Field(..., min_length=1, max_length=5000, description="User message")
    intent_type: Optional[str] = Field(None, description="Pre-classified intent type")
    intent_name: Optional[str] = Field(None, description="Pre-classified intent name")
    intent_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    entities: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    use_llm: bool = Field(default=False, description="Force LLM path (if available)")


class DecisionExplanation(BaseModel):
    """Explanation of why a decision was made (explainability)"""
    strategy: str = Field(..., description="rule_based | llm | fallback")
    intent_type: str
    intent_confidence: float
    matched_rule: Optional[str] = None
    reasoning_steps: List[str] = Field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: Optional[str] = None


class DecisionResponse(BaseModel):
    """Response from the decision engine"""
    success: bool
    action_type: str
    response_text: str
    strategy: str
    explanation: DecisionExplanation
    quality_score: Optional[float] = Field(None, ge=0.0, le=5.0)
    quality_passed: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
    processing_time_ms: float = 0.0
    error: Optional[str] = None


# ========== Persona Style ==========

class PersonaStyleRequest(BaseModel):
    """Request to generate persona conversation style"""
    persona_id: Optional[UUID] = None
    persona_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    personality: Dict[str, Any] = Field(default_factory=dict)


class PersonaStyleResponse(BaseModel):
    """Generated persona conversation style"""
    persona_name: str
    system_prompt: str
    tone_keywords: List[str] = Field(default_factory=list)
    style_directives: List[str] = Field(default_factory=list)
    example_responses: List[str] = Field(default_factory=list)


# ========== Context Building ==========

class ContextBuildRequest(BaseModel):
    """Request to build conversation context"""
    conversation_id: UUID
    customer_id: Optional[UUID] = None
    current_message: str = Field(..., min_length=1)
    recent_messages: List[Dict[str, Any]] = Field(default_factory=list)
    relevant_memories: List[Dict[str, Any]] = Field(default_factory=list)
    conversation_summary: Optional[str] = None
    system_instruction: Optional[str] = Field(
        None, description="Persona system prompt / style directives (from PersonaStyleGenerator)"
    )
    persona_name: Optional[str] = Field(None, description="Persona name to anchor the context")
    max_tokens: int = Field(default=4000, ge=500, le=16000)


class ContextBuildResponse(BaseModel):
    """Built conversation context"""
    conversation_id: UUID
    system_context: str
    user_context: str
    recent_messages: List[Dict[str, Any]]
    memories_included: int
    summary_included: bool
    total_tokens: int
    token_budget: int
    truncated: bool


# ========== Response Validation ==========

class ValidationRequest(BaseModel):
    """Request to validate a response"""
    response_text: str = Field(..., min_length=1)
    user_message: str = Field(..., min_length=1)
    intent_type: str
    persona_name: Optional[str] = None
    personality: Dict[str, Any] = Field(default_factory=dict)


class ValidationDimension(BaseModel):
    """Score for a single validation dimension"""
    name: str
    score: float = Field(..., ge=0.0, le=1.0)
    reason: str


class ValidationResponse(BaseModel):
    """Response validation result"""
    overall_score: float = Field(..., ge=0.0, le=5.0)
    passed: bool
    threshold: float = 4.0
    dimensions: List[ValidationDimension] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)


# ========== Fallback ==========

class FallbackDecisionResponse(BaseModel):
    """Fallback decision response when LLM is unavailable"""
    success: bool
    action_type: str
    response_text: str
    strategy: str = "fallback"
    reason: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
