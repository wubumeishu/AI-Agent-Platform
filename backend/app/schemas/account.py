"""Pydantic schemas for Account module"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


# ---------- Account Schemas ----------

class AccountBase(BaseModel):
    """Base Account schema"""
    platform_id: str = Field(..., min_length=1, max_length=50, description="Platform identifier (e.g., wechat, douyin)")
    name: str = Field(..., min_length=1, max_length=100, description="Account name")
    username: Optional[str] = Field(None, max_length=200, description="Login username")
    password_encrypted: Optional[str] = Field(
        None,
        description="Credential value. Stored as provided (V1: no at-rest "
        "encryption yet — see P5MSG-11 P1-1 follow-up); API responses "
        "always echo a masked sentinel ('***'), never the value.",
    )


class AccountCreate(AccountBase):
    """Schema for creating a new account"""
    status: str = Field("disconnected", pattern="^(connected|disconnected|failed)$", description="Account status")


class AccountUpdate(BaseModel):
    """Schema for updating an account"""
    platform_id: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    username: Optional[str] = Field(None, max_length=200)
    password_encrypted: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(connected|disconnected|failed)$")


class AccountResponse(AccountBase):
    """Schema for account response"""
    id: UUID
    status: str
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AccountListResponse(BaseModel):
    """Paginated account list response"""
    items: List[AccountResponse]
    total: int
    page: int
    page_size: int


# ---------- Binding Schemas ----------

class AgentBindingBase(BaseModel):
    """Base schema for agent binding"""
    agent_id: UUID
    persona_id: UUID
    is_primary: bool = False


class AgentBindingCreate(AgentBindingBase):
    """Schema for creating agent binding"""
    pass


class AgentBindingResponse(AgentBindingBase):
    """Schema for agent binding response"""
    account_id: UUID
    bound_at: datetime

    model_config = {"from_attributes": True}


class BrowserBindingBase(BaseModel):
    """Base schema for browser binding"""
    profile_id: UUID


class BrowserBindingCreate(BrowserBindingBase):
    """Schema for creating browser binding"""
    pass


class BrowserBindingResponse(BrowserBindingBase):
    """Schema for browser binding response"""
    account_id: UUID
    bound_at: datetime
    profile_name: Optional[str] = None
    profile_provider: Optional[str] = None

    model_config = {"from_attributes": True}


class ProxyBindingBase(BaseModel):
    """Base schema for proxy binding"""
    proxy_id: UUID


class ProxyBindingCreate(ProxyBindingBase):
    """Schema for creating proxy binding"""
    pass


class ProxyBindingResponse(ProxyBindingBase):
    """Schema for proxy binding response"""
    account_id: UUID
    bound_at: datetime
    proxy_name: Optional[str] = None
    proxy_type: Optional[str] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None

    model_config = {"from_attributes": True}


# ---------- Test Connection ----------

class TestConnectionResponse(BaseModel):
    """Response for test connection endpoint"""
    success: bool
    message: str
    status: str
    timestamp: datetime
