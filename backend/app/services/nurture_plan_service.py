"""
Enhanced Nurture Plan Service with step management and state transitions
"""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete
from sqlalchemy.exc import IntegrityError

from app.db.models.private_domain import (
    NurturePlan,
    NurturePlanItem,
    CustomerSegment,
    PlanStatus,
)
from app.schemas.private_domain import (
    NurturePlanCreate,
    NurturePlanUpdate,
)
from app.security.jwt_auth import AccountOwnershipError


def _require_plan_ownership(plan: Any, account_id: Optional[UUID]) -> None:
    """F-4: a plan-scoped write must target a plan owned by the caller's
    account (no-op when ``account_id`` is ``None``)."""
    if account_id is None or plan is None:
        return
    owner = getattr(plan, "account_id", None)
    if owner is not None and UUID(str(owner)) != UUID(str(account_id)):
        raise AccountOwnershipError("nurture_plan", account_id)


# ========== helpers ==========

def _coerce_step_uuid(value: Any) -> Optional[UUID]:
    """Lenient UUID coercion for step dicts arriving from JSON payloads.

    Empty strings / non-UUID strings become None (a step without a valid
    content reference is still valid); a well-formed UUID string is accepted.
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return UUID(value.strip())
        except ValueError:
            return None
    return None


def _coerce_delay_hours(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


async def _reconcile_plan_items(
    db: AsyncSession,
    plan_id: UUID,
    steps: List[Dict[str, Any]],
) -> List[NurturePlanItem]:
    """Reconcile nurture_plan_item rows for a plan against the requested steps.

    - upsert by step_order (existing active row updated, missing row created)
    - surplus active rows are soft-deleted (is_deleted=True)

    Single transaction with the caller (commits are owned by the caller).
    Called with the list of step dicts from the legacy sequence_steps payload.
    """
    items_result = await db.execute(
        select(NurturePlanItem).where(
            NurturePlanItem.plan_id == plan_id,
            NurturePlanItem.is_deleted == False,
        )
    )
    existing = {s.step_order: s for s in items_result.scalars().all()}

    new_order = [
        i if isinstance(step.get("step_order"), int) and not isinstance(step.get("step_order"), bool)
        else int(step.get("step_order")) if step.get("step_order") is not None
        else i
        for i, step in enumerate(steps)
    ]

    for order, step in zip(new_order, steps):
        if order in existing:
            item = existing.pop(order)
            item.content_id = _coerce_step_uuid(step.get("content_id"))
            item.delay_hours = _coerce_delay_hours(step.get("delay_hours", 0))
            item.trigger_type = str(step.get("trigger_type") or "time_based")
            item.config = step.get("config") or {}
            item.status = "active"
        else:
            item = NurturePlanItem(
                plan_id=plan_id,
                step_order=order,
                content_id=_coerce_step_uuid(step.get("content_id")),
                delay_hours=_coerce_delay_hours(step.get("delay_hours", 0)),
                trigger_type=str(step.get("trigger_type") or "time_based"),
                config=step.get("config") or {},
            )
            db.add(item)
            # NOTE: do NOT add the freshly-created row back to `existing`.
            # `existing` tracks *prior active rows* that were not requested;
            # re-adding new rows would make the surplus sweep below soft-delete
            # them, which would defeat the single-source-of-truth contract
            # (Contract B: create must leave N live rows in the table).

    # Surplus active rows: soft-delete (retained for audit).
    # `existing` now holds only prior rows whose step_order was not requested.
    for order, item in existing.items():
        item.is_deleted = True

    result = await db.execute(
        select(NurturePlanItem).where(
            NurturePlanItem.plan_id == plan_id,
            NurturePlanItem.is_deleted == False,
        ).order_by(NurturePlanItem.step_order.asc())
    )
    return list(result.scalars().all())


def _steps_payload(steps: List[NurturePlanItem]) -> List[Dict[str, Any]]:
    """Serialize plan step rows for API responses (single source of truth)."""
    return [
        {
            "id": s.id,
            "plan_id": s.plan_id,
            "step_order": s.step_order,
            "content_id": s.content_id,
            "delay_hours": s.delay_hours,
            "trigger_type": s.trigger_type,
            "config": s.config,
            "status": s.status,
            "created_at": s.created_at,
        }
        for s in steps
    ]


async def reconcile_sequence_steps(
    db: AsyncSession,
    plan_id: UUID,
    steps: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Reconcile a legacy ``sequence_steps`` payload into the SoT table.

    Contract B (t_1814d03d / t_4b55abe8): the step definitions live in the
    ``nurture_plan_item`` table (single source of truth). Incoming legacy
    ``sequence_steps`` payloads are upserted by ``step_order``; the legacy
    ``nurture_plan.sequence_steps`` JSON column is never written (stays []).

    ``steps=None`` means "not provided" - no reconcile, returns [].

    Shared by the enhanced service and the legacy private_domain service so
    both entry points honour the same contract.
    """
    if not steps:
        return []
    items = await _reconcile_plan_items(db, plan_id, steps)
    return _steps_payload(items)


