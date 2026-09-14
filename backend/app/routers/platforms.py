"""
Platform Router - RESTful API for Platform management
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.platform import (
    PlatformCreate,
    PlatformUpdate,
    PlatformResponse,
    PlatformListResponse,
    TestConnectionResponse,
)
from app.services.platform_service import PlatformService


router = APIRouter(prefix="/platforms", tags=["Platforms"])


def get_platform_service(db: AsyncSession = Depends(get_db)) -> PlatformService:
    """Dependency for PlatformService"""
    return PlatformService(db)


@router.get("", response_model=PlatformListResponse)
async def list_platforms(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    status: Optional[str] = Query(None, description="Filter by status"),
    service: PlatformService = Depends(get_platform_service),
):
    """列出所有平台（支持分页和状态筛选）"""
    platforms, total = await service.list_platforms(page=page, page_size=page_size, status=status)
    return PlatformListResponse(items=platforms, total=total, page=page, page_size=page_size)


@router.post("", response_model=PlatformResponse, status_code=201)
async def create_platform(
    data: PlatformCreate,
    service: PlatformService = Depends(get_platform_service),
):
    """创建平台（code 唯一约束）"""
    try:
        return await service.create_platform(data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{platform_id}", response_model=PlatformResponse)
async def get_platform(
    platform_id: UUID,
    service: PlatformService = Depends(get_platform_service),
):
    """获取平台详情"""
    platform = await service.get_platform(platform_id)
    if not platform:
        raise HTTPException(status_code=404, detail=f"Platform {platform_id} not found")
    return platform


@router.put("/{platform_id}", response_model=PlatformResponse)
async def update_platform(
    platform_id: UUID,
    data: PlatformUpdate,
    service: PlatformService = Depends(get_platform_service),
):
    """更新平台信息"""
    platform = await service.update_platform(platform_id, data)
    if not platform:
        raise HTTPException(status_code=404, detail=f"Platform {platform_id} not found")
    return platform


@router.delete("/{platform_id}", status_code=204)
async def delete_platform(
    platform_id: UUID,
    service: PlatformService = Depends(get_platform_service),
):
    """软删除平台"""
    deleted = await service.delete_platform(platform_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Platform {platform_id} not found")
    return None


@router.post("/{platform_id}/test", response_model=TestConnectionResponse)
async def test_platform_connection(
    platform_id: UUID,
    service: PlatformService = Depends(get_platform_service),
):
    """测试平台连接（V1 返回模拟状态）"""
    return await service.test_connection(platform_id)
