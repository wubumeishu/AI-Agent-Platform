"""Persona router - CRUD and version management"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.persona import (
    PersonaCreate,
    PersonaUpdate,
    PersonaResponse,
    PersonaListResponse,
    VersionHistoryResponse,
)
from app.services.persona_service import PersonaService


router = APIRouter(prefix="/personas", tags=["Personas"])


def get_persona_service(db: AsyncSession = Depends(get_db)) -> PersonaService:
    """Dependency for PersonaService"""
    return PersonaService(db)


# ========== Persona CRUD ==========

@router.get("/", response_model=PersonaListResponse)
async def list_personas(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    service: PersonaService = Depends(get_persona_service),
):
    """List all personas with pagination"""
    personas, total = await service.list_personas(page=page, page_size=page_size)
    return PersonaListResponse(
        items=personas,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=PersonaResponse, status_code=201)
async def create_persona(
    data: PersonaCreate,
    service: PersonaService = Depends(get_persona_service),
):
    """Create a new persona"""
    return await service.create_persona(data)


@router.get("/{persona_id}", response_model=PersonaResponse)
async def get_persona(
    persona_id: UUID,
    service: PersonaService = Depends(get_persona_service),
):
    """Get persona by ID"""
    persona = await service.get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return persona


@router.put("/{persona_id}", response_model=PersonaResponse)
async def update_persona(
    persona_id: UUID,
    data: PersonaUpdate,
    service: PersonaService = Depends(get_persona_service),
):
    """Update a persona"""
    persona = await service.update_persona(persona_id, data)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return persona


@router.delete("/{persona_id}", status_code=204)
async def delete_persona(
    persona_id: UUID,
    service: PersonaService = Depends(get_persona_service),
):
    """Soft delete a persona"""
    success = await service.delete_persona(persona_id)
    if not success:
        raise HTTPException(status_code=404, detail="Persona not found")
    return None


# ========== Version Management ==========

@router.get("/{persona_id}/versions", response_model=VersionHistoryResponse)
async def get_version_history(
    persona_id: UUID,
    service: PersonaService = Depends(get_persona_service),
):
    """Get version history for a persona"""
    persona = await service.get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return await service.get_version_history(persona_id)


@router.post("/{persona_id}/clone", response_model=PersonaResponse, status_code=201)
async def clone_persona(
    persona_id: UUID,
    service: PersonaService = Depends(get_persona_service),
):
    """Clone a persona to create a new version"""
    persona = await service.get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return await service.clone_persona(persona_id)
