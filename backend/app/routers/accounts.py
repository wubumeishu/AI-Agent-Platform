"""Account router - CRUD and binding management"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.account import (
    AccountCreate,
    AccountUpdate,
    AccountResponse,
    AccountListResponse,
    AgentBindingCreate,
    AgentBindingResponse,
    BrowserBindingCreate,
    BrowserBindingResponse,
    ProxyBindingCreate,
    ProxyBindingResponse,
    TestConnectionResponse,
)
from app.services.account_service import AccountService


router = APIRouter(prefix="/accounts", tags=["Accounts"])


def get_account_service(db: AsyncSession = Depends(get_db)) -> AccountService:
    """Dependency for AccountService"""
    return AccountService(db)


# ========== Account CRUD ==========

@router.get("/", response_model=AccountListResponse)
async def list_accounts(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    platform_id: Optional[str] = Query(None, description="Filter by platform ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    service: AccountService = Depends(get_account_service),
):
    """List all accounts with pagination and filters"""
    accounts, total = await service.list_accounts(
        page=page,
        page_size=page_size,
        platform_id=platform_id,
        status=status,
    )
    return AccountListResponse(
        items=accounts,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=AccountResponse, status_code=201)
async def create_account(
    data: AccountCreate,
    service: AccountService = Depends(get_account_service),
):
    """Create a new account"""
    try:
        return await service.create_account(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Get account by ID"""
    account = await service.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.put("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: UUID,
    data: AccountUpdate,
    service: AccountService = Depends(get_account_service),
):
    """Update an account"""
    try:
        account = await service.update_account(account_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Soft delete an account"""
    success = await service.delete_account(account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return None


@router.post("/{account_id}/test-conn", response_model=TestConnectionResponse)
async def test_connection(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Test account connection (V1: mock response)"""
    return await service.test_connection(account_id)


# ========== Agent Bindings ==========

@router.get("/{account_id}/agent-bindings", response_model=List[AgentBindingResponse])
async def list_agent_bindings(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """List all agent bindings for an account"""
    account = await service.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return await service.list_agent_bindings(account_id)


@router.post("/{account_id}/agent-bindings", response_model=AgentBindingResponse, status_code=201)
async def create_agent_binding(
    account_id: UUID,
    data: AgentBindingCreate,
    service: AccountService = Depends(get_account_service),
):
    """Create an agent binding for an account"""
    account = await service.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return await service.create_agent_binding(account_id, data)


@router.delete("/{account_id}/agent-bindings/{agent_id}/{persona_id}", status_code=204)
async def delete_agent_binding(
    account_id: UUID,
    agent_id: UUID,
    persona_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Delete an agent binding"""
    success = await service.delete_agent_binding(account_id, agent_id, persona_id)
    if not success:
        raise HTTPException(status_code=404, detail="Binding not found")
    return None


# ========== Browser Bindings ==========

@router.get("/{account_id}/browser-bindings", response_model=List[BrowserBindingResponse])
async def list_browser_bindings(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """List all browser bindings for an account"""
    account = await service.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return await service.list_browser_bindings(account_id)


@router.post("/{account_id}/browser-bindings", response_model=BrowserBindingResponse, status_code=201)
async def create_browser_binding(
    account_id: UUID,
    data: BrowserBindingCreate,
    service: AccountService = Depends(get_account_service),
):
    """Create a browser binding for an account"""
    account = await service.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return await service.create_browser_binding(account_id, data)


@router.delete("/{account_id}/browser-bindings/{profile_id}", status_code=204)
async def delete_browser_binding(
    account_id: UUID,
    profile_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Delete a browser binding"""
    success = await service.delete_browser_binding(account_id, profile_id)
    if not success:
        raise HTTPException(status_code=404, detail="Binding not found")
    return None


# ========== Proxy Bindings ==========

@router.get("/{account_id}/proxy-bindings", response_model=List[ProxyBindingResponse])
async def list_proxy_bindings(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """List all proxy bindings for an account"""
    account = await service.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return await service.list_proxy_bindings(account_id)


@router.post("/{account_id}/proxy-bindings", response_model=ProxyBindingResponse, status_code=201)
async def create_proxy_binding(
    account_id: UUID,
    data: ProxyBindingCreate,
    service: AccountService = Depends(get_account_service),
):
    """Create a proxy binding for an account"""
    account = await service.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return await service.create_proxy_binding(account_id, data)


@router.delete("/{account_id}/proxy-bindings/{proxy_id}", status_code=204)
async def delete_proxy_binding(
    account_id: UUID,
    proxy_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Delete a proxy binding"""
    success = await service.delete_proxy_binding(account_id, proxy_id)
    if not success:
        raise HTTPException(status_code=404, detail="Binding not found")
    return None
