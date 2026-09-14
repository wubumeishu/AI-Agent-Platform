"""
Phase 5 Integration Service: Cross-module data consistency
Implements Lead -> Customer conversion, Customer-PrivateChannel association,
NurturePlan application, and DealItem-Customer linkage
"""
import logging
from datetime import datetime
from typing import Any, Optional, Dict, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from app.db.models.customer import Customer
from app.db.models.customer_identity import CustomerIdentity
from app.db.models.lead import Lead
from app.db.models.private_domain import (
    PrivateChannel,
    NurturePlan,
    SegmentMember,
    CustomerSegment,
    DealItem,
    DealItemStatus,
)
from app.db.models.tag import Tag, tag_customer
from app.security.jwt_auth import AccountOwnershipError
from app.security.masking import mask_email, mask_phone

logger = logging.getLogger(__name__)


def _require_channel_ownership(channel: Any, account_id: Optional[UUID]) -> None:
    """F-4: a channel-scoped write must target a channel owned by the caller's
    account (no-op when ``account_id`` is ``None``)."""
    if account_id is None or channel is None:
        return
    owner = getattr(channel, "account_id", None)
    if owner is not None and UUID(str(owner)) != UUID(str(account_id)):
        raise AccountOwnershipError("private_channel", account_id)


def _require_plan_ownership(plan: Any, account_id: Optional[UUID]) -> None:
    """F-4: a nurture-plan-scoped write must target a plan owned by the
    caller's account (no-op when ``account_id`` is ``None``)."""
    if account_id is None or plan is None:
        return
    owner = getattr(plan, "account_id", None)
    if owner is not None and UUID(str(owner)) != UUID(str(account_id)):
        raise AccountOwnershipError("nurture_plan", account_id)


# ==================== Lead -> Customer Conversion ====================

