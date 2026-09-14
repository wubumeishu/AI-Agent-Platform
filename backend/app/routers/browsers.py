"""
Browser Provider 路由层
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.browser import (
    ProviderListResponse,
    ProviderStatus,
    BrowserProfileCreate,
    BrowserProfileUpdate,
    BrowserProfileResponse,
    BrowserProfileListResponse,
    TestConnectionResponse,
)
from app.services.browser_service import BrowserService


router = APIRouter(prefix="/browsers", tags=["Browsers"])


def get_browser_service(db: AsyncSession = Depends(get_db)) -> BrowserService:
    """Dependency for BrowserService"""
    return BrowserService(db)


# ========== Provider Endpoints ==========

@router.get("/providers", response_model=ProviderListResponse)
async def list_providers(service: BrowserService = Depends(get_browser_service)):
    """列出所有可用的浏览器提供商"""
    providers = await service.list_providers()
    return ProviderListResponse(providers=providers, total=len(providers))


@router.get("/providers/{provider_name}/status", response_model=ProviderStatus)
async def get_provider_status(
    provider_name: str,
    service: BrowserService = Depends(get_browser_service),
):
    """获取指定提供商的连接状态"""
    status = await service.get_provider_status(provider_name)
    if not status:
        raise HTTPException(status_code=404, detail=f"Provider {provider_name} not found")
    return status


@router.post("/providers/{provider_name}/test", response_model=TestConnectionResponse)
async def test_provider_connection(
    provider_name: str,
    service: BrowserService = Depends(get_browser_service),
):
    """测试与提供商的连接"""
    return await service.test_provider_connection(provider_name)


# ========== Profile Endpoints ==========

@router.get("/profiles", response_model=BrowserProfileListResponse)
async def list_profiles(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    provider: Optional[str] = Query(None, description="Filter by provider"),
    connection_status: Optional[str] = Query(None, description="Filter by connection status"),
    service: BrowserService = Depends(get_browser_service),
):
    """列出所有浏览器配置"""
    profiles, total = await service.list_profiles(
        page=page,
        page_size=page_size,
        provider=provider,
        connection_status=connection_status,
    )
    return BrowserProfileListResponse(
        items=profiles,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/profiles", response_model=BrowserProfileResponse, status_code=201)
async def create_profile(
    data: BrowserProfileCreate,
    service: BrowserService = Depends(get_browser_service),
):
    """创建新的浏览器配置"""
    return await service.create_profile(data)


@router.get("/profiles/{profile_id}", response_model=BrowserProfileResponse)
async def get_profile(
    profile_id: UUID,
    service: BrowserService = Depends(get_browser_service),
):
    """获取单个配置详情"""
    profile = await service.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.put("/profiles/{profile_id}", response_model=BrowserProfileResponse)
async def update_profile(
    profile_id: UUID,
    data: BrowserProfileUpdate,
    service: BrowserService = Depends(get_browser_service),
):
    """更新配置"""
    profile = await service.update_profile(profile_id, data)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: UUID,
    service: BrowserService = Depends(get_browser_service),
):
    """软删除配置"""
    success = await service.delete_profile(profile_id)
    if not success:
        raise HTTPException(status_code=404, detail="Profile not found")
    return None
