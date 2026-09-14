"""
Pydantic schemas for Browser module
"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


# ---------- Provider Schemas ----------

class ProviderStatus(BaseModel):
    """Provider connection status"""
    provider: str
    connected: bool
    status: str  # "connected", "mock_mode", "error"
    message: str
    endpoint: Optional[str] = None
    timestamp: Optional[datetime] = None


class ProviderListResponse(BaseModel):
    """List of available providers"""
    providers: List[str]
    total: int


# ---------- Browser Profile Schemas ----------

class BrowserProfileCreate(BaseModel):
    """Schema for creating a browser profile"""
    provider: str = Field(default="bitbrowser", description="Provider name")
    profile_id: str = Field(..., min_length=1, max_length=100, description="External profile ID from provider")
    name: Optional[str] = Field(None, max_length=100, description="Display name")
    connection_status: str = Field(default="disconnected", pattern="^(connected|disconnected|error|mock)$", description="Connection status")


class BrowserProfileUpdate(BaseModel):
    """Schema for updating a browser profile"""
    name: Optional[str] = Field(None, max_length=100)
    connection_status: Optional[str] = Field(None, pattern="^(connected|disconnected|error|mock)$")
    profile_id: Optional[str] = Field(None, max_length=100)


class BrowserProfileResponse(BaseModel):
    """Schema for browser profile response"""
    id: UUID
    provider: str
    profile_id: str
    name: Optional[str] = None
    connection_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BrowserProfileListResponse(BaseModel):
    """Paginated browser profile list response"""
    items: List[BrowserProfileResponse]
    total: int
    page: int
    page_size: int


# ---------- Test Connection ----------

class TestConnectionResponse(BaseModel):
    """Response for test connection endpoint"""
    success: bool
    message: str
    status: str
    provider: str
    timestamp: datetime
