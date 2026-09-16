"""
Customer Segment Rule Engine
Supports: tag matching, lifecycle stage matching, behavior conditions
"""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from app.db.models.private_domain import CustomerSegment, SegmentMember
from app.db.models.customer import Customer
from app.db.models.tag import Tag, tag_customer
from app.db.models.lifecycle import LifecycleStage
from app.db.models.lead import Lead
from app.db.models.private_domain import DealItem, DealItemStatus


class SegmentRuleEngine:
    """Rule engine for evaluating customer segment membership"""
    
    @staticmethod
    async def evaluate_segment(
        db: AsyncSession,
        segment: CustomerSegment,
        customer_id: UUID,
    ) -> bool:
        """Evaluate if a customer matches segment rules"""
        filter_config = segment.filter_config or {}
        
        # Manual segments don't need evaluation
        if segment.segment_type == "manual":
            return True
        
        # Check tag matching
        if "tags" in filter_config:
            if not await SegmentRuleEngine._check_tags(db, customer_id, filter_config["tags"]):
                return False
        
        # Check lifecycle stage matching
        if "lifecycle_stages" in filter_config:
            if not await SegmentRuleEngine._check_lifecycle_stages(
                db, customer_id, filter_config["lifecycle_stages"]
            ):
                return False
        
        # Check behavior conditions
        if "behaviors" in filter_config:
            if not await SegmentRuleEngine._check_behaviors(
                db, customer_id, filter_config["behaviors"]
            ):
                return False
        
        # Check custom conditions
        if "conditions" in filter_config:
            if not await SegmentRuleEngine._check_conditions(
                db, customer_id, filter_config["conditions"]
            ):
                return False
        
        return True
    
    @staticmethod
    async def _check_tags(
        db: AsyncSession,
        customer_id: UUID,
        tag_config: Dict[str, Any],
    ) -> bool:
        """Check if customer has required tags"""
        # Get customer tags
        result = await db.execute(
            select(Tag.id).join(tag_customer).where(
                tag_customer.c.customer_id == customer_id
            )
        )
        customer_tags = {row.id for row in result.scalars().all()}
        
        # Check required tags (AND logic)
        required_tags = tag_config.get("required", [])
        if required_tags:
            if not all(tag_id in customer_tags for tag_id in required_tags):
                return False
        
        # Check excluded tags (OR logic - exclude if any match)
        excluded_tags = tag_config.get("excluded", [])
        if excluded_tags:
            if any(tag_id in customer_tags for tag_id in excluded_tags):
                return False
        
        return True
    
    @staticmethod
    async def _check_lifecycle_stages(
        db: AsyncSession,
        customer_id: UUID,
        stage_config: Dict[str, Any],
    ) -> bool:
        """Check if customer's lifecycle stage matches"""
        # Get customer's current lifecycle stage
        # Note: This is a simplified implementation
        # In real system, this would query customer_stage or similar
        
        # For now, check if we're filtering by specific stages
        target_stages = stage_config.get("stages", [])
        if not target_stages:
            return True
        
        # Simplified: assume we have a customer_lifecycle table
        # In practice, you'd need to implement this based on your schema
        return True
    
    @staticmethod
    async def _check_behaviors(
        db: AsyncSession,
        customer_id: UUID,
        behavior_config: Dict[str, Any],
    ) -> bool:
        """Check customer behavior conditions"""
        conditions = behavior_config.get("conditions", [])
        
        for condition in conditions:
            field = condition.get("field")
            operator = condition.get("operator", "eq")
            value = condition.get("value")
            
            if not await SegmentRuleEngine._evaluate_condition(
                db, customer_id, field, operator, value
            ):
                return False
        
        return True
    
    @staticmethod
    async def _evaluate_condition(
        db: AsyncSession,
        customer_id: UUID,
        field: str,
        operator: str,
        value: Any,
    ) -> bool:
        """Evaluate a single condition against customer data"""
        # Handle different field types
        
        if field == "total_spent":
            # Sum of won deal values
            result = await db.execute(
                select(func.coalesce(func.sum(DealItem.value), 0)).where(
                    DealItem.customer_id == customer_id,
                    DealItem.status == DealItemStatus.WON.value,
                    DealItem.is_deleted == False,
                )
            )
            total = result.scalar() or 0
            return SegmentRuleEngine._compare(total, operator, value)
        
        elif field == "deal_count":
            # Count of deals
            result = await db.execute(
                select(func.count()).where(
                    DealItem.customer_id == customer_id,
                    DealItem.is_deleted == False,
                )
            )
            count = result.scalar() or 0
            return SegmentRuleEngine._compare(count, operator, value)
        
        elif field == "last_purchase_date":
            # Last purchase date
            result = await db.execute(
                select(func.max(DealItem.created_at)).where(
                    DealItem.customer_id == customer_id,
                    DealItem.status == DealItemStatus.WON.value,
                    DealItem.is_deleted == False,
                )
            )
            last_date = result.scalar()
            if last_date is None:
                return False
            return SegmentRuleEngine._compare_date(last_date, operator, value)
        
        elif field == "registration_date":
            # Customer registration date
            result = await db.execute(
                select(Customer.created_at).where(Customer.id == customer_id)
            )
            reg_date = result.scalar_one_or_none()
            if reg_date is None:
                return False
            return SegmentRuleEngine._compare_date(reg_date, operator, value)
        
        elif field == "email_opened":
            # Check if customer has opened emails (simplified)
            # This would need actual email tracking integration
            return True
        
        elif field == "wechat_active":
            # Check WeChat activity (simplified)
            # This would need WeChat interaction tracking
            return True
        
        # Default: treat as string comparison on customer fields
        result = await db.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        customer = result.scalar_one_or_none()
        if not customer:
            return False
        
        customer_value = getattr(customer, field, None)
        if customer_value is None:
            return False
        
        return SegmentRuleEngine._compare(customer_value, operator, value)
    
    @staticmethod
    def _compare(actual: Any, operator: str, expected: Any) -> bool:
        """Compare two values with operator"""
        try:
            if operator == "eq":
                return actual == expected
            elif operator == "neq":
                return actual != expected
            elif operator == "gt":
                return actual > expected
            elif operator == "gte":
                return actual >= expected
            elif operator == "lt":
                return actual < expected
            elif operator == "lte":
                return actual <= expected
            elif operator == "in":
                return actual in expected
            elif operator == "not_in":
                return actual not in expected
            else:
                return False
        except (TypeError, ValueError):
            return False
    
    @staticmethod
    def _compare_date(date_val: datetime, operator: str, expected: Any) -> bool:
        """Compare dates"""
        try:
            if isinstance(expected, str):
                expected = datetime.fromisoformat(expected.replace("Z", "+00:00"))
            
            if operator == "eq":
                return date_val.date() == expected.date()
            elif operator == "gt":
                return date_val > expected
            elif operator == "gte":
                return date_val >= expected
            elif operator == "lt":
                return date_val < expected
            elif operator == "lte":
                return date_val <= expected
            else:
                return False
        except (ValueError, TypeError):
            return False


