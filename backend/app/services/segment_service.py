"""
Enhanced Customer Segment Service with rule engine integration
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete
from sqlalchemy.exc import IntegrityError

from app.db.models.private_domain import (
    CustomerSegment,
    SegmentMember,
)
from app.db.models.customer import Customer
from app.schemas.private_domain import (
    CustomerSegmentCreate,
    CustomerSegmentUpdate,
)
from app.security.jwt_auth import AccountOwnershipError
from app.services.segment_rule_engine import (
    sync_segment_members,
    get_segment_stats,
    get_account_segment_stats,
)


def _enforce_segment_ownership(segment: Optional[Any], resource_type: str, account_id: Optional[UUID]) -> None:
    """F-4: a segment-scoped operation must target a segment owned by the
    caller's account (no-op when ``account_id`` is ``None``)."""
    if account_id is None or segment is None:
        return
    owner = getattr(segment, "account_id", None)
    if owner is not None and UUID(str(owner)) != UUID(str(account_id)):
        raise AccountOwnershipError(resource_type, account_id)


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
        CustomerSegment.is_deleted == False,
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


async def get_customer_segment(
    db: AsyncSession,
    segment_id: UUID,
    account_id: UUID,
) -> Optional[Dict[str, Any]]:
    """Get a single customer segment by ID"""
    result = await db.execute(
        select(CustomerSegment).where(
            CustomerSegment.id == segment_id,
            CustomerSegment.account_id == account_id,
            CustomerSegment.is_deleted == False,
        )
    )
    segment = result.scalar_one_or_none()
    
    if not segment:
        return None
    
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


async def create_customer_segment(
    db: AsyncSession,
    data: CustomerSegmentCreate,
) -> Dict[str, Any]:
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
    
    # If automatic segment, sync members
    if segment.segment_type in ("automatic", "dynamic"):
        await sync_segment_members(db, segment.id)
    
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


async def update_customer_segment(
    db: AsyncSession,
    segment_id: UUID,
    account_id: UUID,
    data: CustomerSegmentUpdate,
) -> Optional[Dict[str, Any]]:
    """Update a customer segment"""
    result = await db.execute(
        select(CustomerSegment).where(
            CustomerSegment.id == segment_id,
            CustomerSegment.account_id == account_id,
            CustomerSegment.is_deleted == False,
        )
    )
    segment = result.scalar_one_or_none()
    
    if not segment:
        return None
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(segment, field, value)
    
    segment.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(segment)
    
    # If automatic segment with changed filter config, resync members
    if segment.segment_type in ("automatic", "dynamic") and "filter_config" in update_data:
        await sync_segment_members(db, segment.id)
    
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


async def delete_customer_segment(
    db: AsyncSession,
    segment_id: UUID,
) -> bool:
    """Soft delete a customer segment"""
    result = await db.execute(
        select(CustomerSegment).where(
            CustomerSegment.id == segment_id,
            CustomerSegment.is_deleted == False,
        )
    )
    segment = result.scalar_one_or_none()
    
    if not segment:
        return False
    
    segment.is_deleted = True
    segment.updated_at = datetime.utcnow()
    await db.commit()
    return True


