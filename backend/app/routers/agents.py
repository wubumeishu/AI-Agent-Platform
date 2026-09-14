"""Agent router - CRUD and Customer-Agent integration"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentListResponse,
    AgentCustomerBindingCreate,
    AgentCustomerBindingResponse,
    AgentPerformanceStats,
)
from app.services.agent_service import AgentService


router = APIRouter(prefix="/api/v1/agents", tags=["Agents"])


def get_agent_service(db: AsyncSession = Depends(get_db)) -> AgentService:
    """Dependency for AgentService"""
    return AgentService(db)


# ========== Agent CRUD ==========

@router.get("/", response_model=AgentListResponse)
async def list_agents(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    status: Optional[str] = Query(None, description="Filter by status"),
    name: Optional[str] = Query(None, description="Filter by name (fuzzy)"),
    service: AgentService = Depends(get_agent_service),
):
    """List all agents with pagination and filters"""
    agents, total = await service.list_agents(
        page=page,
        page_size=page_size,
        status=status,
        name=name,
    )
    return AgentListResponse(
        items=agents,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=AgentResponse, status_code=201)
async def create_agent(
    data: AgentCreate,
    service: AgentService = Depends(get_agent_service),
):
    """Create a new agent"""
    return await service.create_agent(data)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    service: AgentService = Depends(get_agent_service),
):
    """Get agent by ID"""
    agent = await service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    service: AgentService = Depends(get_agent_service),
):
    """Update an agent"""
    agent = await service.update_agent(agent_id, data)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: UUID,
    service: AgentService = Depends(get_agent_service),
):
    """Soft delete an agent"""
    success = await service.delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return None


# ========== Agent lifecycle (V1 status transitions) ==========

@router.post("/{agent_id}/start", response_model=AgentResponse)
async def start_agent(
    agent_id: UUID,
    service: AgentService = Depends(get_agent_service),
):
    """Start an agent (V1: sets status to 'active')"""
    agent = await service.start_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/{agent_id}/stop", response_model=AgentResponse)
async def stop_agent(
    agent_id: UUID,
    service: AgentService = Depends(get_agent_service),
):
    """Stop an agent (V1: sets status to 'inactive')"""
    agent = await service.stop_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


# ========== Agent-Customer Bindings ==========

@router.get("/{agent_id}/customers", response_model=AgentListResponse)
async def list_agent_customers(
    agent_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    service: AgentService = Depends(get_agent_service),
):
    """List all customers assigned to an agent"""
    try:
        customers, total = await service.list_agent_customers(
            agent_id=agent_id,
            page=page,
            page_size=page_size,
        )
        return AgentListResponse(
            items=[{
                "id": c.customer_id,
                "name": c.customer_name,
                "email": c.customer_email,
                "phone": c.customer_phone,
                "assigned_at": c.assigned_at.isoformat() if c.assigned_at else None,
                "notes": c.notes,
            } for c in customers],
            total=total,
            page=page,
            page_size=page_size,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{agent_id}/customers", response_model=AgentCustomerBindingResponse, status_code=201)
async def assign_customer_to_agent(
    agent_id: UUID,
    data: AgentCustomerBindingCreate,
    service: AgentService = Depends(get_agent_service),
):
    """Assign a customer to an agent"""
    try:
        return await service.assign_customer_to_agent(agent_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{agent_id}/customers/{customer_id}", status_code=204)
async def remove_customer_from_agent(
    agent_id: UUID,
    customer_id: UUID,
    service: AgentService = Depends(get_agent_service),
):
    """Remove a customer from an agent"""
    success = await service.remove_customer_from_agent(agent_id, customer_id)
    if not success:
        raise HTTPException(status_code=404, detail="Binding not found")
    return None


# ========== Agent Performance ==========

@router.get("/{agent_id}/performance", response_model=AgentPerformanceStats)
async def get_agent_performance(
    agent_id: UUID,
    service: AgentService = Depends(get_agent_service),
):
    """Get agent performance statistics"""
    stats = await service.get_agent_performance(agent_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Agent not found")
    return stats
