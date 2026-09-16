"""
Customer 360 Service: Aggregates all customer-related data
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc, or_

from app.db.models.customer import Customer
from app.db.models.lead import Lead
from app.db.models.tag import Tag, tag_customer
from app.db.models.lifecycle import LifecycleStage
from app.db.models.conversation import Conversation, Message
from app.db.models.memory import Memory, ActivityLog

logger = logging.getLogger(__name__)


async def get_customer_360(db: AsyncSession, customer_id: UUID) -> Optional[Dict[str, Any]]:
    """获取 Customer 360 完整数据"""
    from app.db.models.conversation import Message as MessageModel
    
    # 1. 查询客户基本信息
    customer_result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.is_deleted == False
        )
    )
    customer = customer_result.scalar_one_or_none()
    if not customer:
        return None

    # 2. 查询客户标签
    tags_result = await db.execute(
        select(Tag).join(
            tag_customer, Tag.id == tag_customer.c.tag_id
        ).where(
            tag_customer.c.customer_id == customer_id,
            Tag.is_deleted == False
        )
    )
    tags = tags_result.scalars().all()

    # 3. 查询客户关联的线索
    leads_result = await db.execute(
        select(Lead).where(
            Lead.customer_id == customer_id,
            Lead.is_deleted == False
        ).order_by(Lead.created_at.desc())
    )
    leads = leads_result.scalars().all()

    # 4. 查询对话历史
    conversations_result = await db.execute(
        select(Conversation).where(
            Conversation.customer_id == customer_id,
            Conversation.is_deleted == False
        ).order_by(Conversation.created_at.desc()).limit(50)
    )
    conversations = conversations_result.scalars().all()

    # 5. 查询记忆摘要
    memories_result = await db.execute(
        select(Memory).where(
            Memory.customer_id == customer_id,
            Memory.is_deleted == False
        ).order_by(Memory.importance.desc(), Memory.created_at.desc()).limit(20)
    )
    memories = memories_result.scalars().all()

    # 6. 查询活动记录
    activities_result = await db.execute(
        select(ActivityLog).where(
            ActivityLog.customer_id == customer_id
        ).order_by(ActivityLog.created_at.desc()).limit(50)
    )
    activities = activities_result.scalars().all()

    # 7. 查询生命周期阶段
    lifecycle_stages_result = await db.execute(
        select(LifecycleStage).where(LifecycleStage.is_deleted == False)
    )
    lifecycle_stages = {s.code: s for s in lifecycle_stages_result.scalars().all()}

    # 8. 统计每个对话的消息数量
    conversation_ids = [c.id for c in conversations]
    message_counts = {}
    if conversation_ids:
        messages_result = await db.execute(
            select(MessageModel.conversation_id, func.count().label('msg_count'))
            .where(
                MessageModel.conversation_id.in_(conversation_ids),
                MessageModel.is_deleted == False
            )
            .group_by(MessageModel.conversation_id)
        )
        for row in messages_result.all():
            message_counts[str(row.conversation_id)] = row.msg_count

    # 构建响应数据
    customer_data = {
        "id": str(customer.id),
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "company": customer.company,
        "avatar_url": customer.avatar_url,
        "extra_info": customer.extra_info or {},
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
        "updated_at": customer.updated_at.isoformat() if customer.updated_at else None,
        "tags": [
            {
                "id": str(t.id),
                "name": t.name,
                "color": t.color,
                "description": t.description,
            }
            for t in tags
        ],
        "leads": [
            {
                "id": str(l.id),
                "status": l.status,
                "lifecycle_stage_code": l.lifecycle_stage_code,
                "intent_score": l.intent_score,
                "source_type": l.source_type,
                "tags": l.tags or [],
                "notes": l.notes,
                "created_at": l.created_at.isoformat() if l.created_at else None,
                "lifecycle_stage": lifecycle_stages.get(l.lifecycle_stage_code, {}).name if l.lifecycle_stage_code else None,
            }
            for l in leads
        ],
        "conversations": [
            {
                "id": str(c.id),
                "channel": c.channel,
                "subject": c.subject,
                "status": c.status,
                "summary": c.summary,
                "sentiment": c.sentiment,
                "tags": c.tags or [],
                "message_count": message_counts.get(str(c.id), 0),
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in conversations
        ],
        "memories": [
            {
                "id": str(m.id),
                "category": m.category,
                "content": m.content,
                "importance": m.importance,
                "source": m.source,
                "tags": m.tags or [],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ],
        "activities": [
            {
                "id": str(a.id),
                "activity_type": a.activity_type,
                "title": a.title,
                "description": a.description,
                "related_lead_id": str(a.related_lead_id) if a.related_lead_id else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities
        ],
        "next_action": _suggest_next_action(customer, leads, conversations, memories),
    }

    return customer_data


def _suggest_next_action(customer: Customer, leads: List[Lead], conversations: List[Conversation], memories: List[Memory]) -> Dict[str, Any]:
    """基于客户状态建议下一步行动"""
    suggestions = []

    # 检查是否有高意向线索但未转化
    high_intent_leads = [l for l in leads if l.lifecycle_stage_code in ["high_intent", "商机"] and l.status != "closed"]
    if high_intent_leads:
        suggestions.append({
            "type": "follow_up",
            "priority": "high",
            "message": f"有 {len(high_intent_leads)} 个高意向线索需要跟进",
            "action": "schedule_followup",
        })

    # 检查最近对话是否需要回复
    from datetime import timedelta
    recent_conversations = [c for c in conversations if c.status == "active" and c.created_at and
                           datetime.now(timezone.utc) - c.created_at.replace(tzinfo=None) < timedelta(days=7)]
    if recent_conversations:
        suggestions.append({
            "type": "response",
            "priority": "medium",
            "message": f"有 {len(recent_conversations)} 条未回复的对话",
            "action": "reply_conversation",
        })

    # 检查是否有重要记忆需要关注
    important_memories = [m for m in memories if m.importance >= 8]
    if important_memories:
        suggestions.append({
            "type": "reminder",
            "priority": "low",
            "message": f"有 {len(important_memories)} 条重要记忆需要关注",
            "action": "review_memories",
        })

    if not suggestions:
        suggestions.append({
            "type": "general",
            "priority": "low",
            "message": "客户状态稳定，无需紧急操作",
            "action": "none",
        })

    return {
        "suggestions": suggestions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_customer_conversations(db: AsyncSession, customer_id: UUID, skip: int = 0, limit: int = 20) -> Dict[str, Any]:
    """获取客户对话历史"""
    total_result = await db.execute(
        select(func.count()).where(
            and_(
                Conversation.customer_id == customer_id,
                Conversation.is_deleted == False
            )
        )
    )
    total = total_result.scalar() or 0
    
    conversations_result = await db.execute(
        select(Conversation).where(
            Conversation.customer_id == customer_id,
            Conversation.is_deleted == False
        ).order_by(Conversation.created_at.desc()).offset(skip).limit(limit)
    )
    conversations = conversations_result.scalars().all()
    
    return {
        "total": total,
        "conversations": [
            {
                "id": str(c.id),
                "channel": c.channel,
                "subject": c.subject,
                "status": c.status,
                "summary": c.summary,
                "sentiment": c.sentiment,
                "tags": c.tags or [],
                "message_count": len([m for m in conversations if hasattr(m, 'id')]),
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in conversations
        ],
        "skip": skip,
        "limit": limit,
    }


async def get_customer_memories(db: AsyncSession, customer_id: UUID, category: Optional[str] = None, skip: int = 0, limit: int = 20) -> Dict[str, Any]:
    """获取客户记忆摘要"""
    query = select(Memory).where(
        Memory.customer_id == customer_id,
        Memory.is_deleted == False
    )

    if category:
        query = query.where(Memory.category == category)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    query = query.order_by(Memory.importance.desc(), Memory.created_at.desc())
    query = query.offset(skip).limit(limit)

    memories_result = await db.execute(query)
    memories = memories_result.scalars().all()

    return {
        "total": total,
        "memories": [
            {
                "id": str(m.id),
                "category": m.category,
                "content": m.content,
                "importance": m.importance,
                "source": m.source,
                "tags": m.tags or [],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ],
        "skip": skip,
        "limit": limit,
    }


async def get_customer_activities(db: AsyncSession, customer_id: UUID, activity_type: Optional[str] = None, skip: int = 0, limit: int = 20) -> Dict[str, Any]:
    """获取客户活动记录"""
    query = select(ActivityLog).where(
        ActivityLog.customer_id == customer_id
    )

    if activity_type:
        query = query.where(ActivityLog.activity_type == activity_type)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    query = query.order_by(ActivityLog.created_at.desc())
    query = query.offset(skip).limit(limit)

    activities_result = await db.execute(query)
    activities = activities_result.scalars().all()

    return {
        "total": total,
        "activities": [
            {
                "id": str(a.id),
                "activity_type": a.activity_type,
                "title": a.title,
                "description": a.description,
                "related_lead_id": str(a.related_lead_id) if a.related_lead_id else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities
        ],
        "skip": skip,
        "limit": limit,
    }


async def add_activity(db: AsyncSession, customer_id: UUID, activity_type: str, title: str, description: Optional[str] = None, related_lead_id: Optional[UUID] = None, metadata: Optional[dict] = None) -> Dict[str, Any]:
    """添加活动记录"""
    activity = ActivityLog(
        customer_id=customer_id,
        activity_type=activity_type,
        title=title,
        description=description,
        related_lead_id=related_lead_id,
        metadata_=metadata or {},
    )
    db.add(activity)
    await db.commit()
    await db.refresh(activity)
    
    return {
        "id": str(activity.id),
        "activity_type": activity.activity_type,
        "title": activity.title,
        "description": activity.description,
        "related_lead_id": str(activity.related_lead_id) if activity.related_lead_id else None,
        "created_at": activity.created_at.isoformat() if activity.created_at else None,
    }