async def convert_lead_to_customer(
    db: AsyncSession,
    lead_id: UUID,
    account_id: Optional[UUID] = None,
    channel_id: Optional[UUID] = None,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    company: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convert a Lead to a Customer and link to private domain channel.
    
    This is the core integration: when a lead reaches 'converted' status,
    it creates a Customer record and associates it with the private channel.
    """
    # 1. Get the lead
    lead_result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.is_deleted == False)
    )
    lead = lead_result.scalar_one_or_none()
    
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")
    
    # 2. Check if already converted
    if lead.status == "converted" and lead.customer_id:
        return await _get_conversion_result(db, lead.customer_id, lead_id)
    
    # 3. Determine customer name (use lead info or provided)
    customer_name = name or lead.source_id or "Unknown"
    
    # 4. Find or create customer by email/phone
    existing_customer = None
    if email:
        existing_customer = await _find_customer_by_email(db, email)
    elif phone:
        existing_customer = await _find_customer_by_phone(db, phone)
    
    if existing_customer:
        customer = existing_customer
    else:
        # Create new customer
        customer_data = {
            "name": customer_name,
            "email": email,
            "phone": phone,
            "company": company,
            "extra_info": {
                "source_lead_id": str(lead_id),
                "source_type": lead.source_type,
                "converted_at": datetime.utcnow().isoformat(),
            }
        }
        customer = Customer(**customer_data)
        db.add(customer)
        await db.commit()
        await db.refresh(customer)
        logger.info(f"Created customer {customer.id} from lead {lead_id}")
    
    # 5. Link lead to customer
    lead.customer_id = customer.id
    lead.status = "converted"
    lead.updated_at = datetime.utcnow()
    
    # 6. Associate with private channel if provided
    if channel_id:
        # Verify channel exists and belongs to account
        channel_result = await db.execute(
            select(PrivateChannel).where(
                PrivateChannel.id == channel_id,
                PrivateChannel.account_id == account_id if account_id else True,
                PrivateChannel.is_deleted == False
            )
        )
        channel = channel_result.scalar_one_or_none()
        if not channel:
            raise ValueError(f"Private channel {channel_id} not found")
        
        # Add channel_id to customer extra_info
        if not customer.extra_info:
            customer.extra_info = {}
        customer.extra_info["private_channel_id"] = str(channel_id)
        customer.extra_info["channel_type"] = channel.channel_type
    
    await db.commit()
    await db.refresh(customer)
    await db.refresh(lead)
    
    return await _get_conversion_result(db, customer.id, lead.id)


async def _find_customer_by_email(db: AsyncSession, email: str) -> Optional[Customer]:
    """Find customer by email through identities or direct field"""
    result = await db.execute(
        select(Customer).join(CustomerIdentity, CustomerIdentity.customer_id == Customer.id)
        .where(
            CustomerIdentity.email == email,
            Customer.is_deleted == False,
            CustomerIdentity.is_deleted == False
        )
    )
    return result.scalar_one_or_none()


async def _find_customer_by_phone(db: AsyncSession, phone: str) -> Optional[Customer]:
    """Find customer by phone through identities or direct field"""
    result = await db.execute(
        select(Customer).join(CustomerIdentity, CustomerIdentity.customer_id == Customer.id)
        .where(
            CustomerIdentity.phone == phone,
            Customer.is_deleted == False,
            CustomerIdentity.is_deleted == False
        )
    )
    return result.scalar_one_or_none()


async def _get_conversion_result(db: AsyncSession, customer_id: UUID, lead_id: UUID) -> Dict[str, Any]:
    """Get the conversion result with all linked data"""
    # Get customer
    customer_result = await db.execute(
        select(Customer)
        .options(
            selectinload(Customer.identities),
            selectinload(Customer.tags)
        )
        .where(Customer.id == customer_id, Customer.is_deleted == False)
    )
    customer = customer_result.scalar_one_or_none()
    
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")
    
    # Get lead (use separate query to avoid confusion)
    lead_query = select(Lead).where(Lead.id == lead_id, Lead.is_deleted == False)
    lead_result = await db.execute(lead_query)
    lead = lead_result.scalar_one_or_none()

    # Extract channel info from extra_info
    channel_info = None
    if customer.extra_info and "private_channel_id" in customer.extra_info:
        channel_id = UUID(customer.extra_info["private_channel_id"])
        channel_result = await db.execute(
            select(PrivateChannel).where(
                PrivateChannel.id == channel_id,
                PrivateChannel.is_deleted == False
            )
        )
        channel = channel_result.scalar_one_or_none()
        if channel:
            channel_info = {
                "id": str(channel.id),
                "name": channel.name,
                "channel_type": channel.channel_type,
            }
    
    return {
        "customer": {
            "id": str(customer.id),
            "name": customer.name,
            # P0-2: PII is masked on the way out; the raw value stays at rest
            # (encrypted) and is only decrypted for server-side business use.
            "email": mask_email(customer.email),
            "phone": mask_phone(customer.phone),
            "company": customer.company,
            "identities": [
                {
                    "id": str(i.id),
                    "platform": i.platform,
                    "platform_account_id": i.platform_account_id,
                }
                for i in customer.identities
            ],
            "tags": [
                {"id": str(t.id), "name": t.name}
                for t in customer.tags
            ],
            "extra_info": customer.extra_info or {},
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
        },
        "lead": {
            "id": str(lead.id) if lead else None,
            "status": lead.status if lead else None,
            "customer_id": str(lead.customer_id) if lead and lead.customer_id else None,
        } if lead else None,
        "private_channel": channel_info,
        "converted_at": datetime.utcnow().isoformat(),
    }


# ==================== Customer-PrivateChannel Association ====================

async def associate_customer_with_channel(
    db: AsyncSession,
    customer_id: UUID,
    channel_id: UUID,
    account_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """
    Associate a customer with a private channel.
    Updates customer's extra_info with channel reference.

    F-4: when ``account_id`` is supplied the target channel must belong to it.
    """
    # Verify customer exists
    customer_result = await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False)
    )
    customer = customer_result.scalar_one_or_none()
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")
    
    # Verify channel exists
    channel_result = await db.execute(
        select(PrivateChannel).where(
            PrivateChannel.id == channel_id,
            PrivateChannel.is_deleted == False
        )
    )
    channel = channel_result.scalar_one_or_none()
    if not channel:
        raise ValueError(f"Private channel {channel_id} not found")

    _require_channel_ownership(channel, account_id)
    
    # Update customer extra_info
    if not customer.extra_info:
        customer.extra_info = {}
    
    customer.extra_info["private_channel_id"] = str(channel_id)
    customer.extra_info["channel_type"] = channel.channel_type
    customer.extra_info["channel_name"] = channel.name
    customer.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(customer)
    
    logger.info(f"Associated customer {customer_id} with channel {channel_id}")
    
    return {
        "customer_id": str(customer.id),
        "channel_id": str(channel.id),
        "channel_name": channel.name,
        "channel_type": channel.channel_type,
        "updated_at": datetime.utcnow().isoformat(),
    }


async def get_customer_channel(db: AsyncSession, customer_id: UUID, account_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
    """Get the private channel associated with a customer.

    F-4: when ``account_id`` is supplied the associated channel must belong to it.
    """
    customer_result = await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False)
    )
    customer = customer_result.scalar_one_or_none()
    
    if not customer or not customer.extra_info or "private_channel_id" not in customer.extra_info:
        return None
    
    channel_id = UUID(customer.extra_info["private_channel_id"])
    channel_result = await db.execute(
        select(PrivateChannel).where(
            PrivateChannel.id == channel_id,
            PrivateChannel.is_deleted == False
        )
    )
    channel = channel_result.scalar_one_or_none()
    
    if not channel:
        return None

    _require_channel_ownership(channel, account_id)
    
    return {
        "id": str(channel.id),
        "name": channel.name,
        "channel_type": channel.channel_type,
        "status": channel.status,
        "contact_count": channel.contact_count,
    }


# ==================== NurturePlan Application ====================

async def apply_nurture_plan_to_customer(
    db: AsyncSession,
    plan_id: UUID,
    customer_id: UUID,
    account_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """
    Apply a nurture plan to a specific customer.
    Creates segment membership if needed.

    F-4: when ``account_id`` is supplied the target plan must belong to it.
    """
    # Verify plan exists and is active
    plan_result = await db.execute(
        select(NurturePlan).where(
            NurturePlan.id == plan_id,
            NurturePlan.is_deleted == False
        )
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise ValueError(f"Nurture plan {plan_id} not found")

    _require_plan_ownership(plan, account_id)

    if plan.status != "active":
        raise ValueError(f"Nurture plan {plan_id} is not active (status: {plan.status})")
    
    # Verify customer exists
    customer_result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.is_deleted == False
        )
    )
    customer = customer_result.scalar_one_or_none()
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")
    
    # If plan has a target segment, add customer to segment
    if plan.target_segment_id:
        member_result = await db.execute(
            select(SegmentMember).where(
                SegmentMember.segment_id == plan.target_segment_id,
                SegmentMember.customer_id == customer_id
            )
        )
        if not member_result.scalar_one_or_none():
            # Add to segment
            member = SegmentMember(
                segment_id=plan.target_segment_id,
                customer_id=customer_id,
                added_by="nurture_plan_auto"
            )
            db.add(member)
            logger.info(f"Added customer {customer_id} to segment {plan.target_segment_id} via nurture plan {plan_id}")
    
    # Track plan application
    application_record = {
        "plan_id": str(plan_id),
        "customer_id": str(customer_id),
        "applied_at": datetime.utcnow().isoformat(),
        "status": "applied",
    }
    
    # Update plan performance metrics
    if not plan.performance_metrics:
        plan.performance_metrics = {}
    
    applied_count = plan.performance_metrics.get("applied_count", 0) + 1
    plan.performance_metrics["applied_count"] = applied_count
    plan.performance_metrics["last_applied_at"] = datetime.utcnow().isoformat()
    
    await db.commit()
    await db.refresh(plan)
    
    logger.info(f"Applied nurture plan {plan_id} to customer {customer_id}")
    
    return {
        "success": True,
        "plan": {
            "id": str(plan.id),
            "name": plan.name,
            "status": plan.status,
        },
        "customer": {
            "id": str(customer.id),
            "name": customer.name,
        },
        "applied_at": datetime.utcnow().isoformat(),
        "added_to_segment": bool(plan.target_segment_id),
    }


async def get_customer_nurture_plans(
    db: AsyncSession,
    customer_id: UUID,
) -> List[Dict[str, Any]]:
    """Get all nurture plans applicable to a customer"""
    # Get plans where customer is in target segment
    from sqlalchemy import or_
    
    # Method 1: Customer is directly in the segment
    segment_members_result = await db.execute(
        select(SegmentMember.segment_id).where(
            SegmentMember.customer_id == customer_id
        )
    )
    segment_ids = [row.segment_id for row in segment_members_result.fetchall()]
    
    # Method 2: Plan has no target segment (applies to all)
    plans_result = await db.execute(
        select(NurturePlan).where(
            NurturePlan.is_deleted == False,
            NurturePlan.status == "active",
            or_(
                NurturePlan.target_segment_id.in_(segment_ids) if segment_ids else False,
                NurturePlan.target_segment_id.is_(None)
            )
        )
    )
    plans = plans_result.scalars().all()
    
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "status": p.status,
            "schedule_type": p.schedule_type,
            "target_segment_id": str(p.target_segment_id) if p.target_segment_id else None,
        }
        for p in plans
    ]


# ==================== DealItem-Customer Linkage ====================

async def create_deal_with_customer(
    db: AsyncSession,
    pipeline_id: UUID,
    account_id: UUID,
    customer_id: Optional[UUID] = None,
    lead_id: Optional[UUID] = None,
    name: str = None,
    value: Optional[int] = None,
    owner_account_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """
    Create a deal item with automatic customer/lead linkage.
    If customer_id not provided, tries to infer from lead_id.

    F-4: when ``owner_account_id`` is supplied, the target pipeline must belong
    to it (the router passes the caller's bound account so a client cannot
    create a deal in another account's pipeline via a body-supplied id).
    """
    if owner_account_id is not None:
        from app.db.models.private_domain import DealPipeline
        p_result = await db.execute(
            select(DealPipeline).where(
                DealPipeline.id == pipeline_id, DealPipeline.is_deleted == False
            )
        )
        pipeline = p_result.scalar_one_or_none()
        owner = getattr(pipeline, "account_id", None)
        if owner is not None and UUID(str(owner)) != UUID(str(owner_account_id)):
            raise AccountOwnershipError("deal_pipeline", owner_account_id)

    # If lead_id provided, try to get customer from lead
    if lead_id and not customer_id:
        lead_result = await db.execute(
            select(Lead).where(Lead.id == lead_id, Lead.is_deleted == False)
        )
        lead = lead_result.scalar_one_or_none()
        if lead and lead.customer_id:
            customer_id = lead.customer_id
    
    # Validate customer if provided
    if customer_id:
        customer_result = await db.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.is_deleted == False
            )
        )
        if not customer_result.scalar_one_or_none():
            raise ValueError(f"Customer {customer_id} not found")
    
    # Create deal item
    from app.schemas.private_domain import DealItemCreate
    
    deal_data = DealItemCreate(
        pipeline_id=pipeline_id,
        account_id=account_id,
        customer_id=customer_id,
        lead_id=lead_id,
        name=name or f"Deal for Customer {customer_id}" if customer_id else "New Deal",
        value=value,
    )
    
    deal_item = DealItem(
        pipeline_id=deal_data.pipeline_id,
        account_id=deal_data.account_id,
        customer_id=deal_data.customer_id,
        lead_id=deal_data.lead_id,
        name=deal_data.name,
        description=deal_data.description,
        value=deal_data.value,
        currency=deal_data.currency,
        expected_close_date=deal_data.expected_close_date,
    )
    
    db.add(deal_item)
    await db.commit()
    await db.refresh(deal_item)
    
    return {
        "id": str(deal_item.id),
        "pipeline_id": str(deal_item.pipeline_id),
        "account_id": str(deal_item.account_id),
        "customer_id": str(deal_item.customer_id) if deal_item.customer_id else None,
        "lead_id": str(deal_item.lead_id) if deal_item.lead_id else None,
        "name": deal_item.name,
        "value": deal_item.value,
        "currency": deal_item.currency,
        "status": deal_item.status,
        "created_at": deal_item.created_at.isoformat() if deal_item.created_at else datetime.utcnow().isoformat(),
    }


async def get_customer_deals(
    db: AsyncSession,
    customer_id: UUID,
    account_id: UUID,
) -> List[Dict[str, Any]]:
    """Get all deals associated with a customer"""
    deals_result = await db.execute(
        select(DealItem).where(
            DealItem.customer_id == customer_id,
            DealItem.account_id == account_id,
            DealItem.is_deleted == False
        ).order_by(DealItem.created_at.desc())
    )
    deals = deals_result.scalars().all()
    
    return [
        {
            "id": str(d.id),
            "name": d.name,
            "value": d.value,
            "currency": d.currency,
            "status": d.status,
            "expected_close_date": d.expected_close_date.isoformat() if d.expected_close_date else None,
            "pipeline_id": str(d.pipeline_id),
        }
        for d in deals
    ]


# ==================== Cross-Module Consistency Checks ====================

async def validate_data_consistency(
    db: AsyncSession,
    account_id: UUID,
) -> Dict[str, Any]:
    """
    Validate cross-module data consistency.
    Checks for orphaned references and missing links.
    """
    issues = []
    
    # Check 1: Leads with customer_id pointing to non-existent customers
    leads_result = await db.execute(
        select(Lead).where(
            Lead.customer_id.isnot(None),
            Lead.is_deleted == False
        )
    )
    leads = leads_result.scalars().all()
    
    for lead in leads:
        customer_result = await db.execute(
            select(Customer).where(
                Customer.id == lead.customer_id,
                Customer.is_deleted == False
            )
        )
        if not customer_result.scalar_one_or_none():
            issues.append({
                "type": "orphaned_lead_customer",
                "lead_id": str(lead.id),
                "customer_id": str(lead.customer_id),
                "message": "Lead references non-existent customer",
            })
    
    # Check 2: DealItems with customer_id/lead_id pointing to non-existent records
    deals_result = await db.execute(
        select(DealItem).where(
            DealItem.account_id == account_id,
            DealItem.is_deleted == False,
            DealItem.customer_id.isnot(None)
        )
    )
    deals = deals_result.scalars().all()
    
    for deal in deals:
        customer_result = await db.execute(
            select(Customer).where(
                Customer.id == deal.customer_id,
                Customer.is_deleted == False
            )
        )
        if not customer_result.scalar_one_or_none():
            issues.append({
                "type": "orphaned_deal_customer",
                "deal_id": str(deal.id),
                "customer_id": str(deal.customer_id),
                "message": "Deal references non-existent customer",
            })
    
    # Check 3: NurturePlan target segments that don't exist
    plans_result = await db.execute(
        select(NurturePlan).where(
            NurturePlan.account_id == account_id,
            NurturePlan.target_segment_id.isnot(None),
            NurturePlan.is_deleted == False
        )
    )
    plans = plans_result.scalars().all()
    
    for plan in plans:
        segment_result = await db.execute(
            select(CustomerSegment).where(
                CustomerSegment.id == plan.target_segment_id,
                CustomerSegment.is_deleted == False
            )
        )
        if not segment_result.scalar_one_or_none():
            issues.append({
                "type": "orphaned_plan_segment",
                "plan_id": str(plan.id),
                "segment_id": str(plan.target_segment_id),
                "message": "Nurture plan references non-existent segment",
            })
    
    return {
        "account_id": str(account_id),
        "validated_at": datetime.utcnow().isoformat(),
        "issues_count": len(issues),
        "issues": issues,
        "is_consistent": len(issues) == 0,
    }


async def fix_orphaned_references(
    db: AsyncSession,
    account_id: UUID,
) -> Dict[str, Any]:
    """
    Automatically fix common orphaned reference issues.
    """
    fixes_applied = 0
    
    # Fix 1: Clear customer_id from leads if customer doesn't exist
    leads_result = await db.execute(
        select(Lead).where(
            Lead.customer_id.isnot(None),
            Lead.is_deleted == False
        )
    )
    leads = leads_result.scalars().all()
    
    for lead in leads:
        customer_result = await db.execute(
            select(Customer).where(
                Customer.id == lead.customer_id,
                Customer.is_deleted == False
            )
        )
        if not customer_result.scalar_one_or_none():
            lead.customer_id = None
            lead.status = "new"
            fixes_applied += 1
    
    # Fix 2: Clear customer_id from deals if customer doesn't exist
    deals_result = await db.execute(
        select(DealItem).where(
            DealItem.account_id == account_id,
            DealItem.customer_id.isnot(None),
            DealItem.is_deleted == False
        )
    )
    deals = deals_result.scalars().all()
    
    for deal in deals:
        customer_result = await db.execute(
            select(Customer).where(
                Customer.id == deal.customer_id,
                Customer.is_deleted == False
            )
        )
        if not customer_result.scalar_one_or_none():
            deal.customer_id = None
            fixes_applied += 1
    
    if fixes_applied > 0:
        await db.commit()
        logger.info(f"Fixed {fixes_applied} orphaned references for account {account_id}")
    
    return {
        "account_id": str(account_id),
        "fixes_applied": fixes_applied,
        "fixed_at": datetime.utcnow().isoformat(),
    }


# ==================== Integration Statistics ====================

async def get_integration_stats(
    db: AsyncSession,
    account_id: UUID,
) -> Dict[str, Any]:
    """Get statistics about cross-module integrations"""
    
    # Count leads by status
    leads_result = await db.execute(
        select(Lead.status, func.count()).where(
            Lead.is_deleted == False
        ).group_by(Lead.status)
    )
    leads_by_status = {row[0]: row[1] for row in leads_result.fetchall()}
    
    # Count converted leads
    converted_leads = leads_by_status.get("converted", 0)
    
    # Count customers with private channel
    customers_with_channel = await db.execute(
        select(func.count()).where(
            Customer.is_deleted == False,
            Customer.extra_info['private_channel_id'].is_(None) == False
        )
    )
    customers_with_channel = customers_with_channel.scalar() or 0
    
    # Count deals with customers
    deals_with_customers = await db.execute(
        select(func.count()).where(
            DealItem.account_id == account_id,
            DealItem.is_deleted == False,
            DealItem.customer_id.isnot(None)
        )
    )
    deals_with_customers = deals_with_customers.scalar() or 0
    
    # Count active nurture plans with segments
    active_plans = await db.execute(
        select(func.count()).where(
            NurturePlan.account_id == account_id,
            NurturePlan.is_deleted == False,
            NurturePlan.status == "active",
            NurturePlan.target_segment_id.isnot(None)
        )
    )
    active_plans = active_plans.scalar() or 0
    
    return {
        "account_id": str(account_id),
        "statistics": {
            "leads": {
                "total": sum(leads_by_status.values()),
                "by_status": leads_by_status,
                "converted_count": converted_leads,
            },
            "customers": {
                "with_private_channel": customers_with_channel,
            },
            "deals": {
                "with_customer_link": deals_with_customers,
            },
            "nurture_plans": {
                "active_with_segments": active_plans,
            },
        },
        "calculated_at": datetime.utcnow().isoformat(),
    }