# ========== NurturePlan Service (Enhanced) ==========

async def get_nurture_plan(
    db: AsyncSession,
    plan_id: UUID,
    account_id: Optional[UUID] = None,
) -> Optional[Dict[str, Any]]:
    """Get a single nurture plan by ID with related steps.

    F-4: when ``account_id`` is supplied, a plan owned by another account
    raises :class:`AccountOwnershipError` (-> 403) rather than a bare 404,
    so the API does not leak which accounts exist.
    """
    result = await db.execute(
        select(NurturePlan).where(
            NurturePlan.id == plan_id,
            NurturePlan.is_deleted == False,
        )
    )
    plan = result.scalar_one_or_none()
    
    if not plan:
        return None

    _require_plan_ownership(plan, account_id)

    # Get related steps ordered by step_order (active rows only)
    steps_result = await db.execute(
        select(NurturePlanItem).where(
            NurturePlanItem.plan_id == plan_id,
            NurturePlanItem.is_deleted == False,
        ).order_by(NurturePlanItem.step_order.asc())
    )
    steps = steps_result.scalars().all()
    
    return {
        "id": plan.id,
        "channel_id": plan.channel_id,
        "account_id": plan.account_id,
        "name": plan.name,
        "description": plan.description,
        "status": plan.status,
        "schedule_type": plan.schedule_type,
        "schedule_config": plan.schedule_config,
        "trigger_conditions": plan.trigger_conditions,
        "target_segment_id": plan.target_segment_id,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        # Single source of truth: steps come from the nurture_plan_item table.
        # The legacy plan.sequence_steps JSON column is no longer returned
        # (ruling t_1814d03d / t_4b55abe8).
        "steps": _steps_payload(list(steps)),
    }


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
                # Legacy plan.sequence_steps JSON column is no longer exposed;
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

    Contract B (t_1814d03d / t_4b55abe8): the legacy ``sequence_steps``
    payload is reconciled into ``nurture_plan_item`` rows in the same
    transaction; the legacy JSON column is written as [] and never used as
    a data source again.
    """
    plan = NurturePlan(
        channel_id=data.channel_id,
        account_id=data.account_id,
        name=data.name,
        description=data.description,
        schedule_type=data.schedule_type,
        schedule_config=data.schedule_config or {},
        sequence_steps=[],  # legacy column retired - steps live in nurture_plan_item
        trigger_conditions=data.trigger_conditions or [],
        target_segment_id=data.target_segment_id,
    )
    db.add(plan)
    await db.flush()  # materialise plan.id; commit is owned by the caller flow below

    # Only reconcile when steps were actually supplied: a plan with no
    # sequence_steps has zero item rows, so the pre/post sweeps would be two
    # pointless SELECTs (and would break the no-steps path on callers that
    # do not run a real DB).
    steps_rows = []
    if data.sequence_steps:
        steps_rows = await _reconcile_plan_items(db, plan.id, list(data.sequence_steps))

    await db.commit()
    await db.refresh(plan)

    return {
        "id": plan.id,
        "channel_id": plan.channel_id,
        "account_id": plan.account_id,
        "name": plan.name,
        "description": plan.description,
        "status": plan.status,
        "schedule_type": plan.schedule_type,
        "schedule_config": plan.schedule_config,
        # Single source of truth: steps from the nurture_plan_item table.
        # The legacy sequence_steps JSON column is [] and no longer exposed.
        "steps": _steps_payload(list(steps_rows)),
        "trigger_conditions": plan.trigger_conditions,
        "target_segment_id": plan.target_segment_id,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


async def update_nurture_plan(
    db: AsyncSession, 
    plan_id: UUID, 
    data: NurturePlanUpdate,
    account_id: Optional[UUID] = None,
) -> Optional[Dict[str, Any]]:
    """Update a nurture plan.

    Contract B (t_1814d03d / t_4b55abe8): if the legacy ``sequence_steps``
    payload is provided, the ``nurture_plan_item`` rows are reconciled in
    the same transaction (upsert by step_order, surplus rows soft-deleted).
    The legacy JSON column is never written.

    F-4: ownership-checked when ``account_id`` is given.
    """
    result = await db.execute(
        select(NurturePlan).where(
            NurturePlan.id == plan_id, 
            NurturePlan.is_deleted == False
        )
    )
    plan = result.scalar_one_or_none()
    
    if not plan:
        return None
    
    _require_plan_ownership(plan, account_id)

    update_data = data.model_dump(exclude_unset=True)
    # Legacy sequence_steps is routed to the SoT table, never the JSON column.
    sequence_steps = update_data.pop("sequence_steps", None)
    for field, value in update_data.items():
        setattr(plan, field, value)
    
    steps_rows = []
    if sequence_steps is not None:
        plan.sequence_steps = []  # keep legacy column empty (retired)
        steps_rows = await _reconcile_plan_items(db, plan_id, list(sequence_steps))
    
    plan.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(plan)
    
    return {
        "id": plan.id,
        "channel_id": plan.channel_id,
        "account_id": plan.account_id,
        "name": plan.name,
        "description": plan.description,
        "status": plan.status,
        "schedule_type": plan.schedule_type,
        "schedule_config": plan.schedule_config,
        "steps": _steps_payload(list(steps_rows)),
        "trigger_conditions": plan.trigger_conditions,
        "target_segment_id": plan.target_segment_id,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


async def delete_nurture_plan(db: AsyncSession, plan_id: UUID, account_id: Optional[UUID] = None) -> bool:
    """Soft delete a nurture plan. F-4: ownership-checked when ``account_id`` is given."""
    result = await db.execute(
        select(NurturePlan).where(
            NurturePlan.id == plan_id, 
            NurturePlan.is_deleted == False
        )
    )
    plan = result.scalar_one_or_none()
    
    if not plan:
        return False
    
    _require_plan_ownership(plan, account_id)

    plan.is_deleted = True
    plan.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return True


# ========== State Transition Logic ==========

async def transition_nurture_plan_status(
    db: AsyncSession,
    plan_id: UUID,
    new_status: str,
    account_id: Optional[UUID] = None,
) -> Optional[Dict[str, Any]]:
    """
    Transition nurture plan status with validation.

    Valid transitions:
    - draft -> active, paused, archived
    - active -> paused, completed, archived
    - paused -> active, completed, archived
    - completed -> archived
    - archived -> (no outgoing transitions, final state)

    F-4: ownership-checked when ``account_id`` is given.
    """
    # Validate target status
    valid_statuses = [s.value for s in PlanStatus]
    if new_status not in valid_statuses:
        raise ValueError(f"Invalid status '{new_status}'. Must be one of: {valid_statuses}")
    
    # Get current plan
    result = await db.execute(
        select(NurturePlan).where(
            NurturePlan.id == plan_id,
            NurturePlan.is_deleted == False
        )
    )
    plan = result.scalar_one_or_none()
    
    if not plan:
        return None

    _require_plan_ownership(plan, account_id)
    
    current_status = plan.status
    
    # Validate transition
    valid_transitions = {
        PlanStatus.DRAFT.value: [PlanStatus.ACTIVE.value, PlanStatus.PAUSED.value, PlanStatus.ARCHIVED.value],
        PlanStatus.ACTIVE.value: [PlanStatus.PAUSED.value, PlanStatus.COMPLETED.value, PlanStatus.ARCHIVED.value],
        PlanStatus.PAUSED.value: [PlanStatus.ACTIVE.value, PlanStatus.COMPLETED.value, PlanStatus.ARCHIVED.value],
        PlanStatus.COMPLETED.value: [PlanStatus.ARCHIVED.value],
        PlanStatus.ARCHIVED.value: [],  # Final state
    }
    
    allowed_transitions = valid_transitions.get(current_status, [])
    if new_status not in allowed_transitions:
        raise ValueError(
            f"Cannot transition from '{current_status}' to '{new_status}'. "
            f"Allowed transitions: {allowed_transitions}"
        )
    
    # Execute transition
    plan.status = new_status
    plan.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(plan)
    
    return {
        "id": plan.id,
        "channel_id": plan.channel_id,
        "account_id": plan.account_id,
        "name": plan.name,
        "description": plan.description,
        "status": plan.status,
        "previous_status": current_status,
        "schedule_type": plan.schedule_type,
        "schedule_config": plan.schedule_config,
        # Legacy sequence_steps JSON column is retired (Contract B); steps live
        # in the nurture_plan_item table. Not a step-modifying call, so no
        # steps payload here.
        "trigger_conditions": plan.trigger_conditions,
        "target_segment_id": plan.target_segment_id,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


# ========== NurturePlanItem (Step) Service ==========

async def create_nurture_plan_step(
    db: AsyncSession,
    plan_id: UUID,
    step_order: int,
    content_id: Optional[UUID] = None,
    delay_hours: int = 0,
    trigger_type: str = "time_based",
    config: Optional[Dict[str, Any]] = None,
    account_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Create a new step in a nurture plan. F-4: plan ownership checked when ``account_id`` is given."""
    # Verify plan exists
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
    
    # Create step
    step = NurturePlanItem(
        plan_id=plan_id,
        step_order=step_order,
        content_id=content_id,
        delay_hours=delay_hours,
        trigger_type=trigger_type,
        config=config or {},
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)
    
    return {
        "id": step.id,
        "plan_id": step.plan_id,
        "step_order": step.step_order,
        "content_id": step.content_id,
        "delay_hours": step.delay_hours,
        "trigger_type": step.trigger_type,
        "config": step.config,
        "status": step.status,
        "created_at": step.created_at,
    }


