"""
Private Domain Routers: Private Channel, Nurture Plan, Content Library,
Follow-up Task, Customer Segment, Deal Pipeline

P0-1 / ADR-011 (security):
  * Every endpoint requires a JWT Bearer token (``require_private_domain``) —
    unauthenticated requests are 401.
  * ``account_id`` is derived from the *authenticated* principal, never trusted
    from the client. A client-supplied ``account_id`` that does not match the
    token's account is 403 (cross-account), and create/update/delete body
    ``account_id`` values are overridden with the caller's bound account.
  * All responses that can carry PII are run through :func:`mask_dict` so no
    plaintext phone / email / WeChat-id / credential reaches the client (P0-2).
  * Sensitive create / update / delete operations write an audit row (P1-1).
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.db.session import get_db
from app.security.jwt_auth import (
    PrivateDomainPrincipal,
    require_private_domain,
)
from app.security.masking import mask_dict
from app.security.audit import record_audit, OP_CREATE, OP_UPDATE, OP_DELETE, OP_TRANSITION

from app.services.private_domain import (
    get_private_channels,
    get_private_channel,
    create_private_channel,
    update_private_channel,
    delete_private_channel,
    get_channel_stats,
    update_channel_connection_status,
    get_account_channel_stats,
    get_nurture_plans,
    create_nurture_plan,
    update_nurture_plan,
    delete_nurture_plan,
    get_content_items,
    create_content_item,
    update_content_item,
    delete_content_item,
    get_follow_up_tasks,
    create_follow_up_task,
    update_follow_up_task,
    delete_follow_up_task,
    transition_task_status,
    check_and_update_overdue_tasks,
    get_upcoming_reminders,
    get_follow_up_task_stats,
    get_customer_segments,
    create_customer_segment,
    update_customer_segment,
    delete_customer_segment,
    get_deal_pipelines,
    create_deal_pipeline,
    update_deal_pipeline,
    delete_deal_pipeline,
    get_deal_stages,
    create_deal_stage,
    update_deal_stage,
    delete_deal_stage,
    get_deal_items,
    create_deal_item,
    update_deal_item,
    delete_deal_item,
    transition_deal_item,
    get_deal_pipeline_stats,
    get_deal_pipeline_stats_by_account,
)
from app.services.integration_service import (
    convert_lead_to_customer,
    associate_customer_with_channel,
    get_customer_channel,
    apply_nurture_plan_to_customer,
    get_customer_nurture_plans,
    create_deal_with_customer,
    get_customer_deals,
    validate_data_consistency,
    fix_orphaned_references,
    get_integration_stats,
)
from app.services.nurture_plan_service import (
    get_nurture_plan,
    transition_nurture_plan_status,
    create_nurture_plan_step,
    update_nurture_plan_step,
    delete_nurture_plan_step,
    reorder_nurture_plan_steps,
    get_nurture_plan_stats,
)
from app.services.content_library import (
    search_content_items,
    track_content_usage,
    get_content_usage_stats,
    get_content_type_stats,
    get_content_category_stats,
    get_content_categories,
    get_content_tags,
    get_top_used_content,
    get_content_by_category,
)
from app.services.segment_service import (
    get_customer_segment,
    sync_segment,
    add_segment_member,
    remove_segment_member,
    bulk_add_members,
    get_segment_with_stats,
    get_segment_members,
    get_account_segment_stats,
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
    DealItemTransition,
    LeadConversionRequest,
    LeadConversionResponse,
    CustomerChannelAssociation,
    NurturePlanApplication,
    DealCreationWithCustomer,
    DataConsistencyResult,
    OrphanedReferenceFix,
    IntegrationStats,
)

router = APIRouter(prefix="/private-domain", tags=["private-domain"])

# Default auth dependency: a JWT-bound, account-scoped principal. Every
# private-domain endpoint depends on this, so the surface is unauthenticated-
# free by construction.
principal_dep = Depends(require_private_domain)


def _principal_account(principal: PrivateDomainPrincipal) -> UUID:
    """The caller's owning account (guaranteed non-None by require_private_domain)."""
    assert principal.account_id is not None
    return principal.account_id


# ========== Private Channel Endpoints ==========

