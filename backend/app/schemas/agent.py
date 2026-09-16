"""Pydantic schemas for Agent module"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


# ---------- Agent Schemas ----------

class AgentBase(BaseModel):
    """Base Agent schema"""
    name: str = Field(..., min_length=1, max_length=100, description="Agent name")
    description: Optional[str] = Field(None, description="Agent description")
    status: str = Field("active", pattern="^(active|inactive|paused)$", description="Agent status")


class AgentCreate(AgentBase):
    """Schema for creating a new agent"""
    pass


class AgentUpdate(BaseModel):
    """Schema for updating an agent"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|inactive|paused)$")


class AgentResponse(AgentBase):
    """Schema for agent response"""
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentListResponse(BaseModel):
    """Paginated agent list response"""
    items: List[AgentResponse]
    total: int
    page: int
    page_size: int


# ---------- Agent-Customer Binding Schemas ----------

class AgentCustomerBindingBase(BaseModel):
    """Base schema for agent-customer binding"""
    customer_id: UUID
    notes: Optional[str] = Field(None, description="Assignment notes")


class AgentCustomerBindingCreate(AgentCustomerBindingBase):
    """Schema for creating agent-customer binding"""
    pass


class AgentCustomerBindingResponse(AgentCustomerBindingBase):
    """Schema for agent-customer binding response"""
    id: UUID
    agent_id: UUID
    assigned_at: datetime
    assigned_by: Optional[UUID] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None

    model_config = {"from_attributes": True}


class AgentCustomerListResponse(BaseModel):
    """Paginated customer list for an agent"""
    items: List[AgentCustomerBindingResponse]
    total: int
    page: int
    page_size: int


# ---------- Agent Performance Schemas ----------

class AgentPerformanceStats(BaseModel):
    """Agent performance statistics"""
    agent_id: UUID
    agent_name: str
    total_customers: int = Field(default=0, description="Total responsible customers")
    active_customers: int = Field(default=0, description="Active customers")
    conversion_rate: Optional[float] = Field(None, description="Conversion rate (0-100)")
    leads_count: int = Field(default=0, description="Number of leads")
    deals_count: int = Field(default=0, description="Number of deals")
    deals_value: float = Field(default=0.0, description="Total deal value")
