"""Content Generation Router - Phase 5 AI Content Generation + Nurture Automation.

Endpoints:
- POST /content-generate          Generate personalized content (+ optional library save)
- POST /content-evaluate          Quality + relevance evaluation of a content piece
- POST /nurture/inject-content   Generate (or reuse) content and attach to a NurturePlan step
- GET  /content-history           Query the content-generation audit log

Follows the Phase 2 DecisionEngine idiom: the pure, provider-agnostic
``ContentGenerator`` does the work; this router wires a DB session and, when the
deployment exposes a healthy LLM provider, injects it. Absent a provider the
deterministic template path always returns a usable, quality-scored result.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.content_generation import (
    ContentEvaluationRequest,
    ContentGenerationRequest,
    ContentInjectionRequest,
    ContentInjectionResponse,
    GeneratedContent,
    GenerationHistoryResponse,
    QualityEvaluation,
)
from app.services.content_generation_service import ContentGenerationService


router = APIRouter(prefix="/api/v1/content", tags=["Content Generation"])


def get_content_generation_service(
    db: AsyncSession = Depends(get_db),
) -> ContentGenerationService:
    """Dependency: ContentGenerationService wired to the request's DB session.

    No LLM provider is wired by default → the generator runs in safe
    deterministic template mode. A deployment with a healthy LLM provider can
    inject one here (mirrors the DecisionService dependency).
    """
    return ContentGenerationService(db)


# ========== Content generation ==========

@router.post(
    "/generate",
    response_model=GeneratedContent,
    summary="Generate personalized nurture content",
)
async def generate_content_endpoint(
    request: ContentGenerationRequest,
    service: ContentGenerationService = Depends(get_content_generation_service),
):
    """Generate customer-personalized content for a segment / lifecycle stage /
    objective. Quality-scored; LLM when available, deterministic template
    otherwise. Optionally persists to the content library."""
    return await service.generate_content(request)


# ========== Quality evaluation ==========

@router.post(
    "/evaluate",
    response_model=QualityEvaluation,
    summary="Evaluate content quality + relevance",
)
async def evaluate_content_endpoint(
    request: ContentEvaluationRequest,
    service: ContentGenerationService = Depends(get_content_generation_service),
):
    """Score a content piece against its intended context (5 weighted
    dimensions → 0-5 overall + pass/fail). No generation performed."""
    return service.evaluate_content(request)


# ========== NurturePlan content injection ==========

@router.post(
    "/nurture/inject",
    response_model=ContentInjectionResponse,
    summary="Inject generated content into a NurturePlan step",
)
async def inject_content_endpoint(
    request: ContentInjectionRequest,
    service: ContentGenerationService = Depends(get_content_generation_service),
):
    """Generate (or reuse an existing library item) and attach the content to a
    NurturePlan step, linking the generation into the audit log."""
    try:
        return await service.inject_into_plan(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface DB errors as 500
        raise HTTPException(status_code=500, detail=f"Content injection failed: {exc}")


# ========== Generation history ==========

@router.get(
    "/history",
    response_model=GenerationHistoryResponse,
    summary="Query the content-generation audit log",
)
async def history_endpoint(
    account_id: UUID = Query(..., description="Account whose generations to list"),
    source: Optional[str] = Query(None, description="Filter by source (ai_content | ai_nurture)"),
    strategy: Optional[str] = Query(None, description="Filter by strategy (llm | template | library)"),
    content_id: Optional[UUID] = Query(None, description="Filter by linked content item"),
    nurture_plan_id: Optional[UUID] = Query(None, description="Filter by linked nurture plan"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: ContentGenerationService = Depends(get_content_generation_service),
):
    """Return the most-recent content-generation audit rows for an account,
    newest first, with pagination + optional filters."""
    return await service.get_history(
        account_id,
        source=source,
        strategy=strategy,
        content_id=content_id,
        nurture_plan_id=nurture_plan_id,
        limit=limit,
        offset=offset,
    )
