"""
Pydantic schemas for Platform module
"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


class PlatformCreate(BaseModel):
    """Schema for creating a platform"""
    code: str = Field(..., min_length=1, max_length=50, description="Platform unique code (e.g., wechat, douyin)")
    name: str = Field(..., min_length=1, max_length=100, description="Platform display name")
    capabilities: List[str] = Field(default=[], description="Platform capabilities list")
    adapter_class: Optional[str] = Field(None, max_length=200, description="Adapter class path")
    config: dict = Field(default={}, description="Platform configuration")
    status: str = Field(default="active", pattern="^(active|inactive)$", description="Platform status")


class PlatformUpdate(BaseModel):
    """Schema for updating a platform"""
    name: Optional[str] = Field(None, max_length=100)
    capabilities: Optional[List[str]] = None
    adapter_class: Optional[str] = Field(None, max_length=200)
    config: Optional[dict] = None
    status: Optional[str] = Field(None, pattern="^(active|inactive)$")


class PlatformResponse(BaseModel):
    """Schema for platform response"""
    id: UUID
    code: str
    name: str
    capabilities: List[str]
    adapter_class: Optional[str] = None
    config: dict
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PlatformListResponse(BaseModel):
    """Paginated platform list response"""
    items: List[PlatformResponse]
    total: int
    page: int
    page_size: int


class TestConnectionResponse(BaseModel):
    """Response for test connection endpoint"""
    success: bool
    message: str
    status: str
    platform_code: str
    timestamp: datetime