async def add_segment_member(
    db: AsyncSession,
    segment_id: UUID,
    customer_id: UUID,
    added_by: Optional[str] = None,
    account_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Manually add a customer to a segment.

    F-4: ``account_id`` (the caller's bound account) enforces that the target
    segment belongs to the caller. F-5: when the caller is authenticated
    (``account_id`` supplied) the audit ``added_by`` is bound to the
    authenticated identity unless one was explicitly provided, so audit
    attribution cannot be forged.
    """
    # Check segment exists
    segment_result = await db.execute(
        select(CustomerSegment).where(
            CustomerSegment.id == segment_id,
            CustomerSegment.is_deleted == False,
        )
    )
    segment = segment_result.scalar_one_or_none()
    
    if not segment:
        raise ValueError(f"Segment {segment_id} not found")

    _enforce_segment_ownership(segment, "customer_segment", account_id)
    
    # Check customer exists
    customer_result = await db.execute(
        select(Customer).where(Customer.id == customer_id)
    )
    customer = customer_result.scalar_one_or_none()
    
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")
    
    # Check if already a member
    existing = await db.execute(
        select(SegmentMember).where(
            SegmentMember.segment_id == segment_id,
            SegmentMember.customer_id == customer_id,
        )
    )
    if existing.scalar_one_or_none():
        return {
            "segment_id": segment_id,
            "customer_id": customer_id,
            "action": "already_member",
            "message": "Customer is already a member of this segment",
        }
    
    # F-5: an authenticated caller's identity is the audit default.
    effective_added_by = added_by if added_by else ("authenticated" if account_id else "manual")

    # Add member
    member = SegmentMember(
        segment_id=segment_id,
        customer_id=customer_id,
        added_by=effective_added_by,
    )
    db.add(member)
    
    # Update count
    segment.member_count += 1
    segment.last_synced_at = datetime.utcnow()
    
    await db.commit()
    
    return {
        "segment_id": segment_id,
        "customer_id": customer_id,
        "action": "added",
        "added_at": member.added_at,
        "total_members": segment.member_count,
    }


async def remove_segment_member(
    db: AsyncSession,
    segment_id: UUID,
    customer_id: UUID,
    account_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Remove a customer from a segment. F-4: ownership-checked when ``account_id`` is given."""
    # F-4: verify the segment belongs to the caller before touching membership.
    if account_id is not None:
        seg_result = await db.execute(
            select(CustomerSegment).where(CustomerSegment.id == segment_id, CustomerSegment.is_deleted == False)
        )
        _enforce_segment_ownership(seg_result.scalar_one_or_none(), "customer_segment", account_id)

    # Find the member
    result = await db.execute(
        select(SegmentMember).where(
            SegmentMember.segment_id == segment_id,
            SegmentMember.customer_id == customer_id,
        )
    )
    member = result.scalar_one_or_none()
    
    if not member:
        raise ValueError(f"Customer {customer_id} is not a member of segment {segment_id}")
    
    # Remove member
    await db.delete(member)
    
    # Update segment count
    segment_result = await db.execute(
        select(CustomerSegment).where(CustomerSegment.id == segment_id)
    )
    segment = segment_result.scalar_one_or_none()
    if segment:
        segment.member_count = max(0, segment.member_count - 1)
        segment.last_synced_at = datetime.utcnow()
    
    await db.commit()
    
    return {
        "segment_id": segment_id,
        "customer_id": customer_id,
        "action": "removed",
        "total_members": segment.member_count if segment else 0,
    }


async def sync_segment(
    db: AsyncSession,
    segment_id: UUID,
    account_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Manually trigger segment member sync. F-4: ownership-checked when ``account_id`` is given."""
    if account_id is not None:
        seg_result = await db.execute(
            select(CustomerSegment).where(CustomerSegment.id == segment_id, CustomerSegment.is_deleted == False)
        )
        _enforce_segment_ownership(seg_result.scalar_one_or_none(), "customer_segment", account_id)
    return await sync_segment_members(db, segment_id)


async def get_segment_with_stats(
    db: AsyncSession,
    segment_id: UUID,
    account_id: UUID,
) -> Optional[Dict[str, Any]]:
    """Get segment with detailed statistics"""
    # Get segment
    result = await db.execute(
        select(CustomerSegment).where(
            CustomerSegment.id == segment_id,
            CustomerSegment.account_id == account_id,
            CustomerSegment.is_deleted == False,
        )
    )
    segment = result.scalar_one_or_none()
    
    if not segment:
        return None
    
    # Get stats
    stats = await get_segment_stats(db, segment_id)
    
    return {
        **segment.__dict__,
        "stats": stats,
    }


async def bulk_add_members(
    db: AsyncSession,
    segment_id: UUID,
    customer_ids: List[UUID],
    added_by: Optional[str] = None,
    account_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Bulk add customers to a segment.

    F-4: ownership-checked when ``account_id`` is given; F-5: audit ``added_by``
    is bound to the authenticated identity by default.
    """
    # Check segment exists
    segment_result = await db.execute(
        select(CustomerSegment).where(
            CustomerSegment.id == segment_id,
            CustomerSegment.is_deleted == False,
        )
    )
    segment = segment_result.scalar_one_or_none()
    
    if not segment:
        raise ValueError(f"Segment {segment_id} not found")

    _enforce_segment_ownership(segment, "customer_segment", account_id)

    # F-5: an authenticated caller's identity is the audit default.
    effective_added_by = added_by if added_by else ("authenticated" if account_id else "bulk")

    added = []
    already_members = []
    
    for customer_id in customer_ids:
        # Check if already a member
        existing = await db.execute(
            select(SegmentMember).where(
                SegmentMember.segment_id == segment_id,
                SegmentMember.customer_id == customer_id,
            )
        )
        if existing.scalar_one_or_none():
            already_members.append(customer_id)
            continue
        
        # Add member
        member = SegmentMember(
            segment_id=segment_id,
            customer_id=customer_id,
            added_by=effective_added_by,
        )
        db.add(member)
        added.append(customer_id)
    
    if added:
        segment.member_count += len(added)
        segment.last_synced_at = datetime.utcnow()
        await db.commit()
    
    return {
        "segment_id": segment_id,
        "total_requested": len(customer_ids),
        "added": len(added),
        "already_members": len(already_members),
        "total_members": segment.member_count,
    }


async def get_segment_members(
    db: AsyncSession,
    segment_id: UUID,
    page: int = 1,
    page_size: int = 20,
    account_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Get members of a segment with pagination. F-4: ownership-checked when ``account_id`` is given."""
    if account_id is not None:
        seg_result = await db.execute(
            select(CustomerSegment).where(CustomerSegment.id == segment_id, CustomerSegment.is_deleted == False)
        )
        _enforce_segment_ownership(seg_result.scalar_one_or_none(), "customer_segment", account_id)

    # Get members
    query = select(SegmentMember).where(
        SegmentMember.segment_id == segment_id
    ).order_by(SegmentMember.added_at.desc())
    
    # Get total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    members = result.scalars().all()
    
    return {
        "items": [
            {
                "id": m.id,
                "segment_id": m.segment_id,
                "customer_id": m.customer_id,
                "added_by": m.added_by,
                "added_at": m.added_at,
            }
            for m in members
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
