"""Decision Engine Router - AI decision, persona style, context, validation, fallback."""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.decision import (
    DecisionRequest,
    DecisionResponse,
    PersonaStyleRequest,
    PersonaStyleResponse,
    ContextBuildRequest,
    ContextBuildResponse,
    ValidationRequest,
    ValidationResponse,
    FallbackDecisionResponse,
)
from app.services.decision_service import DecisionService


# BUG-1 (t_acffd4d0): this AI-tier router self-carries its full
# `/api/v1/decision` prefix and is mounted BARE in main.py (no extra
# prefix), so the live URL is the single-prefix `/api/v1/decision/...`.
# Do NOT strip the `/api/v1` to make this a bare `"/decision"`: the pinned
# route-path assertions in tests/test_decision_api.py require router.routes
# to start with `/api/v1/decision`, and stripping would re-introduce the
# double-prefix bug if main.py ever mounts these again with a prefix.
router = APIRouter(prefix="/api/v1/decision", tags=["Decision Engine"])


def get_decision_service(db: AsyncSession = Depends(get_db)) -> DecisionService:
    """Dependency: DecisionService wired to the request's DB session.

    No LLM provider is wired by default → the engine runs in safe
    rule/fallback mode. A deployment that has a healthy LLM provider can
    inject one here.
    """
    return DecisionService(db)


# ========== Decision ==========

@router.post("/decide", response_model=DecisionResponse)
async def make_decision(
    request: DecisionRequest,
    service: DecisionService = Depends(get_decision_service),
):
    """Run the decision engine: understand → remember → strategy → action →
    generate → validate. Returns an explainable, quality-scored decision."""
    return await service.decide(request)


# ========== Persona Style Generation ==========

@router.post("/persona-style", response_model=PersonaStyleResponse)
async def generate_persona_style(
    request: PersonaStyleRequest,
    service: DecisionService = Depends(get_decision_service),
):
    """Generate an executable conversation style from a persona definition."""
    return await service.generate_persona_style(request)


# ========== Context Building ==========

@router.post("/context", response_model=ContextBuildResponse)
async def build_context(
    request: ContextBuildRequest,
    service: DecisionService = Depends(get_decision_service),
):
    """Build a token-budgeted conversation context block for the LLM."""
    return service.build_context(request)


# ========== Response Validation ==========

@router.post("/validate", response_model=ValidationResponse)
async def validate_response(
    request: ValidationRequest,
    service: DecisionService = Depends(get_decision_service),
):
    """Validate a generated response's quality (0-5 score + pass/fail)."""
    return service.validate_response(request)


# ========== Fallback ==========

@router.post("/fallback", response_model=FallbackDecisionResponse)
async def get_fallback(
    intent_type: str = Query("unknown", description="Intent the fallback should satisfy"),
    persona_name: Optional[str] = Query(None, description="Persona name to layer in"),
    service: DecisionService = Depends(get_decision_service),
):
    """Return a safe, intent-appropriate fallback response (LLM-down path)."""
    return service.get_fallback(intent_type, persona_name=persona_name)


# ========== Decision History / Audit ==========

@router.get("/history/{conversation_id}")
async def get_decision_history(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200, description="Number of decisions to return"),
    service: DecisionService = Depends(get_decision_service),
):
    """Return recent decision logs for a conversation (explainability/audit)."""
    history = await service.get_decision_history(conversation_id, limit)
    return {
        "conversation_id": str(conversation_id),
        "decisions": history,
        "total": len(history),
    }


# ========== Health ==========

@router.get("/health")
async def health_check():
    """Health check for the decision engine."""
    return {"status": "ok", "service": "decision-engine"}
