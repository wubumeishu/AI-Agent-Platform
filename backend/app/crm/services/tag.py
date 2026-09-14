"""Tag CRUD and association management service

基于 SQLAlchemy ORM
支持标签层级结构、批量关联、统计功能
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update
from sqlalchemy.orm import selectinload

from app.db.models.tag import Tag, tag_customer, tag_lead
from app.db.models.customer import Customer
from app.db.models.lead import Lead

logger = logging.getLogger(__name__)


# ---------------- Domain event publishing (workflow-CRM integration) ----------------
def _publish_customer_tag_changed(
    customer_id: UUID, tag_ids: List[UUID], operation: str
) -> None:
    """Queue a ``customer.tag_changed`` event.

    Called ONLY when a tag association actually changed (inserted/removed),
    so a no-op add/remove never fires workflows (idempotent termination).
    """
    try:
        from app.services.crm_events import get_crm_publisher

        pub = get_crm_publisher()
        pub.publish_nowait(
            pub.build(
                "customer.tag_changed",
                "customer",
                customer_id,
                {
                    "tag_ids": [str(t) for t in tag_ids],
                    "operation": operation,
                },
            )
        )
    except Exception:
        logger.debug("failed to queue customer.tag_changed event", exc_info=True)


def _publish_lead_tags_changed(lead_id: UUID, tag_ids: List[UUID], operation: str) -> None:
    """Queue a ``lead.tags_changed`` event (called only on real changes)."""
    try:
        from app.services.crm_events import get_crm_publisher

        pub = get_crm_publisher()
        pub.publish_nowait(
            pub.build(
                "lead.tags_changed",
                "lead",
                lead_id,
                {
                    "tag_ids": [str(t) for t in tag_ids],
                    "operation": operation,
                },
            )
        )
    except Exception:
        logger.debug("failed to queue lead.tags_changed event", exc_info=True)


# ==================== Tag CRUD ====================


async def get_tag(db: AsyncSession, tag_id: UUID) -> Optional[dict]:
    """获取单个标签详情（含层级和统计信息）"""
    result = await db.execute(
        select(Tag)
        .options(
            selectinload(Tag.children),
            selectinload(Tag.customers),
            selectinload(Tag.leads),
        )
        .where(Tag.id == tag_id, Tag.is_deleted == False)
    )
    tag = result.scalar_one_or_none()
    
    if not tag:
        return None
    
    return {
        "id": str(tag.id),
        "name": tag.name,
        "color": tag.color,
        "description": tag.description,
        "parent_id": str(tag.parent_id) if tag.parent_id else None,
        "usage_count": tag.usage_count,
        "children": [
            {
                "id": str(c.id),
                "name": c.name,
                "color": c.color,
            }
            for c in (tag.children or [])
        ],
        "customer_count": len(tag.customers) if tag.customers else 0,
        "lead_count": len(tag.leads) if tag.leads else 0,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


async def list_tags(
    db: AsyncSession,
    name: Optional[str] = None,
    parent_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 100,
) -> Dict[str, Any]:
    """列出标签列表（支持筛选、分页）"""
    query = select(Tag).where(Tag.is_deleted == False)
    
    if name:
        query = query.where(Tag.name.like(f"%{name}%"))
    
    if parent_id:
        query = query.where(Tag.parent_id == parent_id)
    else:
        # 默认只返回根标签
        query = query.where(Tag.parent_id.is_(None))
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # 排序和分页
    query = query.order_by(Tag.created_at.desc()).offset(skip).limit(limit)
    
    result = await db.execute(
        query
        .options(
            selectinload(Tag.children),
            selectinload(Tag.customers),
            selectinload(Tag.leads),
        )
    )
    tags = result.scalars().all()
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "data": [
            {
                "id": str(t.id),
                "name": t.name,
                "color": t.color,
                "description": t.description,
                "parent_id": str(t.parent_id) if t.parent_id else None,
                "usage_count": t.usage_count,
                "child_count": len(t.children) if t.children else 0,
                "customer_count": len(t.customers) if t.customers else 0,
                "lead_count": len(t.leads) if t.leads else 0,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tags
        ],
    }


async def create_tag(db: AsyncSession, tag_data: dict) -> dict:
    """创建标签"""
    # 验证父标签存在（如果指定了 parent_id）
    if tag_data.get("parent_id"):
        parent_result = await db.execute(
            select(Tag).where(Tag.id == tag_data["parent_id"], Tag.is_deleted == False)
        )
        if not parent_result.scalar_one_or_none():
            raise ValueError(f"父标签 {tag_data['parent_id']} 不存在")
    
    # 检查同层级下是否有重名
    name_query = select(Tag).where(
        and_(
            Tag.name == tag_data["name"],
            Tag.parent_id == tag_data.get("parent_id"),
            Tag.is_deleted == False,
        )
    )
    existing = await db.execute(name_query)
    if existing.scalar_one_or_none():
        raise ValueError(f"同层级下已存在同名标签: {tag_data['name']}")
    
    new_tag = Tag(
        name=tag_data["name"],
        color=tag_data.get("color"),
        description=tag_data.get("description"),
        parent_id=tag_data.get("parent_id"),
    )
    db.add(new_tag)
    await db.commit()
    await db.refresh(new_tag)
    
    logger.info(f"Created tag: {new_tag.id}, name={new_tag.name}")
    return await get_tag(db, new_tag.id)


async def update_tag(db: AsyncSession, tag_id: UUID, updates: dict) -> Optional[dict]:
    """更新标签"""
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.is_deleted == False)
    )
    tag = result.scalar_one_or_none()
    
    if not tag:
        return None
    
    # 不允许更新的字段
    locked_fields = ["id", "created_at", "is_deleted"]
    
    for key, value in updates.items():
        if key in locked_fields:
            continue
        if key == "parent_id" and value:
            # 规范化为 UUID（API 层传入的是 JSON 字符串，直接比较 str==UUID 恒为 False，
            # 会导致自身/循环校验静默失效）
            try:
                value = UUID(str(value))
            except (ValueError, TypeError):
                raise ValueError(f"无效的父标签 ID: {value}")
            # 验证父标签存在且不是自身
            if value == tag_id:
                raise ValueError("不能将自身设为父标签")
            parent_result = await db.execute(
                select(Tag).where(Tag.id == value, Tag.is_deleted == False)
            )
            if not parent_result.scalar_one_or_none():
                raise ValueError(f"父标签 {value} 不存在")
            # 检查是否会形成循环引用
            if await _would_cause_cycle(db, tag_id, value):
                raise ValueError("设置父标签会导致循环引用")
        setattr(tag, key, value)
    
    tag.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(tag)
    
    logger.info(f"Updated tag: {tag_id}")
    return await get_tag(db, tag_id)


async def delete_tag(db: AsyncSession, tag_id: UUID) -> bool:
    """删除标签（软删除）"""
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.is_deleted == False)
    )
    tag = result.scalar_one_or_none()
    
    if not tag:
        return False
    
    # 检查是否有子标签
    children_result = await db.execute(
        select(Tag).where(Tag.parent_id == tag_id, Tag.is_deleted == False)
    )
    children = children_result.scalars().all()
    
    if children:
        # 将子标签提升至当前层级
        for child in children:
            child.parent_id = tag.parent_id
        logger.info(f"Promoted {len(children)} child tags from deleted tag {tag_id}")
    
    tag.is_deleted = True
    await db.commit()
    
    logger.info(f"Deleted tag: {tag_id}")
    return True


async def _would_cause_cycle(db: AsyncSession, child_id: UUID, parent_id: UUID) -> bool:
    """检查设置父子关系是否会导致循环引用"""
    # 向上遍历父链，看是否能回到自己
    visited = set()
    current_id = parent_id
    while current_id:
        if current_id == child_id:
            return True
        if current_id in visited:
            break
        visited.add(current_id)
        
        result = await db.execute(
            select(Tag.parent_id)
            .where(Tag.id == current_id, Tag.is_deleted == False)
        )
        next_parent = result.scalar_one_or_none()
        if not next_parent:
            break
        current_id = next_parent
    
    return False


# ==================== Tag Associations ====================


async def add_tags_to_customer(
    db: AsyncSession,
    customer_id: UUID,
    tag_ids: List[UUID],
) -> Dict[str, Any]:
    """为 customerId 添加多个标签"""
    # 验证客户存在
    customer_result = await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False)
    )
    if not customer_result.scalar_one_or_none():
        raise ValueError(f"客户 {customer_id} 不存在")
    
    # 验证标签存在
    tags_result = await db.execute(
        select(Tag).where(Tag.id.in_(tag_ids), Tag.is_deleted == False)
    )
    tags = tags_result.scalars().all()
    existing_tag_ids = {str(t.id) for t in tags}
    
    if len(existing_tag_ids) != len(tag_ids):
        missing = set(str(tid) for tid in tag_ids) - existing_tag_ids
        raise ValueError(f"以下标签不存在: {', '.join(missing)}")
    
    # 批量插入关联
    inserted = 0
    for tag_id in tag_ids:
        # 检查是否已存在关联
        existing = await db.execute(
            select(tag_customer).where(
                and_(
                    tag_customer.c.tag_id == tag_id,
                    tag_customer.c.customer_id == customer_id,
                )
            )
        )
        if not existing.scalar_one_or_none():
            stmt = tag_customer.insert().values(
                tag_id=tag_id,
                customer_id=customer_id,
            )
            await db.execute(stmt)
            inserted += 1
    
    # 更新标签使用次数
    if inserted > 0:
        await db.execute(
            update(Tag)
            .where(Tag.id.in_(tag_ids))
            .values(usage_count=Tag.usage_count + 1)
        )
        await db.commit()
    
    logger.info(f"Added {inserted} tags to customer {customer_id}")
    if inserted > 0:
        _publish_customer_tag_changed(customer_id, tag_ids, "add")

    return {
        "customer_id": str(customer_id),
        "tag_ids": [str(tid) for tid in tag_ids],
        "inserted": inserted,
        "already_existed": len(tag_ids) - inserted,
    }


async def add_tags_to_lead(
    db: AsyncSession,
    lead_id: UUID,
    tag_ids: List[UUID],
) -> Dict[str, Any]:
    """为 leadId 添加多个标签"""
    # 验证 lead 存在
    lead_result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.is_deleted == False)
    )
    if not lead_result.scalar_one_or_none():
        raise ValueError(f"Lead {lead_id} 不存在")
    
    # 验证标签存在
    tags_result = await db.execute(
        select(Tag).where(Tag.id.in_(tag_ids), Tag.is_deleted == False)
    )
    tags = tags_result.scalars().all()
    existing_tag_ids = {str(t.id) for t in tags}
    
    if len(existing_tag_ids) != len(tag_ids):
        missing = set(str(tid) for tid in tag_ids) - existing_tag_ids
        raise ValueError(f"以下标签不存在: {', '.join(missing)}")
    
    # 批量插入关联
    inserted = 0
    for tag_id in tag_ids:
        existing = await db.execute(
            select(tag_lead).where(
                and_(
                    tag_lead.c.tag_id == tag_id,
                    tag_lead.c.lead_id == lead_id,
                )
            )
        )
        if not existing.scalar_one_or_none():
            stmt = tag_lead.insert().values(
                tag_id=tag_id,
                lead_id=lead_id,
            )
            await db.execute(stmt)
            inserted += 1
    
    # 更新标签使用次数
    if inserted > 0:
        await db.execute(
            update(Tag)
            .where(Tag.id.in_(tag_ids))
            .values(usage_count=Tag.usage_count + 1)
        )
        await db.commit()
    
    logger.info(f"Added {inserted} tags to lead {lead_id}")
    if inserted > 0:
        _publish_lead_tags_changed(lead_id, tag_ids, "add")

    return {
        "lead_id": str(lead_id),
        "tag_ids": [str(tid) for tid in tag_ids],
        "inserted": inserted,
        "already_existed": len(tag_ids) - inserted,
    }


async def remove_tag_from_customer(
    db: AsyncSession,
    customer_id: UUID,
    tag_id: UUID,
) -> bool:
    """从客户移除单个标签"""
    result = await db.execute(
        select(tag_customer).where(
            and_(
                tag_customer.c.tag_id == tag_id,
                tag_customer.c.customer_id == customer_id,
            )
        )
    )
    if not result.scalar_one_or_none():
        return False
    
    await db.execute(
        tag_customer.delete().where(
            and_(
                tag_customer.c.tag_id == tag_id,
                tag_customer.c.customer_id == customer_id,
            )
        )
    )
    await db.commit()
    _publish_customer_tag_changed(customer_id, [tag_id], "remove")
    return True


async def remove_tag_from_lead(
    db: AsyncSession,
    lead_id: UUID,
    tag_id: UUID,
) -> bool:
    """从 lead 移除单个标签"""
    result = await db.execute(
        select(tag_lead).where(
            and_(
                tag_lead.c.tag_id == tag_id,
                tag_lead.c.lead_id == lead_id,
            )
        )
    )
    if not result.scalar_one_or_none():
        return False
    
    await db.execute(
        tag_lead.delete().where(
            and_(
                tag_lead.c.tag_id == tag_id,
                tag_lead.c.lead_id == lead_id,
            )
        )
    )
    await db.commit()
    _publish_lead_tags_changed(lead_id, [tag_id], "remove")
    return True


# ==================== Tag Statistics ====================


async def get_tag_statistics(db: AsyncSession) -> Dict[str, Any]:
    """获取标签统计信息"""
    # 总体统计
    total_result = await db.execute(
        select(func.count()).where(Tag.is_deleted == False)
    )
    total_tags = total_result.scalar() or 0
    
    # 根标签数量
    root_result = await db.execute(
        select(func.count()).where(
            and_(
                Tag.is_deleted == False,
                Tag.parent_id.is_(None),
            )
        )
    )
    root_tags = root_result.scalar() or 0
    
    # 子标签数量
    child_tags = total_tags - root_tags
    
    # 按使用次数排序的前10个标签
    top_tags_result = await db.execute(
        select(Tag)
        .where(Tag.is_deleted == False)
        .order_by(Tag.usage_count.desc())
        .limit(10)
    )
    top_tags = top_tags_result.scalars().all()
    
    # 最近创建的标签
    recent_result = await db.execute(
        select(Tag)
        .where(Tag.is_deleted == False)
        .order_by(Tag.created_at.desc())
        .limit(10)
    )
    recent_tags = recent_result.scalars().all()
    
    return {
        "total_tags": total_tags,
        "root_tags": root_tags,
        "child_tags": child_tags,
        "top_tags": [
            {
                "id": str(t.id),
                "name": t.name,
                "usage_count": t.usage_count,
            }
            for t in top_tags
        ],
        "recent_tags": [
            {
                "id": str(t.id),
                "name": t.name,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in recent_tags
        ],
    }
