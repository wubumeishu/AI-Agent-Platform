"""
Customer Service: Full CRUD + Identity Management
基于 SQLAlchemy ORM
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from app.db.models.customer import Customer
from app.db.models.customer_identity import CustomerIdentity
from app.db.models.tag import Tag, tag_customer

logger = logging.getLogger(__name__)


# ---------------- Domain event publishing (workflow-CRM integration) ----------------
def _publish_customer_created(customer) -> None:
    """Queue a ``customer.created`` event for a freshly persisted customer."""
    try:
        from app.services.crm_events import get_crm_publisher

        pub = get_crm_publisher()
        pub.publish_nowait(
            pub.build(
                "customer.created",
                "customer",
                customer.id,
                {
                    "name": getattr(customer, "name", None),
                    "company": getattr(customer, "company", None),
                },
            )
        )
    except Exception:
        logger.debug("failed to queue customer.created event", exc_info=True)


# ==================== Customer CRUD ====================

async def get_customer(db: AsyncSession, customer_id: UUID) -> Optional[dict]:
    """获取单个客户"""
    result = await db.execute(
        select(Customer)
        .options(
            selectinload(Customer.identities),
            selectinload(Customer.tags)
        )
        .where(Customer.id == customer_id, Customer.is_deleted == False)
    )
    customer = result.scalar_one_or_none()
    
    if not customer:
        return None
    
    return {
        "id": str(customer.id),
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "company": customer.company,
        "avatar_url": customer.avatar_url,
        "extra_info": customer.extra_info or {},
        "identities": [
            {
                "id": str(i.id),
                "platform": i.platform,
                "platform_account_id": i.platform_account_id,
                "platform_username": i.platform_username,
                "phone": i.phone,
                "email": i.email,
                "external_id": i.external_id,
                "match_score": i.match_score,
                "confidence": i.confidence,
                "source": i.source,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in customer.identities
        ],
        "tags": [
            {
                "id": str(t.id),
                "name": t.name,
                "color": t.color,
            }
            for t in customer.tags
        ],
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
        "updated_at": customer.updated_at.isoformat() if customer.updated_at else None,
    }


async def list_customers(
    db: AsyncSession,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    tag_ids: Optional[List[UUID]] = None,
    stage_code: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc"
) -> Dict[str, Any]:
    """
    列出客户列表（支持筛选、分页、排序）
    
    - name: 按名称模糊搜索
    - phone: 按手机号精确搜索
    - email: 按邮箱精确搜索
    - tag_ids: 按标签筛选（多选）
    - stage_code: 按生命周期阶段筛选
    """
    # 基础查询
    query = select(Customer).where(Customer.is_deleted == False)
    
    # 名称模糊搜索
    if name:
        query = query.where(Customer.name.like(f"%{name}%"))
    
    # 手机号精确搜索
    if phone:
        query = query.where(Customer.phone == phone)
    
    # 邮箱精确搜索
    if email:
        query = query.where(Customer.email == email)
    
    # 标签筛选（多选）
    if tag_ids:
        query = query.join(Customer.tags).where(Tag.id.in_(tag_ids))
    
    # 生命周期阶段筛选（通过 Lead 关联）
    if stage_code:
        from app.db.models.lead import Lead
        query = (
            query
            .join(Lead, Lead.customer_id == Customer.id, isouter=True)
            .where(Lead.lifecycle_stage_code == stage_code)
        )
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # 排序
    sort_field = getattr(Customer, sort_by, Customer.created_at)
    if sort_order == "desc":
        query = query.order_by(sort_field.desc())
    else:
        query = query.order_by(sort_field.asc())
    
    # 分页
    query = query.offset(skip).limit(limit)
    
    # 执行查询并加载关联数据
    result = await db.execute(
        query
        .options(
            selectinload(Customer.identities),
            selectinload(Customer.tags)
        )
    )
    customers = result.scalars().all()
    
    # 构建响应
    data = [
        {
            "id": str(c.id),
            "name": c.name,
            "email": c.email,
            "phone": c.phone,
            "company": c.company,
            "avatar_url": c.avatar_url,
            "identities_count": len(c.identities),
            "tags": [
                {"id": str(t.id), "name": t.name}
                for t in c.tags
            ],
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in customers
    ]
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "data": data,
    }


async def create_customer(db: AsyncSession, customer_data: dict) -> dict:
    """创建客户"""
    new_customer = Customer(**customer_data)
    db.add(new_customer)
    await db.commit()
    await db.refresh(new_customer)
    
    logger.info(f"Created customer: {new_customer.id}")
    _publish_customer_created(new_customer)
    return await get_customer(db, new_customer.id)


async def update_customer(db: AsyncSession, customer_id: UUID, updates: dict) -> Optional[dict]:
    """更新客户"""
    result = await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False)
    )
    customer = result.scalar_one_or_none()
    
    if not customer:
        return None
    
    # 允许更新的字段
    updatable_fields = ["name", "email", "phone", "company", "avatar_url", "extra_info"]
    
    for key, value in updates.items():
        if key in updatable_fields and value is not None:
            setattr(customer, key, value)
    
    # P6AN-17 P2-3: aware-UTC timestamptz write (customer columns are timestamptz).
    customer.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(customer)
    
    logger.info(f"Updated customer: {customer_id}")
    return await get_customer(db, customer_id)


async def delete_customer(db: AsyncSession, customer_id: UUID) -> bool:
    """删除客户（软删除）"""
    result = await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False)
    )
    customer = result.scalar_one_or_none()
    
    if not customer:
        return False
    
    customer.is_deleted = True
    await db.commit()
    
    logger.info(f"Deleted customer: {customer_id}")
    return True


# ==================== CustomerIdentity CRUD ====================

async def add_customer_identity(
    db: AsyncSession,
    customer_id: UUID,
    identity_data: dict
) -> dict:
    """为客户添加身份"""
    # 验证客户存在
    result = await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False)
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise ValueError(f"客户 {customer_id} 不存在")
    
    # 检查是否已存在相同平台+账号的身份
    existing = await db.execute(
        select(CustomerIdentity).where(
            and_(
                CustomerIdentity.customer_id == customer_id,
                CustomerIdentity.platform == identity_data["platform"],
                CustomerIdentity.platform_account_id == identity_data["platform_account_id"],
                CustomerIdentity.is_deleted == False
            )
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("该平台账号身份已存在")
    
    # 创建新身份
    new_identity = CustomerIdentity(
        customer_id=customer_id,
        **identity_data
    )
    db.add(new_identity)
    await db.commit()
    await db.refresh(new_identity)
    
    logger.info(f"Added identity to customer {customer_id}: platform={identity_data['platform']}")
    return await get_customer_identity(db, new_identity.id)


async def list_customer_identities(
    db: AsyncSession,
    customer_id: UUID,
    skip: int = 0,
    limit: int = 20
) -> List[dict]:
    """列出客户的所有身份"""
    result = await db.execute(
        select(CustomerIdentity)
        .where(
            and_(
                CustomerIdentity.customer_id == customer_id,
                CustomerIdentity.is_deleted == False
            )
        )
        .offset(skip)
        .limit(limit)
    )
    identities = result.scalars().all()
    
    return [
        {
            "id": str(i.id),
            "platform": i.platform,
            "platform_account_id": i.platform_account_id,
            "platform_username": i.platform_username,
            "phone": i.phone,
            "email": i.email,
            "external_id": i.external_id,
            "match_score": i.match_score,
            "confidence": i.confidence,
            "source": i.source,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in identities
    ]


async def get_customer_identity(db: AsyncSession, identity_id: UUID) -> Optional[dict]:
    """获取单个身份"""
    result = await db.execute(
        select(CustomerIdentity)
        .where(CustomerIdentity.id == identity_id, CustomerIdentity.is_deleted == False)
    )
    identity = result.scalar_one_or_none()
    
    if not identity:
        return None
    
    return {
        "id": str(identity.id),
        "customer_id": str(identity.customer_id),
        "platform": identity.platform,
        "platform_account_id": identity.platform_account_id,
        "platform_username": identity.platform_username,
        "phone": identity.phone,
        "email": identity.email,
        "external_id": identity.external_id,
        "match_score": identity.match_score,
        "confidence": identity.confidence,
        "source": identity.source,
        "extra_data": identity.extra_data or {},
        "created_at": identity.created_at.isoformat() if identity.created_at else None,
    }


async def update_customer_identity(
    db: AsyncSession,
    identity_id: UUID,
    updates: dict
) -> Optional[dict]:
    """更新身份"""
    result = await db.execute(
        select(CustomerIdentity).where(
            CustomerIdentity.id == identity_id,
            CustomerIdentity.is_deleted == False
        )
    )
    identity = result.scalar_one_or_none()
    
    if not identity:
        return None
    
    updatable_fields = ["platform_username", "phone", "email", "external_id", "extra_data"]
    
    for key, value in updates.items():
        if key in updatable_fields and value is not None:
            setattr(identity, key, value)
    
    identity.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(identity)
    
    return await get_customer_identity(db, identity_id)


async def delete_customer_identity(db: AsyncSession, identity_id: UUID) -> bool:
    """删除身份（软删除）"""
    result = await db.execute(
        select(CustomerIdentity).where(
            CustomerIdentity.id == identity_id,
            CustomerIdentity.is_deleted == False
        )
    )
    identity = result.scalar_one_or_none()
    
    if not identity:
        return False
    
    identity.is_deleted = True
    await db.commit()
    
    return True


# ==================== Identity Resolution ====================

async def resolve_customer_by_phone(
    db: AsyncSession,
    phone: str
) -> Optional[dict]:
    """通过手机号解析客户身份"""
    from app.db.models.customer import Customer as CustomerModel
    # 查找是否有匹配的手机号的身份
    result = await db.execute(
        select(CustomerIdentity)
        .options(selectinload(CustomerIdentity.customer))
        .join(CustomerModel, CustomerModel.id == CustomerIdentity.customer_id)
        .where(
            and_(
                CustomerIdentity.phone == phone,
                CustomerIdentity.is_deleted == False,
                CustomerModel.is_deleted == False
            )
        )
    )
    identity = result.scalar_one_or_none()

    if not identity:
        return None

    return {
        "customer": await get_customer(db, identity.customer_id),
        "matched_identity": {
            "id": str(identity.id),
            "platform": identity.platform,
            "phone": identity.phone,
            "confidence": "high",
        }
    }


async def resolve_customer_by_email(
    db: AsyncSession,
    email: str
) -> Optional[dict]:
    """通过邮箱解析客户身份"""
    from app.db.models.customer import Customer as CustomerModel
    result = await db.execute(
        select(CustomerIdentity)
        .options(selectinload(CustomerIdentity.customer))
        .join(CustomerModel, CustomerModel.id == CustomerIdentity.customer_id)
        .where(
            and_(
                CustomerIdentity.email == email,
                CustomerIdentity.is_deleted == False,
                CustomerModel.is_deleted == False
            )
        )
    )
    identity = result.scalar_one_or_none()
    
    if not identity:
        return None
    
    return {
        "customer": await get_customer(db, identity.customer_id),
        "matched_identity": {
            "id": str(identity.id),
            "platform": identity.platform,
            "email": identity.email,
            "confidence": "high",
        }
    }


async def merge_customers(
    db: AsyncSession,
    source_customer_id: UUID,
    target_customer_id: UUID
) -> dict:
    """
    手动合并重复客户
    将 source_customer 的所有身份迁移到 target_customer
    """
    # 验证两个客户都存在
    source_result = await db.execute(
        select(Customer).where(Customer.id == source_customer_id, Customer.is_deleted == False)
    )
    source_customer = source_result.scalar_one_or_none()
    
    target_result = await db.execute(
        select(Customer).where(Customer.id == target_customer_id, Customer.is_deleted == False)
    )
    target_customer = target_result.scalar_one_or_none()
    
    if not source_customer or not target_customer:
        raise ValueError("客户不存在")
    
    if source_customer_id == target_customer_id:
        raise ValueError("不能合并同一个客户")
    
    # 迁移所有身份
    identities_result = await db.execute(
        select(CustomerIdentity).where(
            and_(
                CustomerIdentity.customer_id == source_customer_id,
                CustomerIdentity.is_deleted == False
            )
        )
    )
    identities = identities_result.scalars().all()
    
    migrated_count = 0
    for identity in identities:
        identity.customer_id = target_customer_id
        migrated_count += 1
    
    # 标记源客户为已删除
    source_customer.is_deleted = True
    source_customer.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    
    logger.info(f"Merged {migrated_count} identities from {source_customer_id} to {target_customer_id}")
    
    return {
        "source_customer_id": str(source_customer_id),
        "target_customer_id": str(target_customer_id),
        "migrated_identities": migrated_count,
        "merged_at": datetime.utcnow().isoformat(),
    }
