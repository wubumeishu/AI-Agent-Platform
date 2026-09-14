"""Pydantic schemas for Persona module"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


class PersonaBase(BaseModel):
    """Base Persona schema"""
    name: str = Field(..., min_length=1, max_length=100, description="Persona name")
    description: Optional[str] = Field(None, description="Persona description")
    personality: dict = Field(default_factory=dict, description="Personality traits as JSON")


class PersonaCreate(PersonaBase):
    """Schema for creating a new persona"""
    pass


class PersonaUpdate(BaseModel):
    """Schema for updating a persona"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    personality: Optional[dict] = None


class PersonaResponse(PersonaBase):
    """Schema for persona response"""
    id: UUID
    version: int
    parent_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PersonaListResponse(BaseModel):
    """Paginated persona list response"""
    items: List[PersonaResponse]
    total: int
    page: int
    page_size: int


class VersionHistory(BaseModel):
    """Schema for version history entry"""
    id: UUID
    name: str
    version: int
    parent_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VersionHistoryResponse(BaseModel):
    """Response for version history"""
    items: List[VersionHistory]
    total: int
