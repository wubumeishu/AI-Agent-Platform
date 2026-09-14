"""
Proxy Router - RESTful API for Proxy management
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.proxy import (
    ProxyCreate,
    ProxyUpdate,
    ProxyResponse,
    ProxyListResponse,
    TestConnectionResponse,
)
from app.services.proxy_service import ProxyService


router = APIRouter(prefix="/proxies", tags=["Proxies"])


def get_proxy_service(db: AsyncSession = Depends(get_db)) -> ProxyService:
    """Dependency for ProxyService"""
    return ProxyService(db)


@router.get("", response_model=ProxyListResponse)
async def list_proxies(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    type: Optional[str] = Query(None, description="Filter by type (http/https/socks5)"),
    status: Optional[str] = Query(None, description="Filter by status"),
    service: ProxyService = Depends(get_proxy_service),
):
    """列出所有代理（支持分页和类型/状态筛选）"""
    proxies, total = await service.list_proxies(page=page, page_size=page_size, type=type, status=status)
    return ProxyListResponse(items=proxies, total=total, page=page, page_size=page_size)


@router.post("", response_model=ProxyResponse, status_code=201)
async def create_proxy(
    data: ProxyCreate,
    service: ProxyService = Depends(get_proxy_service),
):
    """创建代理"""
    return await service.create_proxy(data)


@router.get("/{proxy_id}", response_model=ProxyResponse)
async def get_proxy(
    proxy_id: UUID,
    service: ProxyService = Depends(get_proxy_service),
):
    """获取代理详情"""
    proxy = await service.get_proxy(proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail=f"Proxy {proxy_id} not found")
    return proxy


@router.put("/{proxy_id}", response_model=ProxyResponse)
async def update_proxy(
    proxy_id: UUID,
    data: ProxyUpdate,
    service: ProxyService = Depends(get_proxy_service),
):
    """更新代理信息"""
    proxy = await service.update_proxy(proxy_id, data)
    if not proxy:
        raise HTTPException(status_code=404, detail=f"Proxy {proxy_id} not found")
    return proxy


@router.delete("/{proxy_id}", status_code=204)
async def delete_proxy(
    proxy_id: UUID,
    service: ProxyService = Depends(get_proxy_service),
):
    """软删除代理"""
    deleted = await service.delete_proxy(proxy_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Proxy {proxy_id} not found")
    return None


@router.post("/{proxy_id}/test", response_model=TestConnectionResponse)
async def test_proxy_connection(
    proxy_id: UUID,
    service: ProxyService = Depends(get_proxy_service),
):
    """测试代理连通性（V1 返回模拟状态）"""
    return await service.test_connection(proxy_id)
