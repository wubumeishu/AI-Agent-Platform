"""
Customer Routers: CRUD + Identity Management
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
from uuid import UUID

from app.db.session import get_db

router = APIRouter(prefix="/crm/customers", tags=["Customer"])


# ==================== Customer CRUD ====================

@router.get("", response_model=dict)
async def list_customers(
    name: Optional[str] = Query(None, description="按名称模糊搜索"),
    phone: Optional[str] = Query(None, description="按手机号精确搜索"),
    email: Optional[str] = Query(None, description="按邮箱精确搜索"),
    tag_ids: Optional[str] = Query(None, description="标签ID列表（逗号分隔）"),
    stage_code: Optional[str] = Query(None, description="按生命周期阶段筛选"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向：asc/desc"),
    db = Depends(get_db),
):
    """列出客户列表（支持筛选、分页、排序）"""
    from app.crm.services.customer import list_customers
    
    # 解析标签ID
    tag_id_list = None
    if tag_ids:
        try:
            tag_id_list = [UUID(tid) for tid in tag_ids.split(",")]
        except Exception:
            raise HTTPException(status_code=400, detail="无效的标签ID格式")
    
    return await list_customers(
        db,
        name=name,
        phone=phone,
        email=email,
        tag_ids=tag_id_list,
        stage_code=stage_code,
        skip=skip,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/{customer_id}", response_model=dict)
async def get_customer(customer_id: UUID, db = Depends(get_db)):
    """获取单个客户详情"""
    from app.crm.services.customer import get_customer
    customer = await get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    return customer


@router.post("", response_model=dict, status_code=201)
async def create_customer(customer_data: dict, db = Depends(get_db)):
    """创建客户"""
    from app.crm.services.customer import create_customer
    try:
        return await create_customer(db, customer_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{customer_id}", response_model=dict)
async def update_customer(customer_id: UUID, updates: dict, db = Depends(get_db)):
    """更新客户"""
    from app.crm.services.customer import update_customer
    customer = await update_customer(db, customer_id, updates)
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    return customer


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(customer_id: UUID, db = Depends(get_db)):
    """删除客户（软删除）"""
    from app.crm.services.customer import delete_customer
    success = await delete_customer(db, customer_id)
    if not success:
        raise HTTPException(status_code=404, detail="客户不存在")


# ==================== CustomerIdentity CRUD ====================

@router.get("/{customer_id}/identities", response_model=List[dict])
async def list_customer_identities(
    customer_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db = Depends(get_db),
):
    """列出客户的所有身份"""
    from app.crm.services.customer import list_customer_identities
    # 先验证客户存在
    customer_result = await db.execute(
        __import__('sqlalchemy', fromlist=['select']).select(
            __import__('app.db.models', fromlist=['Customer']).Customer.id
        ).where(
            __import__('app.db.models', fromlist=['Customer']).Customer.id == customer_id,
            __import__('app.db.models', fromlist=['Customer']).Customer.is_deleted == False
        )
    )
    if not customer_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="客户不存在")
    
    return await list_customer_identities(db, customer_id, skip=skip, limit=limit)


@router.post("/{customer_id}/identities", response_model=dict, status_code=201)
async def add_customer_identity(
    customer_id: UUID,
    identity_data: dict,
    db = Depends(get_db),
):
    """为客户添加身份"""
    from app.crm.services.customer import add_customer_identity
    try:
        return await add_customer_identity(db, customer_id, identity_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{customer_id}/identities/{identity_id}", response_model=dict)
async def get_customer_identity(
    customer_id: UUID,
    identity_id: UUID,
    db = Depends(get_db),
):
    """获取单个身份"""
    from app.crm.services.customer import get_customer_identity
    identity = await get_customer_identity(db, identity_id)
    if not identity:
        raise HTTPException(status_code=404, detail="身份不存在")
    return identity


@router.put("/{customer_id}/identities/{identity_id}", response_model=dict)
async def update_customer_identity(
    customer_id: UUID,
    identity_id: UUID,
    updates: dict,
    db = Depends(get_db),
):
    """更新身份"""
    from app.crm.services.customer import update_customer_identity
    identity = await update_customer_identity(db, identity_id, updates)
    if not identity:
        raise HTTPException(status_code=404, detail="身份不存在")
    return identity


@router.delete("/{customer_id}/identities/{identity_id}", status_code=204)
async def delete_customer_identity(
    customer_id: UUID,
    identity_id: UUID,
    db = Depends(get_db),
):
    """删除身份（软删除）"""
    from app.crm.services.customer import delete_customer_identity
    success = await delete_customer_identity(db, identity_id)
    if not success:
        raise HTTPException(status_code=404, detail="身份不存在")


# ==================== Identity Resolution ====================

@router.get("/resolve/phone", response_model=dict)
async def resolve_customer_by_phone(
    phone: str = Query(..., description="手机号"),
    db = Depends(get_db),
):
    """通过手机号解析客户身份"""
    from app.crm.services.customer import resolve_customer_by_phone
    result = await resolve_customer_by_phone(db, phone)
    if not result:
        raise HTTPException(status_code=404, detail="未找到匹配的客户")
    return result


@router.get("/resolve/email", response_model=dict)
async def resolve_customer_by_email(
    email: str = Query(..., description="邮箱"),
    db = Depends(get_db),
):
    """通过邮箱解析客户身份"""
    from app.crm.services.customer import resolve_customer_by_email
    result = await resolve_customer_by_email(db, email)
    if not result:
        raise HTTPException(status_code=404, detail="未找到匹配的客户")
    return result


@router.post("/merge", response_model=dict)
async def merge_customers(
    source_customer_id: UUID = Query(..., description="源客户ID（将被删除）"),
    target_customer_id: UUID = Query(..., description="目标客户ID（接收所有身份）"),
    db = Depends(get_db),
):
    """手动合并重复客户"""
    from app.crm.services.customer import merge_customers
    try:
        return await merge_customers(db, source_customer_id, target_customer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
