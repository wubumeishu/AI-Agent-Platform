"""
Pydantic schemas for Proxy module
"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


class ProxyCreate(BaseModel):
    """Schema for creating a proxy"""
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(http|https|socks5)$", description="Proxy type")
    host: str = Field(..., min_length=1, max_length=200)
    port: int = Field(..., ge=1, le=65535)
    username: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = Field(
        None,
        description="Credential value. Stored as provided (V1: no at-rest "
        "encryption yet — P5MSG-11 P1-1 follow-up); response payloads "
        "never echo it (ProxyResponse carries no password field).",
    )
    status: str = Field(default="active", pattern="^(active|inactive|failed)$")


class ProxyUpdate(BaseModel):
    """Schema for updating a proxy"""
    name: Optional[str] = Field(None, max_length=100)
    type: Optional[str] = Field(None, pattern="^(http|https|socks5)$")
    host: Optional[str] = Field(None, max_length=200)
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = Field(None, description="Plain text password (will be encrypted)")
    status: Optional[str] = Field(None, pattern="^(active|inactive|failed)$")


class ProxyResponse(BaseModel):
    """Schema for proxy response"""
    id: UUID
    name: str
    type: str
    host: str
    port: int
    username: Optional[str] = None
    status: str
    last_tested: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProxyListResponse(BaseModel):
    """Paginated proxy list response"""
    items: List[ProxyResponse]
    total: int
    page: int
    page_size: int


class TestConnectionResponse(BaseModel):
    """Response for test connection endpoint"""
    success: bool
    message: str
    status: str
    proxy_id: UUID
    timestamp: datetime