async def sync_segment_members(
    db: AsyncSession,
    segment_id: UUID,
) -> Dict[str, Any]:
    """Recalculate and sync segment members based on rules"""
    # Get segment
    result = await db.execute(
        select(CustomerSegment).where(
            CustomerSegment.id == segment_id,
            CustomerSegment.is_deleted == False,
        )
    )
    segment = result.scalar_one_or_none()
    
    if not segment:
        raise ValueError(f"Segment {segment_id} not found")
    
    if segment.segment_type == "manual":
        return {
            "segment_id": segment_id,
            "members_added": 0,
            "members_removed": 0,
            "total_members": segment.member_count,
            "synced_at": segment.last_synced_at,
        }
    
    # Get all customers (Customer model doesn't have account_id)
    customers_result = await db.execute(
        select(Customer.id).where(
            Customer.is_deleted == False,
        )
    )
    customer_ids = set(customers_result.scalars().all())
    
    # Get current members
    members_result = await db.execute(
        select(SegmentMember.customer_id).where(
            SegmentMember.segment_id == segment_id
        )
    )
    current_member_ids = set(members_result.scalars().all())
    
    # Evaluate each customer
    new_member_ids = set()
    for customer_id in customer_ids:
        if await SegmentRuleEngine.evaluate_segment(db, segment, customer_id):
            new_member_ids.add(customer_id)
    
    # Calculate changes
    added = new_member_ids - current_member_ids
    removed = current_member_ids - new_member_ids
    
    # Add new members
    for customer_id in added:
        member = SegmentMember(
            segment_id=segment_id,
            customer_id=customer_id,
            added_by="system",
        )
        db.add(member)
    
    # Remove members no longer qualifying
    if removed:
        await db.execute(
            SegmentMember.__table__.delete().where(
                SegmentMember.segment_id == segment_id,
                SegmentMember.customer_id.in_(removed),
            )
        )
    
    # Update segment
    segment.member_count = len(new_member_ids)
    segment.last_synced_at = datetime.now(timezone.utc)
    
    await db.commit()
    
    return {
        "segment_id": segment_id,
        "members_added": len(added),
        "members_removed": len(removed),
        "total_members": segment.member_count,
        "synced_at": segment.last_synced_at,
    }


