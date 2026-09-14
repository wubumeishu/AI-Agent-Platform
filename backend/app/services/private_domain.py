"""
Private Domain Services: Private Channel, Nurture Plan, Content Library,
Follow-up Task, Customer Segment, Deal Pipeline
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete
from sqlalchemy.exc import IntegrityError

from app.security.jwt_auth import AccountOwnershipError

from app.db.models.private_domain import (
    PrivateChannel,
    NurturePlan,
    ContentItem,
    FollowUpTask,
    CustomerSegment,
    DealPipeline,
    DealStage,
    DealItem,
    DealItemStatus,
    DealStageStatus,
)
from app.schemas.private_domain import (
    PrivateChannelCreate,
    PrivateChannelUpdate,
    NurturePlanCreate,
    NurturePlanUpdate,
    ContentItemCreate,
    ContentItemUpdate,
    FollowUpTaskCreate,
    FollowUpTaskUpdate,
    CustomerSegmentCreate,
    CustomerSegmentUpdate,
    DealPipelineCreate,
    DealPipelineUpdate,
    DealStageCreate,
    DealStageUpdate,
    DealItemCreate,
    DealItemUpdate,
)


def _enforce_ownership(resource: Any, resource_type: str, account_id: Optional[UUID]) -> None:
    """F-4: enforce per-account ownership on an id-scoped service operation.

    When the router passes the caller's bound ``account_id``, the resource must
    belong to that account or :class:`AccountOwnershipError` is raised (mapped
    to HTTP 403). When ``account_id`` is ``None`` (legacy / internal callers and
    the existing unit-test suite) the check is a no-op, so existing behaviour
    is preserved. This deliberately adds no extra DB query — it compares the
    already-loaded resource, keeping call-count mocks green.
    """
    if account_id is None:
        return
    owner = getattr(resource, "account_id", None)
    if owner is None:
        # Some child resources (deal_stage, segment_member) derive ownership
        # from a parent; if the resource carries no direct account_id the
        # caller is expected to have validated the parent scope already.
        return
    if UUID(str(owner)) != UUID(str(account_id)):
        raise AccountOwnershipError(resource_type, account_id)


# ========== PrivateChannel Service ==========

async def get_private_channels(
    db: AsyncSession,
    account_id: UUID,
    page: int = 1,
    page_size: int = 20,
    channel_type: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Get paginated list of private channels"""
    query = select(PrivateChannel).where(
        PrivateChannel.account_id == account_id,
        PrivateChannel.is_deleted == False
    )
    
    if channel_type:
        query = query.where(PrivateChannel.channel_type == channel_type)
    if status:
        query = query.where(PrivateChannel.status == status)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate
    query = query.order_by(PrivateChannel.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    channels = result.scalars().all()
    
    return {
        "items": [
            {
                "id": ch.id,
                "account_id": ch.account_id,
                "platform_id": ch.platform_id,
                "channel_type": ch.channel_type,
                "name": ch.name,
                "description": ch.description,
                "contact_info": ch.contact_info,
                "avatar_url": ch.avatar_url,
                "status": ch.status,
                "connection_status": ch.connection_status,
                "last_connection": ch.last_connection,
                "contact_count": ch.contact_count,
                "message_count": ch.message_count,
                "tags": ch.tags,
                "extra_config": ch.extra_config,
                "created_at": ch.created_at,
                "updated_at": ch.updated_at,
            }
            for ch in channels
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_private_channel(db: AsyncSession, channel_id: UUID, account_id: UUID) -> Optional[Dict[str, Any]]:
    """Get a single private channel by ID"""
    result = await db.execute(
        select(PrivateChannel).where(
            PrivateChannel.id == channel_id,
            PrivateChannel.account_id == account_id,
            PrivateChannel.is_deleted == False
        )
    )
    channel = result.scalar_one_or_none()
    
    if not channel:
        return None
    
    return {
        "id": channel.id,
        "account_id": channel.account_id,
        "platform_id": channel.platform_id,
        "channel_type": channel.channel_type,
        "name": channel.name,
        "description": channel.description,
        "contact_info": channel.contact_info,
        "avatar_url": channel.avatar_url,
        "status": channel.status,
        "connection_status": channel.connection_status,
        "last_connection": channel.last_connection,
        "contact_count": channel.contact_count,
        "message_count": channel.message_count,
        "tags": channel.tags,
        "extra_config": channel.extra_config,
        "created_at": channel.created_at,
        "updated_at": channel.updated_at,
    }


async def create_private_channel(db: AsyncSession, data: PrivateChannelCreate) -> Dict[str, Any]:
    """Create a new private channel"""
    channel = PrivateChannel(
        account_id=data.account_id,
        platform_id=data.platform_id,
        channel_type=data.channel_type,
        name=data.name,
        description=data.description,
        contact_info=data.contact_info or {},
        avatar_url=data.avatar_url,
        tags=data.tags or [],
        extra_config=data.extra_config or {},
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    
    return {
        "id": channel.id,
        "account_id": channel.account_id,
        "platform_id": channel.platform_id,
        "channel_type": channel.channel_type,
        "name": channel.name,
        "description": channel.description,
        "contact_info": channel.contact_info,
        "avatar_url": channel.avatar_url,
        "status": channel.status,
        "connection_status": channel.connection_status,
        "last_connection": channel.last_connection,
        "contact_count": channel.contact_count,
        "message_count": channel.message_count,
        "tags": channel.tags,
        "extra_config": channel.extra_config,
        "created_at": channel.created_at,
        "updated_at": channel.updated_at,
    }


async def update_private_channel(db: AsyncSession, channel_id: UUID, account_id: UUID, data: PrivateChannelUpdate) -> Optional[Dict[str, Any]]:
    """Update a private channel"""
    result = await db.execute(
        select(PrivateChannel).where(
            PrivateChannel.id == channel_id,
            PrivateChannel.account_id == account_id,
            PrivateChannel.is_deleted == False
        )
    )
    channel = result.scalar_one_or_none()
    
    if not channel:
        return None
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(channel, field, value)
    
    channel.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(channel)
    
    return {
        "id": channel.id,
        "account_id": channel.account_id,
        "platform_id": channel.platform_id,
        "channel_type": channel.channel_type,
        "name": channel.name,
        "description": channel.description,
        "contact_info": channel.contact_info,
        "avatar_url": channel.avatar_url,
        "status": channel.status,
        "connection_status": channel.connection_status,
        "last_connection": channel.last_connection,
        "contact_count": channel.contact_count,
        "message_count": channel.message_count,
        "tags": channel.tags,
        "extra_config": channel.extra_config,
        "created_at": channel.created_at,
        "updated_at": channel.updated_at,
    }


async def delete_private_channel(db: AsyncSession, channel_id: UUID, account_id: UUID) -> bool:
    """Soft delete a private channel"""
    result = await db.execute(
        select(PrivateChannel).where(
            PrivateChannel.id == channel_id,
            PrivateChannel.account_id == account_id,
            PrivateChannel.is_deleted == False
        )
    )
    channel = result.scalar_one_or_none()
    
    if not channel:
        return False
    
    channel.is_deleted = True
    channel.updated_at = datetime.utcnow()
    await db.commit()
    return True


# ========== NurturePlan Service ==========

async def get_nurture_plans(
    db: AsyncSession,
    channel_id: Optional[UUID] = None,
    account_id: Optional[UUID] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """Get paginated list of nurture plans"""
    query = select(NurturePlan).where(NurturePlan.is_deleted == False)
    
    if channel_id:
        query = query.where(NurturePlan.channel_id == channel_id)
    if account_id:
        query = query.where(NurturePlan.account_id == account_id)
    if status:
        query = query.where(NurturePlan.status == status)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate
    query = query.order_by(NurturePlan.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    plans = result.scalars().all()
    
    return {
        "items": [
            {
                "id": p.id,
                "channel_id": p.channel_id,
                "account_id": p.account_id,
                "name": p.name,
                "description": p.description,
                "status": p.status,
                "schedule_type": p.schedule_type,
                "schedule_config": p.schedule_config,
                # Legacy sequence_steps JSON column is retired (Contract B);
                # step definitions live in the nurture_plan_item table.
                "trigger_conditions": p.trigger_conditions,
                "target_segment_id": p.target_segment_id,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p in plans
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def create_nurture_plan(db: AsyncSession, data: NurturePlanCreate) -> Dict[str, Any]:
    """Create a new nurture plan.

    Delegates to the enhanced service: the legacy ``sequence_steps`` payload
    is reconciled into ``nurture_plan_item`` rows (single source of truth,
    ruling t_1814d03d / t_4b55abe8 Contract B); the legacy JSON column is
    retired ([]).
    """
    from app.services.nurture_plan_service import (
        create_nurture_plan as create_nurture_plan_enhanced,
    )

    return await create_nurture_plan_enhanced(db, data)


async def update_nurture_plan(db: AsyncSession, plan_id: UUID, data: NurturePlanUpdate, account_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
    """Update a nurture plan.

    Delegates to the enhanced service: a legacy ``sequence_steps`` payload
    reconciles the ``nurture_plan_item`` rows (single source of truth,
    ruling t_1814d03d / t_4b55abe8 Contract B); the legacy JSON column is
    retired.

    F-4: when ``account_id`` is supplied (the authenticated caller's account),
    the plan must belong to it or :class:`AccountOwnershipError` (-> 403) is
    raised. A no-op for internal callers that pass ``None``.
    """
    from app.services.nurture_plan_service import (
        update_nurture_plan as update_nurture_plan_enhanced,
    )

    if account_id is not None:
        result = await db.execute(
            select(NurturePlan).where(NurturePlan.id == plan_id, NurturePlan.is_deleted == False)
        )
        _enforce_ownership(result.scalar_one_or_none(), "nurture_plan", account_id)

    return await update_nurture_plan_enhanced(db, plan_id, data, account_id=account_id)


async def delete_nurture_plan(db: AsyncSession, plan_id: UUID, account_id: Optional[UUID] = None) -> bool:
    """Soft delete a nurture plan.

    F-4: when ``account_id`` is supplied the plan must belong to it.
    """
    result = await db.execute(
        select(NurturePlan).where(NurturePlan.id == plan_id, NurturePlan.is_deleted == False)
    )
    plan = result.scalar_one_or_none()
    
    if not plan:
        return False

    _enforce_ownership(plan, "nurture_plan", account_id)

    plan.is_deleted = True
    plan.updated_at = datetime.utcnow()
    await db.commit()
    return True


# ========== ContentItem Service ==========

async def get_content_items(
    db: AsyncSession,
    account_id: UUID,
    channel_id: Optional[UUID] = None,
    content_type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """Get paginated list of content items"""
    query = select(ContentItem).where(
        ContentItem.account_id == account_id,
        ContentItem.is_deleted == False
    )
    
    if channel_id:
        query = query.where(ContentItem.channel_id == channel_id)
    if content_type:
        query = query.where(ContentItem.content_type == content_type)
    if status:
        query = query.where(ContentItem.status == status)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate
    query = query.order_by(ContentItem.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "items": [
            {
                "id": item.id,
                "account_id": item.account_id,
                "channel_id": item.channel_id,
                "content_type": item.content_type,
                "title": item.title,
                "summary": item.summary,
                "body": item.body,
                "media_urls": item.media_urls,
                "tags": item.tags,
                "category": item.category,
                "status": item.status,
                "version": item.version,
                "usage_count": item.usage_count,
                "last_used_at": item.last_used_at,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def create_content_item(db: AsyncSession, data: ContentItemCreate) -> Dict[str, Any]:
    """Create a new content item"""
    item = ContentItem(
        account_id=data.account_id,
        channel_id=data.channel_id,
        content_type=data.content_type,
        title=data.title,
        summary=data.summary,
        body=data.body,
        media_urls=data.media_urls or [],
        tags=data.tags or [],
        category=data.category,
        usage_count=0,
        last_used_at=None,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return {
        "id": item.id,
        "account_id": item.account_id,
        "channel_id": item.channel_id,
        "content_type": item.content_type,
        "title": item.title,
        "summary": item.summary,
        "body": item.body,
        "media_urls": item.media_urls,
        "tags": item.tags,
        "category": item.category,
        "status": item.status,
        "version": item.version,
        "usage_count": item.usage_count,
        "last_used_at": item.last_used_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def update_content_item(db: AsyncSession, item_id: UUID, data: ContentItemUpdate, account_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
    """Update a content item. F-4: ownership-checked when ``account_id`` is given."""
    result = await db.execute(
        select(ContentItem).where(ContentItem.id == item_id, ContentItem.is_deleted == False)
    )
    item = result.scalar_one_or_none()
    
    if not item:
        return None
    
    _enforce_ownership(item, "content_item", account_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    
    item.updated_at = datetime.utcnow()
    item.version += 1
    await db.commit()
    await db.refresh(item)
    
    return {
        "id": item.id,
        "account_id": item.account_id,
        "channel_id": item.channel_id,
        "content_type": item.content_type,
        "title": item.title,
        "summary": item.summary,
        "body": item.body,
        "media_urls": item.media_urls,
        "tags": item.tags,
        "category": item.category,
        "status": item.status,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def delete_content_item(db: AsyncSession, item_id: UUID, account_id: Optional[UUID] = None) -> bool:
    """Soft delete a content item. F-4: ownership-checked when ``account_id`` is given."""
    result = await db.execute(
        select(ContentItem).where(ContentItem.id == item_id, ContentItem.is_deleted == False)
    )
    item = result.scalar_one_or_none()
    
    if not item:
        return False
    
    _enforce_ownership(item, "content_item", account_id)

    item.is_deleted = True
    item.status = "deleted"
    item.updated_at = datetime.utcnow()
    await db.commit()
    return True


# ========== FollowUpTask Service ==========

async def get_follow_up_tasks(
    db: AsyncSession,
    account_id: UUID,
    customer_id: Optional[UUID] = None,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """Get paginated list of follow-up tasks"""
    query = select(FollowUpTask).where(
        FollowUpTask.account_id == account_id,
        FollowUpTask.is_deleted == False
    )
    
    if customer_id:
        query = query.where(FollowUpTask.customer_id == customer_id)
    if status:
        query = query.where(FollowUpTask.status == status)
    if priority is not None:
        query = query.where(FollowUpTask.priority >= priority)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate
    query = query.order_by(FollowUpTask.due_date.asc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    tasks = result.scalars().all()
    
    return {
        "items": [
            {
                "id": t.id,
                "account_id": t.account_id,
                "customer_id": t.customer_id,
                "lead_id": t.lead_id,
                "task_type": t.task_type,
                "title": t.title,
                "description": t.description,
                "status": t.status,
                "scheduled_at": t.scheduled_at,
                "due_date": t.due_date,
                "priority": t.priority,
                "reminder_config": t.reminder_config,
                "result": t.result,
                "notes": t.notes,
                "created_by": t.created_by,
                "assigned_to": t.assigned_to,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in tasks
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def create_follow_up_task(db: AsyncSession, data: FollowUpTaskCreate) -> Dict[str, Any]:
    """Create a new follow-up task"""
    task = FollowUpTask(
        account_id=data.account_id,
        customer_id=data.customer_id,
        lead_id=data.lead_id,
        task_type=data.task_type,
        title=data.title,
        description=data.description,
        status=data.status or "pending",
        scheduled_at=data.scheduled_at,
        due_date=data.due_date,
        priority=data.priority,
        reminder_config=data.reminder_config or {},
        created_by=data.assigned_to,
        assigned_to=data.assigned_to,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    
    return {
        "id": task.id,
        "account_id": task.account_id,
        "customer_id": task.customer_id,
        "lead_id": task.lead_id,
        "task_type": task.task_type,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "scheduled_at": task.scheduled_at,
        "due_date": task.due_date,
        "priority": task.priority,
        "reminder_config": task.reminder_config,
        "result": task.result,
        "notes": task.notes,
        "created_by": task.created_by,
        "assigned_to": task.assigned_to,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


async def update_follow_up_task(db: AsyncSession, task_id: UUID, data: FollowUpTaskUpdate, account_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
    """Update a follow-up task. F-4: ownership-checked when ``account_id`` is given."""
    result = await db.execute(
        select(FollowUpTask).where(FollowUpTask.id == task_id, FollowUpTask.is_deleted == False)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        return None
    
    _enforce_ownership(task, "follow_up_task", account_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)
    
    task.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)
    
    return {
        "id": task.id,
        "account_id": task.account_id,
        "customer_id": task.customer_id,
        "lead_id": task.lead_id,
        "task_type": task.task_type,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "scheduled_at": task.scheduled_at,
        "due_date": task.due_date,
        "priority": task.priority,
        "reminder_config": task.reminder_config,
        "result": task.result,
        "notes": task.notes,
        "created_by": task.created_by,
        "assigned_to": task.assigned_to,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


async def delete_follow_up_task(db: AsyncSession, task_id: UUID, account_id: Optional[UUID] = None) -> bool:
    """Soft delete a follow-up task. F-4: ownership-checked when ``account_id`` is given."""
    result = await db.execute(
        select(FollowUpTask).where(FollowUpTask.id == task_id, FollowUpTask.is_deleted == False)
    )
    task = result.scalar_one_or_none()

    if not task:
        return False

    _enforce_ownership(task, "follow_up_task", account_id)

    task.is_deleted = True
    task.updated_at = datetime.utcnow()
    await db.commit()
    return True


async def transition_task_status(
    db: AsyncSession,
    task_id: UUID,
    new_status: str,
    account_id: Optional[UUID] = None,
) -> Optional[Dict[str, Any]]:
    """Transition follow-up task to a new status with validation"""
    result = await db.execute(
        select(FollowUpTask).where(FollowUpTask.id == task_id, FollowUpTask.is_deleted == False)
    )
    task = result.scalar_one_or_none()

    if not task:
        return None

    # F-4: cross-account ownership is a 403 (mapped from AccountOwnershipError),
    # not a 404 / ValueError — an unknown status transition stays a ValueError.
    _enforce_ownership(task, "follow_up_task", account_id)

    # Validate status transition
    valid_transitions = {
        "pending": ["in_progress", "cancelled"],
        "in_progress": ["completed", "cancelled"],
        "completed": [],
        "cancelled": [],
        "overdue": ["completed"],
    }

    current_status = task.status
    allowed_transitions = valid_transitions.get(current_status, [])

    if new_status not in allowed_transitions:
        raise ValueError(
            f"Invalid status transition from '{current_status}' to '{new_status}'. "
            f"Allowed transitions: {allowed_transitions}"
        )

    task.status = new_status
    task.updated_at = datetime.utcnow()

    # If completing, record result timestamp
    if new_status == "completed":
        if task.result is None:
            task.result = {}
        task.result["completed_at"] = datetime.utcnow().isoformat()

    await db.commit()
    await db.refresh(task)

    return {
        "id": task.id,
        "account_id": task.account_id,
        "customer_id": task.customer_id,
        "lead_id": task.lead_id,
        "task_type": task.task_type,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "scheduled_at": task.scheduled_at,
        "due_date": task.due_date,
        "priority": task.priority,
        "reminder_config": task.reminder_config,
        "result": task.result,
        "notes": task.notes,
        "created_by": task.created_by,
        "assigned_to": task.assigned_to,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


async def check_and_update_overdue_tasks(
    db: AsyncSession,
    account_id: UUID,
) -> Dict[str, Any]:
    """Check for overdue tasks and update their status"""
    now = datetime.utcnow()

    # Find pending or in_progress tasks that are past due date
    result = await db.execute(
        select(FollowUpTask).where(
            FollowUpTask.account_id == account_id,
            FollowUpTask.is_deleted == False,
            FollowUpTask.status.in_(["pending", "in_progress"]),
            FollowUpTask.due_date < now,
        )
    )
    overdue_tasks = result.scalars().all()

    updated_count = 0
    for task in overdue_tasks:
        task.status = "overdue"
        task.updated_at = now
        updated_count += 1

    if updated_count > 0:
        await db.commit()

    return {
        "checked_at": now.isoformat(),
        "overdue_tasks_found": updated_count,
        "account_id": account_id,
    }


async def get_upcoming_reminders(
    db: AsyncSession,
    account_id: UUID,
    hours_ahead: int = 24,
) -> List[Dict[str, Any]]:
    """Get tasks that need reminders within the specified hours"""
    now = datetime.utcnow()
    reminder_window = now + __import__("datetime").timedelta(hours=hours_ahead)

    result = await db.execute(
        select(FollowUpTask).where(
            FollowUpTask.account_id == account_id,
            FollowUpTask.is_deleted == False,
            FollowUpTask.status.in_(["pending", "in_progress"]),
            FollowUpTask.due_date >= now,
            FollowUpTask.due_date <= reminder_window,
        ).order_by(FollowUpTask.due_date.asc())
    )
    tasks = result.scalars().all()

    return [
        {
            "id": t.id,
            "title": t.title,
            "due_date": t.due_date,
            "status": t.status,
            "priority": t.priority,
            "hours_until_due": max(0, round((t.due_date - now).total_seconds() / 3600, 1)),
        }
        for t in tasks
    ]


async def get_follow_up_task_stats(
    db: AsyncSession,
    account_id: UUID,
) -> Dict[str, Any]:
    """Get statistics for follow-up tasks"""
    # Total counts by status
    status_counts = {}
    for status in ["pending", "in_progress", "completed", "cancelled", "overdue"]:
        result = await db.execute(
            select(func.count()).where(
                FollowUpTask.account_id == account_id,
                FollowUpTask.is_deleted == False,
                FollowUpTask.status == status,
            )
        )
        status_counts[status] = result.scalar() or 0

    # Total count
    total = sum(status_counts.values())

    # Overdue count (pending/in_progress with past due_date)
    now = datetime.utcnow()
    overdue_result = await db.execute(
        select(func.count()).where(
            FollowUpTask.account_id == account_id,
            FollowUpTask.is_deleted == False,
            FollowUpTask.status.in_(["pending", "in_progress"]),
            FollowUpTask.due_date < now,
        )
    )
    overdue_count = overdue_result.scalar() or 0

    # Completion rate
    completed = status_counts.get("completed", 0)
    completion_rate = round((completed / total * 100), 1) if total > 0 else 0.0

    # Average priority of active tasks
    avg_priority_result = await db.execute(
        select(func.avg(FollowUpTask.priority)).where(
            FollowUpTask.account_id == account_id,
            FollowUpTask.is_deleted == False,
            FollowUpTask.status.in_(["pending", "in_progress", "overdue"]),
        )
    )
    avg_priority = round(avg_priority_result.scalar() or 0, 1)

    return {
        "account_id": account_id,
        "total_tasks": total,
        "status_counts": status_counts,
        "overdue_count": overdue_count,
        "completion_rate": completion_rate,
        "average_priority": avg_priority,
        "updated_at": now.isoformat(),
    }


# ========== CustomerSegment Service ==========

async def get_customer_segments(
    db: AsyncSession,
    account_id: UUID,
    segment_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """Get paginated list of customer segments"""
    query = select(CustomerSegment).where(
        CustomerSegment.account_id == account_id,
        CustomerSegment.is_deleted == False
    )
    
    if segment_type:
        query = query.where(CustomerSegment.segment_type == segment_type)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate
    query = query.order_by(CustomerSegment.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    segments = result.scalars().all()
    
    return {
        "items": [
            {
                "id": s.id,
                "account_id": s.account_id,
                "name": s.name,
                "description": s.description,
                "segment_type": s.segment_type,
                "filter_config": s.filter_config,
                "member_count": s.member_count,
                "last_synced_at": s.last_synced_at,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in segments
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def create_customer_segment(db: AsyncSession, data: CustomerSegmentCreate) -> Dict[str, Any]:
    """Create a new customer segment"""
    segment = CustomerSegment(
        account_id=data.account_id,
        name=data.name,
        description=data.description,
        segment_type=data.segment_type,
        filter_config=data.filter_config or {},
    )
    db.add(segment)
    await db.commit()
    await db.refresh(segment)
    
    return {
        "id": segment.id,
        "account_id": segment.account_id,
        "name": segment.name,
        "description": segment.description,
        "segment_type": segment.segment_type,
        "filter_config": segment.filter_config,
        "member_count": segment.member_count,
        "last_synced_at": segment.last_synced_at,
        "created_at": segment.created_at,
        "updated_at": segment.updated_at,
    }


async def update_customer_segment(db: AsyncSession, segment_id: UUID, data: CustomerSegmentUpdate, account_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
    """Update a customer segment. F-4: ownership-checked when ``account_id`` is given."""
    result = await db.execute(
        select(CustomerSegment).where(CustomerSegment.id == segment_id, CustomerSegment.is_deleted == False)
    )
    segment = result.scalar_one_or_none()
    
    if not segment:
        return None
    
    _enforce_ownership(segment, "customer_segment", account_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(segment, field, value)
    
    segment.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(segment)
    
    return {
        "id": segment.id,
        "account_id": segment.account_id,
        "name": segment.name,
        "description": segment.description,
        "segment_type": segment.segment_type,
        "filter_config": segment.filter_config,
        "member_count": segment.member_count,
        "last_synced_at": segment.last_synced_at,
        "created_at": segment.created_at,
        "updated_at": segment.updated_at,
    }


async def delete_customer_segment(db: AsyncSession, segment_id: UUID, account_id: Optional[UUID] = None) -> bool:
    """Soft delete a customer segment. F-4: ownership-checked when ``account_id`` is given."""
    result = await db.execute(
        select(CustomerSegment).where(CustomerSegment.id == segment_id, CustomerSegment.is_deleted == False)
    )
    segment = result.scalar_one_or_none()
    
    if not segment:
        return False
    
    _enforce_ownership(segment, "customer_segment", account_id)

    segment.is_deleted = True
    segment.updated_at = datetime.utcnow()
    await db.commit()
    return True


# ========== DealPipeline Service ==========

async def get_deal_pipelines(
    db: AsyncSession,
    account_id: UUID,
    pipeline_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """Get paginated list of deal pipelines"""
    query = select(DealPipeline).where(
        DealPipeline.account_id == account_id,
        DealPipeline.is_deleted == False
    )
    
    if pipeline_type:
        query = query.where(DealPipeline.pipeline_type == pipeline_type)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate
    query = query.order_by(DealPipeline.is_default.desc(), DealPipeline.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    pipelines = result.scalars().all()
    
    return {
        "items": [
            {
                "id": p.id,
                "account_id": p.account_id,
                "name": p.name,
                "description": p.description,
                "pipeline_type": p.pipeline_type,
                "is_default": p.is_default,
                "stages": p.stages,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p in pipelines
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _upsert_deal_stages(db: AsyncSession, pipeline: "Any", stages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Upsert deal_stage rows for a pipeline, keyed by `order`
    (architect decision t_1814d03d: deal_stage table is the single source of
    truth; deal_pipeline.stages JSON column is legacy-only and stays []).
    Caller owns the transaction (commit).
    """
    existing = (await db.execute(
        select(DealStage).where(
            DealStage.pipeline_id == pipeline.id,
            DealStage.is_deleted == False
        )
    )).scalars().all()
    by_order = {s.order: s for s in existing}

    result: List[Dict[str, Any]] = []
    for i, raw in enumerate(stages):
        name = str(raw.get("name", ""))[:100]
        probability = int(raw.get("probability", 0) or 0)
        config = raw.get("config") or {}
        if i in by_order:
            stage = by_order[i]
            stage.name = name
            stage.probability = probability
            stage.config = config
            stage.status = DealStageStatus.ACTIVE.value
            stage.updated_at = datetime.utcnow()
        else:
            stage = DealStage(
                pipeline_id=pipeline.id,
                name=name,
                order=i,
                probability=probability,
                config=config,
                status=DealStageStatus.ACTIVE.value,
            )
            db.add(stage)
            await db.flush()
            await db.refresh(stage)
        result.append(stage)

    # Soft-delete surplus stages no longer present in the desired list
    wanted_orders = set(range(len(stages)))
    for s in existing:
        if s.order not in wanted_orders:
            s.is_deleted = True
            s.updated_at = datetime.utcnow()
    await db.flush()

    return [
        {
            "id": s.id,
            "pipeline_id": s.pipeline_id,
            "name": s.name,
            "order": s.order,
            "probability": s.probability,
            "config": s.config,
            "status": s.status,
        }
        for s in result
    ]


async def create_deal_pipeline(db: AsyncSession, data: DealPipelineCreate) -> Dict[str, Any]:
    """Create a new deal pipeline.

    Stages are persisted as deal_stage table rows (single source of truth,
    architect decision t_1814d03d). The deal_pipeline.stages JSON column is
    legacy-only: it is kept as [] (read-only snapshot) and scheduled for
    removal after the ADR-011 migration.
    """
    pipeline = DealPipeline(
        account_id=data.account_id,
        name=data.name,
        description=data.description,
        pipeline_type=data.pipeline_type,
        is_default=data.is_default,
        stages=[],  # legacy JSON column kept as empty snapshot; see _upsert_deal_stages
    )
    db.add(pipeline)
    await db.flush()
    await db.refresh(pipeline)

    stages_payload = data.stages or []
    stage_rows = await _upsert_deal_stages(db, pipeline, stages_payload) if stages_payload else []
    await db.commit()

    return {
        "id": pipeline.id,
        "account_id": pipeline.account_id,
        "name": pipeline.name,
        "description": pipeline.description,
        "pipeline_type": pipeline.pipeline_type,
        "is_default": pipeline.is_default,
        "stages": stage_rows,
        "created_at": pipeline.created_at,
        "updated_at": pipeline.updated_at,
    }


async def update_deal_pipeline(db: AsyncSession, pipeline_id: UUID, data: DealPipelineUpdate, account_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
    """Update a deal pipeline.

    When `stages` is provided, deal_stage rows are reconciled (upsert by
    order, surplus rows soft-deleted) — deal_stage remains the single
    source of truth; the JSON column stays [].

    F-4: ownership-checked when ``account_id`` is given.
    """
    result = await db.execute(
        select(DealPipeline).where(DealPipeline.id == pipeline_id, DealPipeline.is_deleted == False)
    )
    pipeline = result.scalar_one_or_none()
    
    if not pipeline:
        return None
    
    _enforce_ownership(pipeline, "deal_pipeline", account_id)

    update_data = data.model_dump(exclude_unset=True)
    new_stages = update_data.pop("stages", None)
    for field, value in update_data.items():
        setattr(pipeline, field, value)
    
    stages_payload: List[Dict[str, Any]] = []
    if new_stages is not None:
        stages_payload = new_stages
        pipeline.stages = []  # keep legacy JSON column empty; rows are the source of truth
        await db.flush()
        stage_rows = await _upsert_deal_stages(db, pipeline, stages_payload)
    else:
        stage_rows = await get_deal_stages(db, pipeline.id)

    pipeline.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(pipeline)
    
    return {
        "id": pipeline.id,
        "account_id": pipeline.account_id,
        "name": pipeline.name,
        "description": pipeline.description,
        "pipeline_type": pipeline.pipeline_type,
        "is_default": pipeline.is_default,
        "stages": stage_rows,
        "created_at": pipeline.created_at,
        "updated_at": pipeline.updated_at,
    }


async def delete_deal_pipeline(db: AsyncSession, pipeline_id: UUID, account_id: Optional[UUID] = None) -> bool:
    """Soft delete a deal pipeline. F-4: ownership-checked when ``account_id`` is given."""
    result = await db.execute(
        select(DealPipeline).where(DealPipeline.id == pipeline_id, DealPipeline.is_deleted == False)
    )
    pipeline = result.scalar_one_or_none()
    
    if not pipeline:
        return False
    
    _enforce_ownership(pipeline, "deal_pipeline", account_id)

    pipeline.is_deleted = True
    pipeline.updated_at = datetime.utcnow()
    await db.commit()
    return True


# ========== DealStage Service ==========

async def get_deal_stages(db: AsyncSession, pipeline_id: UUID, account_id: Optional[UUID] = None) -> List[Dict[str, Any]]:
    """Get all stages for a pipeline.

    F-4: when ``account_id`` is given, the pipeline must belong to it (stage
    ownership is derived through the parent pipeline).
    """
    if account_id is not None:
        p_result = await db.execute(
            select(DealPipeline).where(
                DealPipeline.id == pipeline_id, DealPipeline.is_deleted == False
            )
        )
        _enforce_ownership(p_result.scalar_one_or_none(), "deal_pipeline", account_id)

    result = await db.execute(
        select(DealStage).where(
            DealStage.pipeline_id == pipeline_id,
            DealStage.is_deleted == False
        ).order_by(DealStage.order.asc())
    )
    stages = result.scalars().all()
    
    return [
        {
            "id": s.id,
            "pipeline_id": s.pipeline_id,
            "name": s.name,
            "order": s.order,
            "probability": s.probability,
            "config": s.config,
            "status": s.status,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
        for s in stages
    ]


async def create_deal_stage(db: AsyncSession, data: DealStageCreate, account_id: Optional[UUID] = None) -> Dict[str, Any]:
    """Create a new deal stage. F-4: pipeline ownership checked when ``account_id`` is given."""
    if account_id is not None:
        p_result = await db.execute(
            select(DealPipeline).where(
                DealPipeline.id == data.pipeline_id, DealPipeline.is_deleted == False
            )
        )
        _enforce_ownership(p_result.scalar_one_or_none(), "deal_pipeline", account_id)

    stage = DealStage(
        pipeline_id=data.pipeline_id,
        name=data.name,
        order=data.order,
        probability=data.probability,
        config=data.config or {},
    )
    db.add(stage)
    await db.commit()
    await db.refresh(stage)
    
    return {
        "id": stage.id,
        "pipeline_id": stage.pipeline_id,
        "name": stage.name,
        "order": stage.order,
        "probability": stage.probability,
        "config": stage.config,
        "status": stage.status,
        "created_at": stage.created_at,
        "updated_at": stage.updated_at,
    }


async def update_deal_stage(db: AsyncSession, stage_id: UUID, data: DealStageUpdate, account_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
    """Update a deal stage. F-4: pipeline ownership checked when ``account_id`` is given."""
    result = await db.execute(
        select(DealStage).where(DealStage.id == stage_id, DealStage.is_deleted == False)
    )
    stage = result.scalar_one_or_none()
    
    if not stage:
        return None
    
    if account_id is not None:
        p_result = await db.execute(
            select(DealPipeline).where(
                DealPipeline.id == stage.pipeline_id, DealPipeline.is_deleted == False
            )
        )
        _enforce_ownership(p_result.scalar_one_or_none(), "deal_pipeline", account_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(stage, field, value)
    
    stage.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(stage)
    
    return {
        "id": stage.id,
        "pipeline_id": stage.pipeline_id,
        "name": stage.name,
        "order": stage.order,
        "probability": stage.probability,
        "config": stage.config,
        "status": stage.status,
        "created_at": stage.created_at,
        "updated_at": stage.updated_at,
    }


async def delete_deal_stage(db: AsyncSession, stage_id: UUID, account_id: Optional[UUID] = None) -> bool:
    """Soft delete a deal stage. F-4: pipeline ownership checked when ``account_id`` is given."""
    result = await db.execute(
        select(DealStage).where(DealStage.id == stage_id, DealStage.is_deleted == False)
    )
    stage = result.scalar_one_or_none()
    
    if not stage:
        return False
    
    if account_id is not None:
        p_result = await db.execute(
            select(DealPipeline).where(
                DealPipeline.id == stage.pipeline_id, DealPipeline.is_deleted == False
            )
        )
        _enforce_ownership(p_result.scalar_one_or_none(), "deal_pipeline", account_id)

    stage.is_deleted = True
    stage.updated_at = datetime.utcnow()
    await db.commit()
    return True


# ========== DealItem Service ==========

async def get_deal_items(
    db: AsyncSession,
    account_id: UUID,
    pipeline_id: Optional[UUID] = None,
    stage_id: Optional[UUID] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """Get paginated list of deal items"""
    query = select(DealItem).where(
        DealItem.account_id == account_id,
        DealItem.is_deleted == False
    )
    
    if pipeline_id:
        query = query.where(DealItem.pipeline_id == pipeline_id)
    if stage_id:
        query = query.where(DealItem.stage_id == stage_id)
    if status:
        query = query.where(DealItem.status == status)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate
    query = query.order_by(DealItem.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "items": [
            {
                "id": d.id,
                "pipeline_id": d.pipeline_id,
                "stage_id": d.stage_id,
                "account_id": d.account_id,
                "customer_id": d.customer_id,
                "lead_id": d.lead_id,
                "name": d.name,
                "description": d.description,
                "value": d.value,
                "currency": d.currency,
                "expected_close_date": d.expected_close_date,
                "status": d.status,
                "winner_reason": d.winner_reason,
                "loser_reason": d.loser_reason,
                "created_at": d.created_at,
                "updated_at": d.updated_at,
            }
            for d in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def create_deal_item(db: AsyncSession, data: DealItemCreate) -> Dict[str, Any]:
    """Create a new deal item"""
    item = DealItem(
        pipeline_id=data.pipeline_id,
        stage_id=data.stage_id,
        account_id=data.account_id,
        customer_id=data.customer_id,
        lead_id=data.lead_id,
        name=data.name,
        description=data.description,
        value=data.value,
        currency=data.currency,
        expected_close_date=data.expected_close_date,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    
    return {
        "id": item.id,
        "pipeline_id": item.pipeline_id,
        "stage_id": item.stage_id,
        "account_id": item.account_id,
        "customer_id": item.customer_id,
        "lead_id": item.lead_id,
        "name": item.name,
        "description": item.description,
        "value": item.value,
        "currency": item.currency,
        "expected_close_date": item.expected_close_date,
        "status": item.status,
        "winner_reason": item.winner_reason,
        "loser_reason": item.loser_reason,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def update_deal_item(db: AsyncSession, item_id: UUID, data: DealItemUpdate, account_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
    """Update a deal item. F-4: ownership-checked when ``account_id`` is given."""
    result = await db.execute(
        select(DealItem).where(DealItem.id == item_id, DealItem.is_deleted == False)
    )
    item = result.scalar_one_or_none()
    
    if not item:
        return None
    
    _enforce_ownership(item, "deal_item", account_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    
    item.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(item)
    
    return {
        "id": item.id,
        "pipeline_id": item.pipeline_id,
        "stage_id": item.stage_id,
        "account_id": item.account_id,
        "customer_id": item.customer_id,
        "lead_id": item.lead_id,
        "name": item.name,
        "description": item.description,
        "value": item.value,
        "currency": item.currency,
        "expected_close_date": item.expected_close_date,
        "status": item.status,
        "winner_reason": item.winner_reason,
        "loser_reason": item.loser_reason,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def delete_deal_item(db: AsyncSession, item_id: UUID, account_id: Optional[UUID] = None) -> bool:
    """Soft delete a deal item. F-4: ownership-checked when ``account_id`` is given."""
    result = await db.execute(
        select(DealItem).where(DealItem.id == item_id, DealItem.is_deleted == False)
    )
    item = result.scalar_one_or_none()

    if not item:
        return False

    _enforce_ownership(item, "deal_item", account_id)

    item.is_deleted = True
    item.updated_at = datetime.utcnow()
    await db.commit()
    return True


# ========== Deal Stage Transition ==========

async def transition_deal_item(
    db: AsyncSession,
    item_id: UUID,
    account_id: UUID,
    stage_id: UUID,
    status: Optional[str] = None,
    winner_reason: Optional[str] = None,
    loser_reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Move a deal item to a new stage"""
    result = await db.execute(
        select(DealItem).where(
            DealItem.id == item_id,
            DealItem.account_id == account_id,
            DealItem.is_deleted == False
        )
    )
    item = result.scalar_one_or_none()

    if not item:
        return None

    # Verify stage belongs to same pipeline
    stage_result = await db.execute(
        select(DealStage).where(DealStage.id == stage_id, DealStage.is_deleted == False)
    )
    stage = stage_result.scalar_one_or_none()
    if not stage:
        raise ValueError(f"Stage {stage_id} not found")

    if stage.pipeline_id != item.pipeline_id:
        raise ValueError("Stage does not belong to this pipeline")

    item.stage_id = stage_id
    if status:
        item.status = status
    if winner_reason:
        item.winner_reason = winner_reason
    if loser_reason:
        item.loser_reason = loser_reason

    item.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(item)

    return {
        "id": item.id,
        "pipeline_id": item.pipeline_id,
        "stage_id": item.stage_id,
        "account_id": item.account_id,
        "customer_id": item.customer_id,
        "lead_id": item.lead_id,
        "name": item.name,
        "description": item.description,
        "value": item.value,
        "currency": item.currency,
        "expected_close_date": item.expected_close_date,
        "status": item.status,
        "winner_reason": item.winner_reason,
        "loser_reason": item.loser_reason,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


# ========== Deal Pipeline Statistics ==========

async def get_deal_pipeline_stats(
    db: AsyncSession,
    pipeline_id: UUID,
    account_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Get funnel statistics for a deal pipeline.

    F-4: when ``account_id`` is given, the pipeline must belong to it.
    """
    if account_id is not None:
        p_result = await db.execute(
            select(DealPipeline).where(
                DealPipeline.id == pipeline_id, DealPipeline.is_deleted == False
            )
        )
        _enforce_ownership(p_result.scalar_one_or_none(), "deal_pipeline", account_id)

    # Get stages with order
    stages_result = await db.execute(
        select(DealStage).where(
            DealStage.pipeline_id == pipeline_id,
            DealStage.is_deleted == False
        ).order_by(DealStage.order.asc())
    )
    stages = stages_result.scalars().all()

    stage_stats = []
    total_value = 0
    won_value = 0
    open_count = 0

    for stage in stages:
        # Count deals in this stage
        count_result = await db.execute(
            select(func.count()).where(
                DealItem.pipeline_id == pipeline_id,
                DealItem.stage_id == stage.id,
                DealItem.is_deleted == False,
                DealItem.status == DealItemStatus.OPEN.value
            )
        )
        count = count_result.scalar() or 0
        open_count += count

        # Sum value
        value_result = await db.execute(
            select(func.coalesce(func.sum(DealItem.value), 0)).where(
                DealItem.pipeline_id == pipeline_id,
                DealItem.stage_id == stage.id,
                DealItem.is_deleted == False
            )
        )
        stage_value = value_result.scalar() or 0
        total_value += stage_value

        stage_stats.append({
            "stage_id": stage.id,
            "stage_name": stage.name,
            "stage_order": stage.order,
            "deal_count": count,
            "total_value": stage_value,
            "probability": stage.probability,
        })

    # Get won deals
    won_result = await db.execute(
        select(func.coalesce(func.sum(DealItem.value), 0)).where(
            DealItem.pipeline_id == pipeline_id,
            DealItem.is_deleted == False,
            DealItem.status == DealItemStatus.WON.value
        )
    )
    won_value = won_result.scalar() or 0

    # Get lost deals
    lost_result = await db.execute(
        select(func.count()).where(
            DealItem.pipeline_id == pipeline_id,
            DealItem.is_deleted == False,
            DealItem.status == DealItemStatus.LOST.value
        )
    )
    lost_count = lost_result.scalar() or 0

    # Calculate conversion rate (won / total deals)
    total_deals_result = await db.execute(
        select(func.count()).where(
            DealItem.pipeline_id == pipeline_id,
            DealItem.is_deleted == False
        )
    )
    total_deals = total_deals_result.scalar() or 0
    conversion_rate = (won_value / total_value * 100) if total_value > 0 else 0

    return {
        "pipeline_id": pipeline_id,
        "total_deals": total_deals,
        "open_deals": open_count,
        "won_deals": total_deals - open_count - lost_count,
        "lost_deals": lost_count,
        "total_value": total_value,
        "won_value": won_value,
        "open_value": total_value - won_value,
        "conversion_rate": round(conversion_rate, 2),
        "stages": stage_stats,
    }


async def get_deal_pipeline_stats_by_account(
    db: AsyncSession,
    account_id: UUID,
) -> List[Dict[str, Any]]:
    """Get statistics for all pipelines of an account"""
    result = await db.execute(
        select(DealPipeline).where(
            DealPipeline.account_id == account_id,
            DealPipeline.is_deleted == False
        )
    )
    pipelines = result.scalars().all()

    stats_list = []
    for pipeline in pipelines:
        pipeline_id = pipeline.id
        stats = await get_deal_pipeline_stats(db, pipeline_id)
        stats["pipeline_name"] = pipeline.name
        stats["pipeline_type"] = pipeline.pipeline_type
        stats_list.append(stats)

    return stats_list


# ========== PrivateChannel Connection Status Service ==========

async def update_channel_connection_status(
    db: AsyncSession,
    channel_id: UUID,
    account_id: UUID,
    connection_status: str,
    last_connection: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Update channel connection status (online/offline/error)"""
    result = await db.execute(
        select(PrivateChannel).where(
            PrivateChannel.id == channel_id,
            PrivateChannel.account_id == account_id,
            PrivateChannel.is_deleted == False
        )
    )
    channel = result.scalar_one_or_none()

    if not channel:
        return None

    channel.connection_status = connection_status
    if last_connection:
        channel.last_connection = last_connection
    channel.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(channel)

    return {
        "id": channel.id,
        "account_id": channel.account_id,
        "name": channel.name,
        "status": channel.status,
        "connection_status": channel.connection_status,
        "last_connection": channel.last_connection,
        "updated_at": channel.updated_at,
    }


async def get_channel_stats(
    db: AsyncSession,
    channel_id: UUID,
    account_id: UUID,
) -> Optional[Dict[str, Any]]:
    """Get channel statistics (contact count, message count, etc.)"""
    result = await db.execute(
        select(PrivateChannel).where(
            PrivateChannel.id == channel_id,
            PrivateChannel.account_id == account_id,
            PrivateChannel.is_deleted == False
        )
    )
    channel = result.scalar_one_or_none()

    if not channel:
        return None

    # Get related data counts
    content_count_result = await db.execute(
        select(func.count()).where(
            ContentItem.account_id == account_id,
            ContentItem.channel_id == channel_id,
            ContentItem.is_deleted == False,
        )
    )
    content_count = content_count_result.scalar() or 0

    nurture_plan_count_result = await db.execute(
        select(func.count()).where(
            NurturePlan.account_id == account_id,
            NurturePlan.channel_id == channel_id,
            NurturePlan.is_deleted == False,
        )
    )
    nurture_plan_count = nurture_plan_count_result.scalar() or 0

    return {
        "channel_id": channel.id,
        "channel_name": channel.name,
        "channel_type": channel.channel_type,
        "status": channel.status,
        "connection_status": channel.connection_status,
        "last_connection": channel.last_connection,
        "contact_count": channel.contact_count,
        "message_count": channel.message_count,
        "content_count": content_count,
        "nurture_plan_count": nurture_plan_count,
        "created_at": channel.created_at,
        "updated_at": channel.updated_at,
    }


async def get_account_channel_stats(
    db: AsyncSession,
    account_id: UUID,
) -> Dict[str, Any]:
    """Get aggregated statistics for all channels of an account"""
    result = await db.execute(
        select(PrivateChannel).where(
            PrivateChannel.account_id == account_id,
            PrivateChannel.is_deleted == False
        )
    )
    channels = result.scalars().all()

    total_contacts = sum(ch.contact_count for ch in channels)
    total_messages = sum(ch.message_count for ch in channels)

    online_channels = sum(
        1 for ch in channels
        if ch.connection_status in ("online", "active")
    )
    offline_channels = sum(
        1 for ch in channels
        if ch.connection_status in ("offline", None)
    )
    error_channels = sum(
        1 for ch in channels
        if ch.connection_status == "error"
    )

    by_type: Dict[str, int] = {}
    for ch in channels:
        by_type[ch.channel_type] = by_type.get(ch.channel_type, 0) + 1

    return {
        "account_id": account_id,
        "total_channels": len(channels),
        "online_channels": online_channels,
        "offline_channels": offline_channels,
        "error_channels": error_channels,
        "total_contacts": total_contacts,
        "total_messages": total_messages,
        "by_channel_type": by_type,
        "channels": [
            {
                "id": ch.id,
                "name": ch.name,
                "channel_type": ch.channel_type,
                "status": ch.status,
                "connection_status": ch.connection_status,
                "last_connection": ch.last_connection,
                "contact_count": ch.contact_count,
                "message_count": ch.message_count,
            }
            for ch in channels
        ],
    }
