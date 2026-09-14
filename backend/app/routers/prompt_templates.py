"""Prompt Template Router - CRUD API endpoints"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.prompt_template import (
    PromptTemplateCreate,
    PromptTemplateUpdate,
    PromptTemplateResponse,
    PromptTemplateListResponse,
    VersionHistoryResponse,
    VersionDetailResponse,
    RollbackResponse,
    RenderedTemplate,
    TemplateVariablesResponse,
)
from app.services.prompt_template_service import PromptTemplateService


router = APIRouter(prefix="/prompt-templates", tags=["Prompt Templates"])


def get_prompt_template_service(
    db: AsyncSession = Depends(get_db),
) -> PromptTemplateService:
    """Dependency for PromptTemplateService"""
    return PromptTemplateService(db)


# ========== CRUD Endpoints ==========

@router.get("/", response_model=PromptTemplateListResponse)
async def list_templates(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    template_type: Optional[str] = Query(None, description="Filter by type"),
    category: Optional[str] = Query(None, description="Filter by category"),
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """List all prompt templates with pagination and filtering"""
    templates, total = await service.list_templates(
        page=page,
        page_size=page_size,
        template_type=template_type,
        category=category,
    )
    return PromptTemplateListResponse(
        items=templates,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=PromptTemplateResponse, status_code=201)
async def create_template(
    data: PromptTemplateCreate,
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """Create a new prompt template or version"""
    try:
        return await service.create_template(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{template_id}", response_model=PromptTemplateResponse)
async def get_template(
    template_id: UUID,
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """Get template by ID"""
    template = await service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.put("/{template_id}", response_model=PromptTemplateResponse)
async def update_template(
    template_id: UUID,
    data: PromptTemplateUpdate,
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """Update a template"""
    template = await service.update_template(template_id, data)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: UUID,
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """Soft delete a template"""
    success = await service.delete_template(template_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")
    return None


# ========== Version Management ==========\

@router.get("/{template_id}/versions", response_model=VersionHistoryResponse)
async def get_version_history(
    template_id: UUID,
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """Get version history for a template"""
    try:
        return await service.get_version_history(template_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{template_id}/versions/{version}", response_model=VersionDetailResponse)
async def get_version_detail(
    template_id: UUID,
    version: int = Path(..., ge=1, description="Version number"),
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """Get detailed information for a specific version"""
    try:
        return await service.get_version_detail(template_id, version)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{template_id}/versions/{version}/rollback", response_model=RollbackResponse)
async def rollback_version(
    template_id: UUID,
    version: int = Path(..., ge=1, description="Version to rollback to"),
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """Rollback to a specific version by creating a new version"""
    try:
        return await service.rollback_version(template_id, version)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{template_id}/clone", response_model=PromptTemplateResponse, status_code=201)
async def clone_template(
    template_id: UUID,
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """Clone a template to create a new version"""
    template = await service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Create new version with same content
    new_data = PromptTemplateCreate(
        name=template.name,
        description=template.description,
        content=template.content,
        template_type=template.template_type,
        category=template.category,
        variables=template.variables,
        is_baseline=False,
        parent_id=template_id,
    )
    return await service.create_template(new_data)


# ========== Template Rendering ==========

@router.post("/{template_id}/render", response_model=RenderedTemplate)
async def render_template(
    template_id: UUID,
    variables: dict,
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """Render template with variable substitution"""
    try:
        return await service.render_template(template_id, variables)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{template_id}/variables", response_model=TemplateVariablesResponse)
async def get_template_variables(
    template_id: UUID,
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """Extract variables from template"""
    try:
        return await service.get_template_variables(template_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ========== Version Comparison ==========

@router.get("/{template_id}/compare")
async def compare_versions(
    template_id: UUID,
    version1: int = Query(..., ge=1, description="First version"),
    version2: int = Query(..., ge=1, description="Second version"),
    service: PromptTemplateService = Depends(get_prompt_template_service),
):
    """Compare two versions of a template"""
    try:
        return await service.compare_versions(template_id, version1, version2)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
