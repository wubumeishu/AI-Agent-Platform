"""
Content Library Service: Search, Usage Statistics, Category Management
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import joinedload

from app.db.models.private_domain import (
    ContentItem,
    NurturePlanItem,
    ContentStatus,
)


async def search_content_items(
    db: AsyncSession,
    account_id: UUID,
    keyword: Optional[str] = None,
    content_type: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    tag: Optional[str] = None,
    min_usage_count: Optional[int] = None,
    max_usage_count: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """Search and filter content items"""
    
    # Base query
    query = select(ContentItem).where(
        ContentItem.account_id == account_id,
        ContentItem.is_deleted == False
    )
    
    # Apply filters
    if keyword:
        keyword_pattern = f"%{keyword}%"
        query = query.where(
            or_(
                ContentItem.title.ilike(keyword_pattern),
                ContentItem.summary.ilike(keyword_pattern),
                ContentItem.body.ilike(keyword_pattern)
            )
        )
    
    if content_type:
        query = query.where(ContentItem.content_type == content_type)
    
    if category:
        query = query.where(ContentItem.category == category)
    
    if status:
        query = query.where(ContentItem.status == status)
    
    if tag:
        # JSON contains filter for tag
        query = query.where(ContentItem.tags.contains([tag]))
    
    if min_usage_count is not None:
        query = query.where(ContentItem.usage_count >= min_usage_count)
    
    if max_usage_count is not None:
        query = query.where(ContentItem.usage_count <= max_usage_count)
    
    if date_from:
        query = query.where(ContentItem.created_at >= date_from)
    
    if date_to:
        query = query.where(ContentItem.created_at <= date_to)
    
    # Apply sorting
    sort_column = getattr(ContentItem, sort_by, ContentItem.created_at)
    if sort_order == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate
    query = query.offset((page - 1) * page_size).limit(page_size)
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
        "keywords": keyword,
    }


async def track_content_usage(db: AsyncSession, content_id: UUID, account_id: UUID) -> Dict[str, Any]:
    """Track content usage by incrementing usage count and updating last used time"""
    
    result = await db.execute(
        select(ContentItem).where(
            ContentItem.id == content_id,
            ContentItem.account_id == account_id,
            ContentItem.is_deleted == False
        )
    )
    item = result.scalar_one_or_none()
    
    if not item:
        return None
    
    item.usage_count += 1
    item.last_used_at = datetime.utcnow()
    item.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(item)
    
    return {
        "id": item.id,
        "usage_count": item.usage_count,
        "last_used_at": item.last_used_at,
    }


async def get_content_usage_stats(
    db: AsyncSession,
    account_id: UUID,
    content_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Get usage statistics for content items"""
    
    query = select(ContentItem).where(
        ContentItem.account_id == account_id,
        ContentItem.is_deleted == False
    )
    
    if content_id:
        query = query.where(ContentItem.id == content_id)
    
    result = await db.execute(query)
    items = result.scalars().all()
    
    stats = []
    for item in items:
        # Count nurture plans using this content
        plan_count_result = await db.execute(
            select(func.count()).where(
                NurturePlanItem.content_id == item.id
            )
        )
        plan_count = plan_count_result.scalar() or 0
        
        stats.append({
            "content_id": item.id,
            "title": item.title,
            "content_type": item.content_type,
            "category": item.category,
            "usage_count": item.usage_count,
            "last_used_at": item.last_used_at,
            "used_in_plans": plan_count,
            "used_in_tasks": 0,  # Placeholder for future implementation
        })
    
    return {"stats": stats}


async def get_content_type_stats(db: AsyncSession, account_id: UUID) -> List[Dict[str, Any]]:
    """Get statistics grouped by content type"""
    
    result = await db.execute(
        select(
            ContentItem.content_type,
            func.count(ContentItem.id).label("count"),
            func.sum(ContentItem.usage_count).label("total_usage")
        ).where(
            ContentItem.account_id == account_id,
            ContentItem.is_deleted == False
        ).group_by(ContentItem.content_type)
    )
    
    rows = result.fetchall()

    return [
        {
            "content_type": row[0],
            "count": row[1] or 0,
            "total_usage": row[2] or 0,
        }
        for row in rows
    ]


async def get_content_category_stats(db: AsyncSession, account_id: UUID) -> List[Dict[str, Any]]:
    """Get statistics grouped by category"""
    
    result = await db.execute(
        select(
            ContentItem.category,
            func.count(ContentItem.id).label("count"),
            func.sum(ContentItem.usage_count).label("total_usage")
        ).where(
            ContentItem.account_id == account_id,
            ContentItem.is_deleted == False
        ).group_by(ContentItem.category)
    )
    
    rows = result.fetchall()
    
    return [
        {
            "category": row[0],
            "count": row[1] or 0,
            "total_usage": row[2] or 0,
        }
        for row in rows
    ]


async def get_content_categories(db: AsyncSession, account_id: UUID) -> List[str]:
    """Get unique categories for an account"""
    
    result = await db.execute(
        select(ContentItem.category)
        .where(
            ContentItem.account_id == account_id,
            ContentItem.is_deleted == False,
            ContentItem.category.isnot(None)
        )
        .distinct()
    )
    
    return [row[0] for row in result.fetchall()]


async def get_content_tags(db: AsyncSession, account_id: UUID) -> List[str]:
    """Get unique tags across all content items"""
    
    result = await db.execute(
        select(ContentItem.tags)
        .where(
            ContentItem.account_id == account_id,
            ContentItem.is_deleted == False,
            ContentItem.tags != []
        )
    )
    
    all_tags = set()
    for row in result.scalars().all():
        if row:
            all_tags.update(row)
    
    return sorted(list(all_tags))


async def get_top_used_content(
    db: AsyncSession,
    account_id: UUID,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Get top N most used content items"""
    
    result = await db.execute(
        select(ContentItem)
        .where(
            ContentItem.account_id == account_id,
            ContentItem.is_deleted == False
        )
        .order_by(ContentItem.usage_count.desc())
        .limit(limit)
    )
    
    items = result.scalars().all()
    
    return [
        {
            "id": item.id,
            "title": item.title,
            "content_type": item.content_type,
            "category": item.category,
            "usage_count": item.usage_count,
            "last_used_at": item.last_used_at,
        }
        for item in items
    ]


async def get_content_by_category(
    db: AsyncSession,
    account_id: UUID,
    category: str,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """Get content items filtered by category"""
    
    query = select(ContentItem).where(
        ContentItem.account_id == account_id,
        ContentItem.is_deleted == False,
        ContentItem.category == category
    )
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate
    query = query.order_by(ContentItem.usage_count.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "category": category,
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "content_type": item.content_type,
                "category": item.category,
                "usage_count": item.usage_count,
                "last_used_at": item.last_used_at,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