async def get_segment_stats(
    db: AsyncSession,
    segment_id: UUID,
) -> Dict[str, Any]:
    """Get statistics for a customer segment"""
    # Get segment
    result = await db.execute(
        select(CustomerSegment).where(
            CustomerSegment.id == segment_id,
            CustomerSegment.is_deleted == False,
        )
    )
    segment = result.scalar_one_or_none()
    
    if not segment:
        raise ValueError(f"Segment {segment_id} not found")
    
    # Get members
    members_result = await db.execute(
        select(SegmentMember).where(
            SegmentMember.segment_id == segment_id
        )
    )
    members = members_result.scalars().all()
    member_ids = [m.customer_id for m in members]
    
    if not member_ids:
        return {
            "segment_id": segment_id,
            "segment_name": segment.name,
            "segment_type": segment.segment_type,
            "member_count": 0,
            "total_value": 0,
            "avg_value": 0,
            "conversion_rate": 0,
            "top_tags": [],
        }
    
    # Calculate total value from won deals
    value_result = await db.execute(
        select(func.coalesce(func.sum(DealItem.value), 0)).where(
            DealItem.customer_id.in_(member_ids),
            DealItem.status == DealItemStatus.WON.value,
            DealItem.is_deleted == False,
        )
    )
    total_value = value_result.scalar() or 0
    
    # Calculate average value
    avg_value = total_value / len(member_ids) if member_ids else 0
    
    # Get top tags for members
    tags_result = await db.execute(
        select(
            Tag.id,
            Tag.name,
            func.count(tag_customer.c.customer_id).label("usage_count")
        )
        .join(tag_customer, Tag.id == tag_customer.c.tag_id)
        .where(tag_customer.c.customer_id.in_(member_ids))
        .group_by(Tag.id, Tag.name)
        .order_by(func.count(tag_customer.c.customer_id).desc())
        .limit(5)
    )
    top_tags = [
        {"id": row.id, "name": row.name, "count": row.usage_count}
        for row in tags_result.all()
    ]
    
    # Calculate conversion rate (simplified: ratio of members with deals)
    deals_result = await db.execute(
        select(func.count()).where(
            DealItem.customer_id.in_(member_ids),
            DealItem.is_deleted == False,
        )
    )
    members_with_deals = deals_result.scalar() or 0
    conversion_rate = (members_with_deals / len(member_ids) * 100) if member_ids else 0
    
    return {
        "segment_id": segment_id,
        "segment_name": segment.name,
        "segment_type": segment.segment_type,
        "member_count": len(member_ids),
        "total_value": total_value,
        "avg_value": round(avg_value, 2),
        "conversion_rate": round(conversion_rate, 2),
        "top_tags": top_tags,
        "last_synced_at": segment.last_synced_at,
    }


async def get_account_segment_stats(
    db: AsyncSession,
    account_id: UUID,
) -> List[Dict[str, Any]]:
    """Get statistics for all segments of an account"""
    result = await db.execute(
        select(CustomerSegment).where(
            CustomerSegment.account_id == account_id,
            CustomerSegment.is_deleted == False,
        )
    )
    segments = result.scalars().all()
    
    stats_list = []
    for segment in segments:
        stats = await get_segment_stats(db, segment.id)
        stats_list.append(stats)
    
    return stats_list
