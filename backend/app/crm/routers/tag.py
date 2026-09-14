"""
Tag Routers: CRUD + Association Management
支持标签层级结构、批量关联、统计功能
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
from uuid import UUID

from app.db.session import get_db

router = APIRouter(prefix="/crm/tags", tags=["Tag"])


# ==================== Tag CRUD ====================


@router.get("", response_model=dict)
async def list_tags(
    name: Optional[str] = Query(None, description="按名称模糊搜索"),
    parent_id: Optional[UUID] = Query(None, description="按父标签筛选"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db = Depends(get_db),
):
    """列出标签列表（支持筛选、分页）"""
    from app.crm.services.tag import list_tags as list_tags_service
    return await list_tags_service(db, name=name, parent_id=parent_id, skip=skip, limit=limit)


@router.get("/statistics", response_model=dict)
async def get_tag_statistics(db = Depends(get_db)):
    """获取标签统计信息"""
    from app.crm.services.tag import get_tag_statistics as stats_service
    return {
        "code": 0,
        "message": "success",
        "data": await stats_service(db),
    }


@router.get("/{tag_id}", response_model=dict)
async def get_tag(tag_id: UUID, db = Depends(get_db)):
    """获取单个标签详情"""
    from app.crm.services.tag import get_tag as get_tag_service
    tag = await get_tag_service(db, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")
    return tag


@router.post("", response_model=dict, status_code=201)
async def create_tag(tag_data: dict, db = Depends(get_db)):
    """创建标签"""
    from app.crm.services.tag import create_tag as create_tag_service
    try:
        return await create_tag_service(db, tag_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{tag_id}", response_model=dict)
async def update_tag(tag_id: UUID, updates: dict, db = Depends(get_db)):
    """更新标签"""
    from app.crm.services.tag import update_tag as update_tag_service
    try:
        tag = await update_tag_service(db, tag_id, updates)
        if not tag:
            raise HTTPException(status_code=404, detail="标签不存在")
        return tag
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(tag_id: UUID, db = Depends(get_db)):
    """删除标签（软删除）"""
    from app.crm.services.tag import delete_tag as delete_tag_service
    success = await delete_tag_service(db, tag_id)
    if not success:
        raise HTTPException(status_code=404, detail="标签不存在")


# ==================== Customer Associations ====================


@router.post("/customers/{customer_id}/tags", response_model=dict)
async def add_tags_to_customer(
    customer_id: UUID,
    tag_ids: List[UUID] = Query(..., description="标签 ID 列表"),
    db = Depends(get_db),
):
    """为 customerId 批量添加标签"""
    from app.crm.services.tag import add_tags_to_customer as add_service
    try:
        return await add_service(db, customer_id, tag_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/customers/{customer_id}/tags/{tag_id}", status_code=204)
async def remove_tag_from_customer(
    customer_id: UUID,
    tag_id: UUID,
    db = Depends(get_db),
):
    """从客户移除单个标签"""
    from app.crm.services.tag import remove_tag_from_customer as remove_service
    success = await remove_service(db, customer_id, tag_id)
    if not success:
        raise HTTPException(status_code=404, detail="标签关联不存在")


# ==================== Lead Associations ====================


@router.post("/leads/{lead_id}/tags", response_model=dict)
async def add_tags_to_lead(
    lead_id: UUID,
    tag_ids: List[UUID] = Query(..., description="标签 ID 列表"),
    db = Depends(get_db),
):
    """为 lead 批量添加标签"""
    from app.crm.services.tag import add_tags_to_lead as add_service
    try:
        return await add_service(db, lead_id, tag_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/leads/{lead_id}/tags/{tag_id}", status_code=204)
async def remove_tag_from_lead(
    lead_id: UUID,
    tag_id: UUID,
    db = Depends(get_db),
):
    """从 lead 移除单个标签"""
    from app.crm.services.tag import remove_tag_from_lead as remove_service
    success = await remove_service(db, lead_id, tag_id)
    if not success:
        raise HTTPException(status_code=404, detail="标签关联不存在")
