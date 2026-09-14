"""
Customer 360 Router
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
from uuid import UUID

from app.db.session import get_db

router = APIRouter(prefix="/360", tags=["Customer 360"])


@router.get("/{customer_id}", response_model=dict)
async def get_customer_360(
    customer_id: UUID,
    db = Depends(get_db),
):
    """获取 Customer 360 完整数据"""
    from app.crm.services.customer_360 import get_customer_360 as get_customer_360_service
    
    data = await get_customer_360_service(db, customer_id)
    if not data:
        raise HTTPException(status_code=404, detail="客户不存在")
    
    return {"code": 0, "message": "success", "data": data}


@router.get("/{customer_id}/conversations", response_model=dict)
async def get_customer_conversations(
    customer_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db = Depends(get_db),
):
    """获取客户对话历史"""
    from app.crm.services.customer_360 import get_customer_conversations as get_conversations_service
    
    data = await get_conversations_service(db, customer_id, skip=skip, limit=limit)
    return {"code": 0, "message": "success", "data": data}


@router.get("/{customer_id}/memories", response_model=dict)
async def get_customer_memories(
    customer_id: UUID,
    category: Optional[str] = Query(None, description="按分类筛选"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db = Depends(get_db),
):
    """获取客户记忆摘要"""
    from app.crm.services.customer_360 import get_customer_memories as get_memories_service
    
    data = await get_memories_service(db, customer_id, category=category, skip=skip, limit=limit)
    return {"code": 0, "message": "success", "data": data}


@router.get("/{customer_id}/activities", response_model=dict)
async def get_customer_activities(
    customer_id: UUID,
    activity_type: Optional[str] = Query(None, description="按活动类型筛选"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db = Depends(get_db),
):
    """获取客户活动记录"""
    from app.crm.services.customer_360 import get_customer_activities as get_activities_service
    
    data = await get_activities_service(db, customer_id, activity_type=activity_type, skip=skip, limit=limit)
    return {"code": 0, "message": "success", "data": data}


from pydantic import BaseModel


class AddActivityRequest(BaseModel):
    activity_type: str
    title: str
    description: Optional[str] = None
    related_lead_id: Optional[UUID] = None
    metadata: Optional[dict] = None


@router.post("/{customer_id}/activities", response_model=dict, status_code=201)
async def add_customer_activity(
    customer_id: UUID,
    request: AddActivityRequest,
    db = Depends(get_db),
):
    """添加活动记录"""
    from app.crm.services.customer_360 import add_activity as add_activity_service

    activity = await add_activity_service(
        db,
        customer_id,
        request.activity_type,
        request.title,
        description=request.description,
        related_lead_id=request.related_lead_id,
        metadata=request.metadata,
    )
    return {"code": 0, "message": "success", "data": activity}
