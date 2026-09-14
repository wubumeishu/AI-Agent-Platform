"""Intent router - Intent classification and management API"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.intent import (
    IntentClassificationRequest,
    IntentClassificationResponse,
    IntentHistoryResponse,
    IntentActionRequest,
    IntentActionResponse,
    IntentStatistics,
)
from app.services.intent_service import IntentService
from app.events.domain_events import DomainEvent, get_event_bus
import logging

logger = logging.getLogger(__name__)


# BUG-1 (t_acffd4d0): this AI-tier router self-carries its full
# `/api/v1/intents` prefix and is mounted BARE in main.py (no extra
# prefix), so the live URL is the single-prefix `/api/v1/intents/...`.
# Do NOT strip the `/api/v1` to make this a bare `"/intents"`: the pinned
# route-path assertions in tests/test_intent_api.py require router.routes
# to start with `/api/v1/intents`, and stripping would re-introduce the
# double-prefix bug if main.py ever mounts these again with a prefix.
router = APIRouter(prefix="/api/v1/intents", tags=["Intent Recognition"])


def get_intent_service(db: AsyncSession = Depends(get_db)) -> IntentService:
    """Dependency for IntentService"""
    return IntentService(db)


# ========== Intent Classification ==========

@router.post("/classify", response_model=IntentClassificationResponse)
async def classify_intent(
    request: IntentClassificationRequest,
    service: IntentService = Depends(get_intent_service),
):
    """Classify user intent"""
    result = await service.classify_intent(request)
    # Publish the classification result so event-triggered workflows can
    # react (e.g. auto-reply on high-value intents). Only successful
    # classifications emit; the payload carries intent type + confidence
    # and ids, but never the raw message text or entities' sensitive
    # fields (secrets/PII stay out of the bus).
    if result.success and result.intent is not None:
        try:
            event = DomainEvent(
                event_type="intent.classified",
                entity_type="intent",
                entity_id=request.conversation_id,
                payload={
                    "conversation_id": str(request.conversation_id) if request.conversation_id else None,
                    "intent_type": result.intent.intent_type,
                    "intent_name": result.intent.intent_name,
                    "confidence": result.intent.confidence,
                },
            )
            await get_event_bus().publish(event)
        except Exception:
            logger.exception("Failed to publish intent.classified event")
    return result


# ========== Intent History ==========

@router.get("/history/{conversation_id}", response_model=IntentHistoryResponse)
async def get_intent_history(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200, description="Number of intents to return"),
    service: IntentService = Depends(get_intent_service),
):
    """Get intent history for a conversation"""
    return await service.get_intent_history(conversation_id, limit)


# ========== Intent to Action Mapping ==========

@router.post("/map-action", response_model=IntentActionResponse)
async def map_intent_to_action(
    request: IntentActionRequest,
    service: IntentService = Depends(get_intent_service),
):
    """Map intent to appropriate action"""
    return await service.map_intent_to_action(request)


# ========== Intent Statistics ==========

@router.get("/statistics", response_model=IntentStatistics)
async def get_intent_statistics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    service: IntentService = Depends(get_intent_service),
):
    """Get intent statistics for analytics"""
    return await service.get_intent_statistics(days)


# ========== Health Check ==========

@router.get("/health")
async def health_check():
    """Health check for intent service"""
    return {"status": "ok", "service": "intent-recognition"}