async def update_nurture_plan_step(
    db: AsyncSession,
    step_id: UUID,
    data: Dict[str, Any],
    account_id: Optional[UUID] = None,
) -> Optional[Dict[str, Any]]:
    """Update a nurture plan step. F-4: plan ownership checked when ``account_id`` is given."""
    result = await db.execute(
        select(NurturePlanItem).where(NurturePlanItem.id == step_id)
    )
    step = result.scalar_one_or_none()
    
    if not step:
        return None
    
    if account_id is not None:
        plan_result = await db.execute(
            select(NurturePlan).where(
                NurturePlan.id == step.plan_id, NurturePlan.is_deleted == False
            )
        )
        _require_plan_ownership(plan_result.scalar_one_or_none(), account_id)
    
    for field, value in data.items():
        if value is not None and hasattr(step, field):
            setattr(step, field, value)
    
    await db.commit()
    await db.refresh(step)
    
    return {
        "id": step.id,
        "plan_id": step.plan_id,
        "step_order": step.step_order,
        "content_id": step.content_id,
        "delay_hours": step.delay_hours,
        "trigger_type": step.trigger_type,
        "config": step.config,
        "status": step.status,
        "created_at": step.created_at,
    }


async def delete_nurture_plan_step(db: AsyncSession, step_id: UUID, account_id: Optional[UUID] = None) -> bool:
    """Delete a nurture plan step. F-4: plan ownership checked when ``account_id`` is given."""
    result = await db.execute(
        select(NurturePlanItem).where(NurturePlanItem.id == step_id)
    )
    step = result.scalar_one_or_none()
    
    if not step:
        return False
    
    if account_id is not None:
        plan_result = await db.execute(
            select(NurturePlan).where(
                NurturePlan.id == step.plan_id, NurturePlan.is_deleted == False
            )
        )
        _require_plan_ownership(plan_result.scalar_one_or_none(), account_id)

    await db.delete(step)
    await db.commit()
    return True


