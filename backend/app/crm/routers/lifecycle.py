"""
CRM Routers: Lifecycle Stage + Funnel Pipeline

NOTE (t_b6b64212): This file used to live at app/crm/routers.py, which is
SHADOWED by the app/crm/routers/ package and therefore never imported or
registered. It was moved here so the lifecycle routes actually reach the
app. Sub-routers carry only their module segment; main.py's
include_router(..., prefix="/api/v1") adds the /api/v1 prefix exactly once.
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
from uuid import UUID

from app.db.session import get_db
from app.schemas.lifecycle import (
    LifecycleStageCreate,
    LifecycleStageUpdate,
    LifecycleTransitionRequest,
    FunnelResponse,
    FunnelStageStat,
)

router = APIRouter(prefix="/crm/lifecycle", tags=["Lifecycle"])


@router.get("/stages", response_model=List[dict])
async def list_lifecycle_stages(
    active_only: bool = Query(True, description="只返回未删除的阶段"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db = Depends(get_db),
):
    """列出所有生命周期阶段"""
    from app.crm.services import get_lifecycle_stages
    return await get_lifecycle_stages(db, active_only=active_only, skip=skip, limit=limit)


@router.post("/stages", response_model=dict, status_code=201)
async def create_stage(stage_data: LifecycleStageCreate, db = Depends(get_db)):
    """创建生命周期阶段（可自定义名称、顺序与自动流转规则）"""
    from app.crm.services import create_lifecycle_stage
    try:
        return await create_lifecycle_stage(db, stage_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stages/{stage_code}", response_model=dict)
async def get_stage(stage_code: str, db = Depends(get_db)):
    """获取单个生命周期阶段"""
    from app.crm.services import get_lifecycle_stage
    stage = await get_lifecycle_stage(db, stage_code)
    if not stage:
        raise HTTPException(status_code=404, detail="阶段不存在")
    return stage


@router.put("/stages/{stage_code}", response_model=dict)
async def update_stage(stage_code: str, stage_update: LifecycleStageUpdate, db = Depends(get_db)):
    """更新生命周期阶段（名称 / 顺序 / 描述 / 自动流转规则）"""
    from app.crm.services import update_lifecycle_stage
    try:
        return await update_lifecycle_stage(db, stage_code, stage_update)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/stages/{stage_code}", status_code=204)
async def delete_stage(stage_code: str, db = Depends(get_db)):
    """删除生命周期阶段（软删除）"""
    from app.crm.services import delete_lifecycle_stage
    success = await delete_lifecycle_stage(db, stage_code)
    if not success:
        raise HTTPException(status_code=404, detail="阶段不存在")


@router.get("/stages/{stage_code}/logs", response_model=List[dict])
async def get_stage_logs(
    stage_code: str,
    lead_id: Optional[UUID] = Query(None, description="按 Lead ID 筛选"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db = Depends(get_db),
):
    """获取阶段变更日志"""
    from app.crm.services import get_lifecycle_stage_logs
    return await get_lifecycle_stage_logs(db, stage_code, lead_id=lead_id, skip=skip, limit=limit)


@router.post("/stages/transition", response_model=dict)
async def transition_stage(
    body: LifecycleTransitionRequest,
    db = Depends(get_db),
):
    """执行阶段流转（手动指定目标阶段）"""
    from app.crm.services import transition_lifecycle_stage
    try:
        return await transition_lifecycle_stage(
            db,
            body.lead_id,
            body.new_stage_code,
            body.reason,
            body.operator,
            body.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stages/auto-transition", response_model=dict)
async def auto_transition_stage(
    lead_id: UUID,
    db = Depends(get_db),
):
    """按已配置的自动流转规则评估并流转单个 Lead。

    规则来源：各阶段 ``config.rules``（``intent_score`` / ``status_change``
    / ``conversation_activity`` 三类触发器）。无命中或 Lead 已在目标阶段时
    ``applied`` 为空数组。
    """
    from sqlalchemy import select
    from app.db.models.lead import Lead
    from app.crm.services.auto import apply_auto_transitions

    lead_result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.is_deleted == False)
    )
    lead = lead_result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead 不存在")

    applied = await apply_auto_transitions(db, lead)
    return {"lead_id": str(lead_id), "applied": applied}


@router.get("/funnel", response_model=FunnelResponse)
async def get_funnel(db = Depends(get_db)):
    """获取商机漏斗统计数据（各阶段客户数量 + 转化率）"""
    from app.crm.services import get_funnel_stats
    stats = await get_funnel_stats(db)

    # 附转化率：相对第一个阶段（漏斗顶部）的累计通过率
    top_count = stats[0]["customer_count"] if stats else 0
    for s in stats:
        s["conversion_rate"] = round(s["customer_count"] / top_count, 4) if top_count else 0.0

    return {"code": 0, "message": "success", "data": stats}
