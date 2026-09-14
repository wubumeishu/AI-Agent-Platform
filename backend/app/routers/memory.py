"""Memory Router - CRUD API endpoints for Memory System"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.memory import (
    MemoryCreate,
    MemoryUpdate,
    MemoryResponse,
    MemoryListResponse,
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryInjectionRequest,
    MemoryInjectionResponse,
    ConversationSummaryCreate,
    ConversationSummaryResponse,
    ConversationSummaryListResponse,
    ContextWindowResponse,
)
from app.services.memory_service import MemoryService


# NOTE: this router self-carries its full `/api/v1/memory` prefix (same
# convention as the other AI-tier routers) and is mounted BARE in main.py.
# The P0 OpenAPI contract (p0_openapi_paths.json) and tests/test_memory_api.py
# both require the /api/v1/memory/... paths; do NOT strip the /api/v1.
# BUG-2 (t_3a619441) + BUG-1 (t_acffd4d0): the AI-tier routers self-carry their
# full `/api/v1/<mod>` prefix and are mounted BARE in main.py. This avoids the
# /api/v1/api/v1 double-prefix defect while keeping `router.routes` paths
# well-formed (test_memory_api.py asserts they start with /api/v1/memory).
router = APIRouter(prefix="/api/v1/memory", tags=["Memory System"])


def get_memory_service(db: AsyncSession = Depends(get_db)) -> MemoryService:
    """Dependency for MemoryService"""
    return MemoryService(db)


# ========== Memory Endpoints ==========

@router.get("/", response_model=MemoryListResponse)
async def list_memories(
    customer_id: UUID = Query(..., description="Customer ID"),
    memory_type: Optional[str] = Query(None, description="Filter by memory type"),
    category: Optional[str] = Query(None, description="Filter by category"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    service: MemoryService = Depends(get_memory_service),
):
    """List memories with pagination and filtering"""
    memories, total = await service.list_memories(
        customer_id=customer_id,
        memory_type=memory_type,
        category=category,
        page=page,
        page_size=page_size,
    )
    return MemoryListResponse(
        items=memories,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=MemoryResponse, status_code=201)
async def create_memory(
    data: MemoryCreate,
    service: MemoryService = Depends(get_memory_service),
):
    """Create a new long-term memory"""
    return await service.create_memory(data)


# ========== Memory Search ==========

@router.post("/search", response_model=MemorySearchResponse)
async def search_memories(
    request: MemorySearchRequest,
    service: MemoryService = Depends(get_memory_service),
):
    """Search memories using keyword matching"""
    return await service.search_memories(request)


@router.post("/inject", response_model=MemoryInjectionResponse)
async def inject_memories(
    request: MemoryInjectionRequest,
    service: MemoryService = Depends(get_memory_service),
):
    """Inject relevant memories into conversation context"""
    return await service.inject_memories_into_context(request)


# ========== Conversation Summary Endpoints ==========

@router.post("/conversations/{conversation_id}/summaries", 
             response_model=ConversationSummaryResponse, status_code=201)
async def create_conversation_summary(
    conversation_id: UUID,
    data: ConversationSummaryCreate,
    service: MemoryService = Depends(get_memory_service),
):
    """Create a conversation summary"""
    if data.conversation_id != conversation_id:
        raise HTTPException(status_code=400, detail="Conversation ID mismatch")
    return await service.create_conversation_summary(data)


@router.get("/conversations/{conversation_id}/summaries", 
            response_model=ConversationSummaryListResponse)
async def get_conversation_summaries(
    conversation_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=50, description="Page size"),
    service: MemoryService = Depends(get_memory_service),
):
    """Get conversation summaries"""
    summaries, total = await service.get_conversation_summaries(
        conversation_id=conversation_id,
        page=page,
        page_size=page_size,
    )
    return ConversationSummaryListResponse(
        items=summaries,
        total=total,
        page=page,
        page_size=page_size,
    )


# ========== Context Window Endpoints ==========

@router.get("/conversations/{conversation_id}/context-window",
            response_model=ContextWindowResponse)
async def get_context_window(
    conversation_id: UUID,
    service: MemoryService = Depends(get_memory_service),
):
    """Get context window status for a conversation"""
    return await service.check_compression_needed(conversation_id)


# ========== Statistics Endpoints ==========

@router.get("/statistics/{customer_id}")
async def get_memory_statistics(
    customer_id: UUID,
    service: MemoryService = Depends(get_memory_service),
):
    """Get memory statistics for a customer"""
    return await service.get_memory_statistics(customer_id)


# ========== Health Check ==========

@router.get("/health")
async def health_check():
    """Health check for memory service"""
    return {"status": "ok", "service": "memory-system"}


# ========== Memory Item Endpoints (catch-all; MUST stay last) ==========
# The /{memory_id} routes use a UUID-typed path param and act as a catch-all
# for any single-segment path. FastAPI/Starlette matches routes in DEFINITION
# ORDER, so these must be registered AFTER every concrete path (/health,
# /statistics/{id}, /search, /inject, /conversations/...) or they would
# shadow those endpoints (e.g. GET /health -> 422 uuid_parsing on 'health').

@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: UUID,
    service: MemoryService = Depends(get_memory_service),
):
    """Get memory by ID"""
    memory = await service.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@router.put("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: UUID,
    data: MemoryUpdate,
    service: MemoryService = Depends(get_memory_service),
):
    """Update memory"""
    memory = await service.update_memory(memory_id, data)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: UUID,
    service: MemoryService = Depends(get_memory_service),
):
    """Soft delete a memory"""
    success = await service.delete_memory(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")
    return None