@router.get("/channels", summary="List private channels")
async def list_channels(
    channel_type: Optional[str] = Query(None, description="Filter by channel type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    # account_id is the caller's own account (token), never client-supplied.
    return mask_dict(await get_private_channels(db, _principal_account(principal), page, page_size, channel_type, status))


@router.get("/channels/{channel_id}", summary="Get private channel")
async def get_channel(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    channel = await get_private_channel(db, channel_id, _principal_account(principal))
    if not channel:
        raise HTTPException(status_code=404, detail="Private channel not found")
    return mask_dict(channel)


@router.post("/channels", summary="Create private channel", status_code=201)
async def create_channel(
    data: PrivateChannelCreate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    # F-4: the owning account is the caller's, not a body-supplied value.
    data.account_id = _principal_account(principal)
    result = await create_private_channel(db, data)
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="private_channel", operation=OP_CREATE, resource_id=result.get("id"))
    return mask_dict(result)


@router.put("/channels/{channel_id}", summary="Update private channel")
async def update_channel(
    channel_id: UUID,
    data: PrivateChannelUpdate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    account_id = _principal_account(principal)
    channel = await update_private_channel(db, channel_id, account_id, data)
    if not channel:
        raise HTTPException(status_code=404, detail="Private channel not found")
    await record_audit(db, account_id=account_id, principal=principal.principal,
                       resource_type="private_channel", operation=OP_UPDATE, resource_id=channel_id)
    return mask_dict(channel)


@router.delete("/channels/{channel_id}", summary="Delete private channel")
async def delete_channel(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    account_id = _principal_account(principal)
    success = await delete_private_channel(db, channel_id, account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Private channel not found")
    await record_audit(db, account_id=account_id, principal=principal.principal,
                       resource_type="private_channel", operation=OP_DELETE, resource_id=channel_id)
    return {"success": True}


@router.get("/channels/{channel_id}/stats", summary="Get channel statistics")
async def get_channel_stats_endpoint(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    stats = await get_channel_stats(db, channel_id, _principal_account(principal))
    if not stats:
        raise HTTPException(status_code=404, detail="Channel not found")
    return stats


@router.put("/channels/{channel_id}/connection-status", summary="Update channel connection status")
async def update_channel_connection_status_endpoint(
    channel_id: UUID,
    connection_status: str = Query(..., description="Connection status: online/offline/error"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    result = await update_channel_connection_status(db, channel_id, _principal_account(principal), connection_status)
    if not result:
        raise HTTPException(status_code=404, detail="Channel not found")
    return result


@router.get("/account-channel-stats", summary="Get account channel statistics")
async def get_account_channel_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return await get_account_channel_stats(db, _principal_account(principal))


# ========== Nurture Plan Endpoints ==========

@router.get("/nurture-plans", summary="List nurture plans")
async def list_nurture_plans(
    channel_id: Optional[UUID] = Query(None, description="Filter by channel"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    # F-4: list is always scoped to the caller's account (no cross-account read).
    return mask_dict(await get_nurture_plans(db, channel_id, _principal_account(principal), status, page, page_size))


@router.get("/nurture-plans/{plan_id}", summary="Get nurture plan detail")
async def get_nurture_plan_endpoint(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    plan = await get_nurture_plan(db, plan_id, _principal_account(principal))
    if not plan:
        raise HTTPException(status_code=404, detail="Nurture plan not found")
    return mask_dict(plan)


@router.post("/nurture-plans", summary="Create nurture plan", status_code=201)
async def create_nurture_plan_endpoint(
    data: NurturePlanCreate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    # F-4: owning account is the caller's, not a body-supplied value.
    data.account_id = _principal_account(principal)
    result = await create_nurture_plan(db, data)
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="nurture_plan", operation=OP_CREATE, resource_id=result.get("id"))
    return mask_dict(result)


@router.put("/nurture-plans/{plan_id}", summary="Update nurture plan")
async def update_nurture_plan_endpoint(
    plan_id: UUID,
    data: NurturePlanUpdate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    plan = await update_nurture_plan(db, plan_id, data, account_id=_principal_account(principal))
    if not plan:
        raise HTTPException(status_code=404, detail="Nurture plan not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="nurture_plan", operation=OP_UPDATE, resource_id=plan_id)
    return mask_dict(plan)


@router.delete("/nurture-plans/{plan_id}", summary="Delete nurture plan")
async def delete_nurture_plan_endpoint(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    success = await delete_nurture_plan(db, plan_id, account_id=_principal_account(principal))
    if not success:
        raise HTTPException(status_code=404, detail="Nurture plan not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="nurture_plan", operation=OP_DELETE, resource_id=plan_id)
    return {"success": True}


@router.post("/nurture-plans/{plan_id}/transition", summary="Transition nurture plan status")
async def transition_nurture_plan_status_endpoint(
    plan_id: UUID,
    new_status: str = Query(..., description="New status: draft/active/paused/completed/archived"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    try:
        result = await transition_nurture_plan_status(db, plan_id, new_status, account_id=_principal_account(principal))
        if not result:
            raise HTTPException(status_code=404, detail="Nurture plan not found")
        await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                           resource_type="nurture_plan", operation=OP_TRANSITION, resource_id=plan_id,
                           action=new_status, detail={"status": new_status})
        return mask_dict(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/nurture-plans/{plan_id}/steps", summary="Create nurture plan step", status_code=201)
async def create_nurture_plan_step_endpoint(
    plan_id: UUID,
    step_order: int = Query(..., description="Step order"),
    content_id: Optional[UUID] = Query(None, description="Content ID to reference"),
    delay_hours: int = Query(0, ge=0, description="Delay in hours before this step"),
    trigger_type: str = Query("time_based", description="Trigger type"),
    config: Optional[str] = Query(None, description="Step config as JSON string"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    import json
    step_config = json.loads(config) if config else None

    result = await create_nurture_plan_step(
        db,
        plan_id=plan_id,
        step_order=step_order,
        content_id=content_id,
        delay_hours=delay_hours,
        trigger_type=trigger_type,
        config=step_config,
        account_id=_principal_account(principal),
    )
    return mask_dict(result)


@router.put("/nurture-plans/steps/{step_id}", summary="Update nurture plan step")
async def update_nurture_plan_step_endpoint(
    step_id: UUID,
    step_order: Optional[int] = Query(None, description="Step order"),
    content_id: Optional[UUID] = Query(None, description="Content ID"),
    delay_hours: Optional[int] = Query(None, ge=0, description="Delay in hours"),
    trigger_type: Optional[str] = Query(None, description="Trigger type"),
    config: Optional[str] = Query(None, description="Step config as JSON string"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    import json
    update_data = {}
    if step_order is not None:
        update_data["step_order"] = step_order
    if content_id is not None:
        update_data["content_id"] = content_id
    if delay_hours is not None:
        update_data["delay_hours"] = delay_hours
    if trigger_type is not None:
        update_data["trigger_type"] = trigger_type
    if config is not None:
        update_data["config"] = json.loads(config)

    result = await update_nurture_plan_step(db, step_id, update_data, account_id=_principal_account(principal))
    if not result:
        raise HTTPException(status_code=404, detail="Step not found")
    return mask_dict(result)


@router.delete("/nurture-plans/steps/{step_id}", summary="Delete nurture plan step")
async def delete_nurture_plan_step_endpoint(
    step_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    success = await delete_nurture_plan_step(db, step_id, account_id=_principal_account(principal))
    if not success:
        raise HTTPException(status_code=404, detail="Step not found")
    return {"success": True}


@router.post("/nurture-plans/{plan_id}/steps/reorder", summary="Reorder nurture plan steps")
async def reorder_nurture_plan_steps_endpoint(
    plan_id: UUID,
    step_orders: List[dict] = Body(..., description="List of {id, step_order}"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    result = await reorder_nurture_plan_steps(db, plan_id, step_orders, account_id=_principal_account(principal))
    return mask_dict(result)


@router.get("/nurture-plans/{plan_id}/stats", summary="Get nurture plan statistics")
async def get_nurture_plan_stats_endpoint(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    stats = await get_nurture_plan_stats(db, plan_id, account_id=_principal_account(principal))
    if not stats:
        raise HTTPException(status_code=404, detail="Nurture plan not found")
    return stats


# ========== Content Item Endpoints ==========

@router.get("/content-items", summary="List content items")
async def list_content_items(
    channel_id: Optional[UUID] = Query(None, description="Filter by channel"),
    content_type: Optional[str] = Query(None, description="Filter by content type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return mask_dict(await get_content_items(db, _principal_account(principal), channel_id, content_type, status, page, page_size))


@router.post("/content-items", summary="Create content item", status_code=201)
async def create_content_item_endpoint(
    data: ContentItemCreate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    data.account_id = _principal_account(principal)
    result = await create_content_item(db, data)
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="content_item", operation=OP_CREATE, resource_id=result.get("id"))
    return mask_dict(result)


@router.put("/content-items/{item_id}", summary="Update content item")
async def update_content_item_endpoint(
    item_id: UUID,
    data: ContentItemUpdate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    item = await update_content_item(db, item_id, data, account_id=_principal_account(principal))
    if not item:
        raise HTTPException(status_code=404, detail="Content item not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="content_item", operation=OP_UPDATE, resource_id=item_id)
    return mask_dict(item)


@router.delete("/content-items/{item_id}", summary="Delete content item")
async def delete_content_item_endpoint(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    success = await delete_content_item(db, item_id, account_id=_principal_account(principal))
    if not success:
        raise HTTPException(status_code=404, detail="Content item not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="content_item", operation=OP_DELETE, resource_id=item_id)
    return {"success": True}


@router.get("/content-items/search", summary="Search content items")
async def search_content_items_endpoint(
    keyword: Optional[str] = Query(None, description="Search keyword"),
    content_type: Optional[str] = Query(None, description="Filter by content type"),
    category: Optional[str] = Query(None, description="Filter by category"),
    status: Optional[str] = Query(None, description="Filter by status"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    min_usage_count: Optional[int] = Query(None, ge=0, description="Minimum usage count"),
    max_usage_count: Optional[int] = Query(None, ge=0, description="Maximum usage count"),
    date_from: Optional[datetime] = Query(None, description="Filter by start date"),
    date_to: Optional[datetime] = Query(None, description="Filter by end date"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return mask_dict(await search_content_items(
        db, _principal_account(principal), keyword, content_type, category, status, tag,
        min_usage_count, max_usage_count, date_from, date_to,
        sort_by, sort_order, page, page_size
    ))


@router.post("/content-items/{item_id}/track", summary="Track content usage")
async def track_content_usage_endpoint(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    result = await track_content_usage(db, item_id, _principal_account(principal))
    if not result:
        raise HTTPException(status_code=404, detail="Content item not found")
    return result


@router.get("/content-items/{item_id}/stats", summary="Get content usage stats")
async def get_content_usage_stats_endpoint(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    stats = await get_content_usage_stats(db, _principal_account(principal), item_id)
    if not stats or not stats.get("stats"):
        raise HTTPException(status_code=404, detail="Content item not found")
    return stats


@router.get("/content/stats/types", summary="Get content type statistics")
async def get_content_type_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return await get_content_type_stats(db, _principal_account(principal))


@router.get("/content/stats/categories", summary="Get content category statistics")
async def get_content_category_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return await get_content_category_stats(db, _principal_account(principal))


@router.get("/content/categories", summary="Get unique content categories")
async def get_content_categories_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return await get_content_categories(db, _principal_account(principal))


@router.get("/content/tags", summary="Get unique content tags")
async def get_content_tags_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return await get_content_tags(db, _principal_account(principal))


@router.get("/content/top-used", summary="Get top used content items")
async def get_top_used_content_endpoint(
    limit: int = Query(10, ge=1, le=50, description="Limit of items"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return mask_dict(await get_top_used_content(db, _principal_account(principal), limit))


@router.get("/content/by-category/{category}", summary="Get content by category")
async def get_content_by_category_endpoint(
    category: str = Path(..., description="Category name"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return mask_dict(await get_content_by_category(db, _principal_account(principal), category, page, page_size))


# ========== Follow-up Task Endpoints ==========

@router.get("/tasks", summary="List follow-up tasks")
async def list_tasks(
    customer_id: Optional[UUID] = Query(None, description="Filter by customer"),
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[int] = Query(None, ge=0, le=100, description="Minimum priority"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return mask_dict(await get_follow_up_tasks(db, _principal_account(principal), customer_id, status, priority, page, page_size))


@router.post("/tasks", summary="Create follow-up task", status_code=201)
async def create_task_endpoint(
    data: FollowUpTaskCreate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    data.account_id = _principal_account(principal)
    # F-5: audit/attribution (the service stores assigned_to as created_by)
    # defaults to the authenticated identity so it cannot be spoofed.
    if not data.assigned_to:
        data.assigned_to = principal.principal
    result = await create_follow_up_task(db, data)
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="follow_up_task", operation=OP_CREATE, resource_id=result.get("id"))
    return mask_dict(result)


@router.put("/tasks/{task_id}", summary="Update follow-up task")
async def update_task_endpoint(
    task_id: UUID,
    data: FollowUpTaskUpdate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    task = await update_follow_up_task(db, task_id, data, account_id=_principal_account(principal))
    if not task:
        raise HTTPException(status_code=404, detail="Follow-up task not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="follow_up_task", operation=OP_UPDATE, resource_id=task_id)
    return mask_dict(task)


@router.delete("/tasks/{task_id}", summary="Delete follow-up task")
async def delete_task_endpoint(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    success = await delete_follow_up_task(db, task_id, account_id=_principal_account(principal))
    if not success:
        raise HTTPException(status_code=404, detail="Follow-up task not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="follow_up_task", operation=OP_DELETE, resource_id=task_id)
    return {"success": True}


@router.post("/tasks/{task_id}/transition", summary="Transition task status")
async def transition_task_endpoint(
    task_id: UUID,
    new_status: str = Query(..., description="New status"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    try:
        task = await transition_task_status(db, task_id, new_status, _principal_account(principal))
        if not task:
            raise HTTPException(status_code=404, detail="Follow-up task not found")
        await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                           resource_type="follow_up_task", operation=OP_TRANSITION, resource_id=task_id,
                           action=new_status, detail={"status": new_status})
        return mask_dict(task)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tasks/overdue/check", summary="Check and update overdue tasks")
async def check_overdue_tasks_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return await check_and_update_overdue_tasks(db, _principal_account(principal))


@router.get("/tasks/reminders", summary="Get upcoming reminders")
async def get_reminders_endpoint(
    hours_ahead: int = Query(24, ge=1, le=168, description="Hours ahead to check (default 24, max 168)"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return mask_dict(await get_upcoming_reminders(db, _principal_account(principal), hours_ahead))


@router.get("/tasks/stats", summary="Get follow-up task statistics")
async def get_task_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return await get_follow_up_task_stats(db, _principal_account(principal))


# ========== Customer Segment Endpoints ==========

@router.get("/segments", summary="List customer segments")
async def list_segments(
    segment_type: Optional[str] = Query(None, description="Filter by segment type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return mask_dict(await get_customer_segments(db, _principal_account(principal), segment_type, page, page_size))


@router.post("/segments", summary="Create customer segment", status_code=201)
async def create_segment_endpoint(
    data: CustomerSegmentCreate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    data.account_id = _principal_account(principal)
    result = await create_customer_segment(db, data)
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="customer_segment", operation=OP_CREATE, resource_id=result.get("id"))
    return mask_dict(result)


@router.put("/segments/{segment_id}", summary="Update customer segment")
async def update_segment_endpoint(
    segment_id: UUID,
    data: CustomerSegmentUpdate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    segment = await update_customer_segment(db, segment_id, data, account_id=_principal_account(principal))
    if not segment:
        raise HTTPException(status_code=404, detail="Customer segment not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="customer_segment", operation=OP_UPDATE, resource_id=segment_id)
    return mask_dict(segment)


@router.delete("/segments/{segment_id}", summary="Delete customer segment")
async def delete_segment_endpoint(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    success = await delete_customer_segment(db, segment_id, account_id=_principal_account(principal))
    if not success:
        raise HTTPException(status_code=404, detail="Customer segment not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="customer_segment", operation=OP_DELETE, resource_id=segment_id)
    return {"success": True}


# ========== Segment Member Management Endpoints ==========

@router.post("/segments/{segment_id}/members", summary="Add member to segment")
async def add_segment_member_endpoint(
    segment_id: UUID,
    customer_id: UUID = Query(..., description="Customer ID"),
    added_by: Optional[str] = Query(None, description="Explicit operator label (defaults to the authenticated identity)"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    try:
        # F-5: audit attribution is bound to the authenticated principal — a
        # free-text added_by may still override the *label*, but an absent one
        # resolves to the caller's identity, not a forgeable default.
        audit_added_by = added_by if added_by else principal.principal
        result = await add_segment_member(db, segment_id, customer_id, audit_added_by, account_id=_principal_account(principal))
        await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                           resource_type="segment_member", operation=OP_CREATE, resource_id=segment_id,
                           detail={"customer_id": str(customer_id), "added_by": added_by})
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/segments/{segment_id}/members/{customer_id}", summary="Remove member from segment")
async def remove_segment_member_endpoint(
    segment_id: UUID,
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    try:
        result = await remove_segment_member(db, segment_id, customer_id, account_id=_principal_account(principal))
        await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                           resource_type="segment_member", operation=OP_DELETE, resource_id=segment_id,
                           detail={"customer_id": str(customer_id)})
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/segments/{segment_id}/members/bulk", summary="Bulk add members to segment")
async def bulk_add_members_endpoint(
    segment_id: UUID,
    customer_ids: List[UUID] = Query(..., description="Customer IDs to add"),
    added_by: Optional[str] = Query(None, description="Explicit operator label"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    try:
        audit_added_by = added_by if added_by else principal.principal
        result = await bulk_add_members(db, segment_id, customer_ids, audit_added_by, account_id=_principal_account(principal))
        await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                           resource_type="segment_member", operation=OP_CREATE, resource_id=segment_id,
                           detail={"bulk": len(customer_ids)})
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/segments/{segment_id}/members", summary="Get segment members")
async def get_segment_members_endpoint(
    segment_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return mask_dict(await get_segment_members(db, segment_id, page, page_size, account_id=_principal_account(principal)))


# ========== Segment Sync Endpoint ==========

@router.post("/segments/{segment_id}/sync", summary="Sync segment members")
async def sync_segment_endpoint(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    try:
        result = await sync_segment(db, segment_id, account_id=_principal_account(principal))
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ========== Segment Statistics Endpoints ==========

@router.get("/segments/{segment_id}/stats", summary="Get segment statistics")
async def get_segment_stats_endpoint(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    account_id = _principal_account(principal)
    segment = await get_customer_segment(db, segment_id, account_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Customer segment not found")

    stats = await get_segment_with_stats(db, segment_id, account_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Segment statistics not found")

    return mask_dict(stats)


@router.get("/account-segment-stats", summary="Get all segment statistics for account")
async def get_account_segment_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    stats = await get_account_segment_stats(db, _principal_account(principal))
    return mask_dict({"segments": stats})


# ========== Deal Pipeline Endpoints ==========

@router.get("/pipelines", summary="List deal pipelines")
async def list_pipelines(
    pipeline_type: Optional[str] = Query(None, description="Filter by pipeline type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return mask_dict(await get_deal_pipelines(db, _principal_account(principal), pipeline_type, page, page_size))


@router.post("/pipelines", summary="Create deal pipeline", status_code=201)
async def create_pipeline_endpoint(
    data: DealPipelineCreate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    data.account_id = _principal_account(principal)
    result = await create_deal_pipeline(db, data)
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="deal_pipeline", operation=OP_CREATE, resource_id=result.get("id"))
    return mask_dict(result)


@router.put("/pipelines/{pipeline_id}", summary="Update deal pipeline")
async def update_pipeline_endpoint(
    pipeline_id: UUID,
    data: DealPipelineUpdate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    pipeline = await update_deal_pipeline(db, pipeline_id, data, account_id=_principal_account(principal))
    if not pipeline:
        raise HTTPException(status_code=404, detail="Deal pipeline not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="deal_pipeline", operation=OP_UPDATE, resource_id=pipeline_id)
    return mask_dict(pipeline)


@router.delete("/pipelines/{pipeline_id}", summary="Delete deal pipeline")
async def delete_pipeline_endpoint(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    success = await delete_deal_pipeline(db, pipeline_id, account_id=_principal_account(principal))
    if not success:
        raise HTTPException(status_code=404, detail="Deal pipeline not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="deal_pipeline", operation=OP_DELETE, resource_id=pipeline_id)
    return {"success": True}


# ========== Deal Stage Endpoints ==========

@router.get("/pipelines/{pipeline_id}/stages", summary="List deal stages")
async def list_stages(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return mask_dict(await get_deal_stages(db, pipeline_id, account_id=_principal_account(principal)))


@router.post("/pipelines/{pipeline_id}/stages", summary="Create deal stage", status_code=201)
async def create_stage_endpoint(
    pipeline_id: UUID,
    data: DealStageCreate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    data.pipeline_id = pipeline_id
    return mask_dict(await create_deal_stage(db, data, account_id=_principal_account(principal)))


@router.put("/stages/{stage_id}", summary="Update deal stage")
async def update_stage_endpoint(
    stage_id: UUID,
    data: DealStageUpdate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    stage = await update_deal_stage(db, stage_id, data, account_id=_principal_account(principal))
    if not stage:
        raise HTTPException(status_code=404, detail="Deal stage not found")
    return mask_dict(stage)


@router.delete("/stages/{stage_id}", summary="Delete deal stage")
async def delete_stage_endpoint(
    stage_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    success = await delete_deal_stage(db, stage_id, account_id=_principal_account(principal))
    if not success:
        raise HTTPException(status_code=404, detail="Deal stage not found")
    return {"success": True}


# ========== Deal Item Endpoints ==========

@router.get("/deals", summary="List deal items")
async def list_deals(
    pipeline_id: Optional[UUID] = Query(None, description="Filter by pipeline"),
    stage_id: Optional[UUID] = Query(None, description="Filter by stage"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    return mask_dict(await get_deal_items(db, _principal_account(principal), pipeline_id, stage_id, status, page, page_size))


@router.post("/deals", summary="Create deal item", status_code=201)
async def create_deal_endpoint(
    data: DealItemCreate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    data.account_id = _principal_account(principal)
    result = await create_deal_item(db, data)
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="deal_item", operation=OP_CREATE, resource_id=result.get("id"))
    return mask_dict(result)


@router.put("/deals/{item_id}", summary="Update deal item")
async def update_deal_endpoint(
    item_id: UUID,
    data: DealItemUpdate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    item = await update_deal_item(db, item_id, data, account_id=_principal_account(principal))
    if not item:
        raise HTTPException(status_code=404, detail="Deal item not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="deal_item", operation=OP_UPDATE, resource_id=item_id)
    return mask_dict(item)


@router.delete("/deals/{item_id}", summary="Delete deal item")
async def delete_deal_endpoint(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    success = await delete_deal_item(db, item_id, account_id=_principal_account(principal))
    if not success:
        raise HTTPException(status_code=404, detail="Deal item not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="deal_item", operation=OP_DELETE, resource_id=item_id)
    return {"success": True}


# ========== Deal Stage Transition Endpoints ==========

@router.post("/deals/{item_id}/transition", summary="Transition deal item to new stage")
async def transition_deal_endpoint(
    item_id: UUID,
    data: DealItemTransition = Body(...),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """
    Move a deal item to a new stage. Optionally update status and reasons.
    """
    import logging
    if data is None:
        raise HTTPException(status_code=422, detail="Request body is required")
    try:
        result = await transition_deal_item(
            db,
            item_id,
            _principal_account(principal),
            data.stage_id,
            data.status,
            data.winner_reason,
            data.loser_reason,
        )
    except Exception as e:  # F-6: never leak internal detail to the client
        logging.getLogger(__name__).exception("deal transition failed for item=%s", item_id)
        raise HTTPException(status_code=500, detail="deal stage transition failed")
    if result is None:
        raise HTTPException(status_code=404, detail="Deal item not found")
    await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                       resource_type="deal_item", operation=OP_TRANSITION, resource_id=item_id,
                       action=str(data.stage_id), detail={"status": data.status})
    return mask_dict(result)


# ========== Deal Pipeline Statistics Endpoints ==========

@router.get("/pipelines/{pipeline_id}/stats", summary="Get deal pipeline statistics")
async def get_pipeline_stats_endpoint(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """Get funnel statistics for a specific deal pipeline"""
    stats = await get_deal_pipeline_stats(db, pipeline_id, account_id=_principal_account(principal))
    return stats


@router.get("/account-stats", summary="Get all pipeline statistics for account")
async def get_account_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """Get statistics for all pipelines of an account"""
    stats = await get_deal_pipeline_stats_by_account(db, _principal_account(principal))
    return mask_dict({"pipelines": stats})


# ========== Integration Endpoints ==========

@router.post("/integration/leads/{lead_id}/convert", response_model=LeadConversionResponse, summary="Convert Lead to Customer")
async def convert_lead_endpoint(
    lead_id: UUID,
    account_id: Optional[UUID] = Query(None, description="Account ID for authorization (defaults to the caller's)"),
    channel_id: Optional[UUID] = Query(None, description="Private channel to associate"),
    data: LeadConversionRequest = Body(None, description="Conversion detail (email/phone travel in the body, not the URL — F-10)"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """
    Convert a Lead to a Customer and associate with private domain channel.

    F-10: PII (email/phone) is passed in the request body, never in the URL,
    so it does not land in access / gateway logs.
    """
    owner = _principal_account(principal)
    import logging
    try:
        result = await convert_lead_to_customer(
            db,
            lead_id=lead_id,
            account_id=owner,
            channel_id=channel_id,
            name=data.name if data else None,
            email=data.email if data else None,
            phone=data.phone if data else None,
            company=data.company if data else None,
        )
        await record_audit(db, account_id=owner, principal=principal.principal,
                           resource_type="lead", operation=OP_TRANSITION, resource_id=lead_id,
                           action="convert", detail={"customer_id": result.get("customer", {}).get("id")})
        return LeadConversionResponse(**mask_dict(result))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/integration/customers/{customer_id}/channels/{channel_id}", response_model=CustomerChannelAssociation, summary="Associate Customer with Channel")
async def associate_customer_channel_endpoint(
    customer_id: UUID,
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """Associate an existing customer with a private channel."""
    try:
        result = await associate_customer_with_channel(db, customer_id, channel_id, account_id=_principal_account(principal))
        await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                           resource_type="customer_channel", operation=OP_CREATE, resource_id=customer_id,
                           detail={"channel_id": str(channel_id)})
        return CustomerChannelAssociation(**mask_dict(result))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/integration/customers/{customer_id}/channel", summary="Get Customer's Channel")
async def get_customer_channel_endpoint(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """Get the private channel associated with a customer."""
    channel = await get_customer_channel(db, customer_id, account_id=_principal_account(principal))
    if not channel:
        raise HTTPException(status_code=404, detail="Customer has no associated channel")
    return mask_dict(channel)


@router.post("/integration/nurture-plans/{plan_id}/apply", response_model=NurturePlanApplication, summary="Apply Nurture Plan to Customer")
async def apply_nurture_plan_endpoint(
    plan_id: UUID,
    customer_id: UUID = Query(..., description="Customer ID"),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """
    Apply a nurture plan to a specific customer.
    Automatically adds customer to target segment if applicable.
    """
    try:
        result = await apply_nurture_plan_to_customer(db, plan_id, customer_id, account_id=_principal_account(principal))
        await record_audit(db, account_id=_principal_account(principal), principal=principal.principal,
                           resource_type="nurture_plan", operation=OP_TRANSITION, resource_id=plan_id,
                           action="apply", detail={"customer_id": str(customer_id)})
        return NurturePlanApplication(**mask_dict(result))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/integration/customers/{customer_id}/nurture-plans", summary="Get Customer's Nurture Plans")
async def get_customer_nurture_plans_endpoint(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """Get all nurture plans applicable to a customer."""
    plans = await get_customer_nurture_plans(db, customer_id)
    return mask_dict({"plans": plans})


@router.post("/integration/deals", response_model=DealCreationWithCustomer, summary="Create Deal with Customer Linkage")
async def create_deal_with_customer_endpoint(
    data: DealItemCreate,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """
    Create a deal item with automatic customer/lead linkage.
    If lead_id is provided, automatically links to associated customer.
    """
    owner = _principal_account(principal)
    try:
        result = await create_deal_with_customer(
            db,
            pipeline_id=data.pipeline_id,
            account_id=data.account_id or owner,
            customer_id=data.customer_id,
            lead_id=data.lead_id,
            name=data.name,
            value=data.value,
            owner_account_id=owner,
        )
        await record_audit(db, account_id=owner, principal=principal.principal,
                           resource_type="deal_item", operation=OP_CREATE, resource_id=result.get("id"))
        return DealCreationWithCustomer(**mask_dict(result))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/integration/customers/{customer_id}/deals", summary="Get Customer's Deals")
async def get_customer_deals_endpoint(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """Get all deals associated with a customer."""
    deals = await get_customer_deals(db, customer_id, _principal_account(principal))
    return mask_dict({"deals": deals})


@router.get("/integration/consistency/check", response_model=DataConsistencyResult, summary="Validate Data Consistency")
async def validate_consistency_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """
    Validate cross-module data consistency.
    Checks for orphaned references and missing links.
    """
    result = await validate_data_consistency(db, _principal_account(principal))
    return DataConsistencyResult(**mask_dict(result))


@router.post("/integration/consistency/fix", response_model=OrphanedReferenceFix, summary="Fix Orphaned References")
async def fix_references_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """
    Automatically fix common orphaned reference issues.
    """
    result = await fix_orphaned_references(db, _principal_account(principal))
    return OrphanedReferenceFix(**mask_dict(result))


@router.get("/integration/stats", response_model=IntegrationStats, summary="Get Integration Statistics")
async def get_integration_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = principal_dep,
):
    """Get statistics about cross-module integrations."""
    stats = await get_integration_stats(db, _principal_account(principal))
    return IntegrationStats(**mask_dict(stats))