async def reorder_nurture_plan_steps(
    db: AsyncSession,
    plan_id: UUID,
    step_orders: List[Dict[str, Any]],
    account_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """
    Reorder steps in a nurture plan.

    step_orders: List of {id: UUID, step_order: int}

    F-4: plan ownership checked when ``account_id`` is given.
    """
    # Verify plan exists
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

    # Update step orders
    for order_data in step_orders:
        step_id = order_data.get("id")
        new_order = order_data.get("step_order")
        
        if not step_id or new_order is None:
            continue
        
        step_result = await db.execute(
            select(NurturePlanItem).where(
                NurturePlanItem.id == step_id,
                NurturePlanItem.plan_id == plan_id
            )
        )
        step = step_result.scalar_one_or_none()
        if step:
            step.step_order = new_order
    
    await db.commit()
    
    # Return updated steps
    steps_result = await db.execute(
        select(NurturePlanItem).where(
            NurturePlanItem.plan_id == plan_id
        ).order_by(NurturePlanItem.step_order.asc())
    )
    steps = steps_result.scalars().all()
    
    return {
        "plan_id": plan_id,
        "steps": [
            {
                "id": s.id,
                "step_order": s.step_order,
                "content_id": s.content_id,
                "delay_hours": s.delay_hours,
                "trigger_type": s.trigger_type,
            }
            for s in steps
        ],
    }


async def get_nurture_plan_stats(
    db: AsyncSession,
    plan_id: UUID,
    account_id: Optional[UUID] = None,
) -> Optional[Dict[str, Any]]:
    """Get statistics for a nurture plan. F-4: ownership-checked when ``account_id`` is given."""
    # Verify plan exists
    result = await db.execute(
        select(NurturePlan).where(
            NurturePlan.id == plan_id,
            NurturePlan.is_deleted == False
        )
    )
    plan = result.scalar_one_or_none()
    
    if not plan:
        return None

    _require_plan_ownership(plan, account_id)
    
    # Get step counts
    steps_result = await db.execute(
        select(func.count()).where(
            NurturePlanItem.plan_id == plan_id
        )
    )
    total_steps = steps_result.scalar() or 0
    
    # Get active steps count
    active_steps_result = await db.execute(
        select(func.count()).where(
            NurturePlanItem.plan_id == plan_id,
            NurturePlanItem.status == "active"
        )
    )
    active_steps = active_steps_result.scalar() or 0
    
    # Get completed steps count (if we track completion)
    completed_steps_result = await db.execute(
        select(func.count()).where(
            NurturePlanItem.plan_id == plan_id,
            NurturePlanItem.status == "completed"
        )
    )
    completed_steps = completed_steps_result.scalar() or 0
    
    return {
        "plan_id": plan_id,
        "plan_name": plan.name,
        "status": plan.status,
        "total_steps": total_steps,
        "active_steps": active_steps,
        "completed_steps": completed_steps,
        "schedule_type": plan.schedule_type,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }
