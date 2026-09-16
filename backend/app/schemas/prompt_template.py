"""Pydantic schemas for PromptTemplate module"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


class PromptTemplateBase(BaseModel):
    """Base PromptTemplate schema"""
    name: str = Field(..., min_length=1, max_length=200, description="Template name")
    description: Optional[str] = Field(None, description="Template description")
    content: str = Field(..., min_length=1, description="Template content with {{variable}} syntax")
    template_type: str = Field(default="custom", pattern="^(system|conversation|greeting|custom)$", description="Template type")
    category: Optional[str] = Field(None, max_length=100, description="Category for organization")
    variables: Optional[List[str]] = Field(None, description="List of variable names in template")


class PromptTemplateCreate(PromptTemplateBase):
    """Schema for creating a new prompt template"""
    is_baseline: bool = Field(default=False, description="Whether to set as baseline version")
    parent_id: Optional[UUID] = Field(None, description="Parent template ID for versioning")


class PromptTemplateUpdate(BaseModel):
    """Schema for updating a prompt template"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    content: Optional[str] = Field(None, min_length=1)
    template_type: Optional[str] = Field(None, pattern="^(system|conversation|greeting|custom)$")
    category: Optional[str] = Field(None, max_length=100)
    variables: Optional[List[str]] = None
    is_baseline: Optional[bool] = None


class PromptTemplateResponse(PromptTemplateBase):
    """Schema for prompt template response"""
    id: UUID
    version: int
    parent_id: Optional[UUID] = None
    is_baseline: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromptTemplateListResponse(BaseModel):
    """Paginated prompt template list response"""
    items: List[PromptTemplateResponse]
    total: int
    page: int
    page_size: int


class VersionHistory(BaseModel):
    """Schema for version history entry"""
    id: UUID
    name: str
    version: int
    parent_id: Optional[UUID] = None
    is_baseline: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VersionDetailResponse(PromptTemplateBase):
    """Schema for version detail response"""
    id: UUID
    version: int
    parent_id: Optional[UUID] = None
    is_baseline: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RollbackResponse(BaseModel):
    """Schema for rollback response"""
    template_id: UUID
    template_name: str
    new_version: int
    rolled_back_from: int
    message: str


class VersionHistoryResponse(BaseModel):
    """Response for version history"""
    items: List[VersionHistory]
    total: int


class RenderedTemplate(BaseModel):
    """Schema for rendered template with variable substitution"""
    template_id: UUID
    template_name: str
    content: str
    variables_used: dict
    cached: bool = False


class VariableDefinition(BaseModel):
    """Schema for variable definition"""
    name: str = Field(..., description="Variable name without braces")
    description: Optional[str] = Field(None, description="Variable description")
    default: Optional[str] = Field(None, description="Default value")


class TemplateVariablesResponse(BaseModel):
    """Response for template variables"""
    template_id: UUID
    template_name: str
    variables: List[VariableDefinition]


class CacheStats(BaseModel):
    """Schema for cache statistics"""
    hit_count: int = 0
    miss_count: int = 0
    hit_rate: float = 0.0
    total_queries: int = 0
