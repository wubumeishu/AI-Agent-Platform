"""
Lead Router: CRUD + Conversation Integration
提供 Lead 管理 API 和 Conversation → Lead 自动转换接口

响应格式遵循 PHASE1-API-SPEC.md 通用规范:
    成功: {"code": 0, "message": "success", "data": ...}
    失败: HTTP 4xx/5xx + {"code": <业务错误码>, "message": <说明>}
    (4001 资源不存在 / 4002 参数错误)

路由顺序约定: 静态路径 (duplicate-check / intent-config / customer/{id}/leads /
auto-generate / from-conversation) 必须先于动态 /{lead_id} 注册, 否则会被 UUID
参数捕获并返回 422 校验错误。
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
from uuid import UUID

from app.db.session import get_db
from app.crm.services.lead import HIGH_INTENT_THRESHOLD
from app.schemas.lead import (
    LeadCreate,
    LeadUpdate,
    LeadResponse,
    LeadListResponse,
    LeadStatusTransition,
    IntentScoreConfig,
)

router = APIRouter(prefix="/crm/leads", tags=["Lead"])


# ==================== 响应封装 (PHASE1-API-SPEC 通用格式) ====================


def _ok(data) -> dict:
    """成功响应统一信封: code=0, message=success, data=载荷。"""
    return {"code": 0, "message": "success", "data": data}


def _to_error(status_code: int, biz_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": biz_code, "message": message})


# ==================== 静态路径 (必须先于 /{lead_id} 注册) ====================


@router.get("", response_model=dict, summary="列出 Lead 列表")
async def list_leads(
    customer_id: Optional[UUID] = Query(None, description="按客户筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    lifecycle_stage: Optional[str] = Query(None, description="按生命周期阶段筛选"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db = Depends(get_db),
):
    """列出 Lead 列表（支持筛选、分页）"""
    from app.crm.services.lead import list_leads as list_leads_service

    result = await list_leads_service(db, customer_id, status, lifecycle_stage, skip, limit)
    return _ok(LeadListResponse(**result).model_dump(mode="json"))


@router.post("", response_model=dict, status_code=201, summary="创建 Lead")
async def create_lead(lead_data: LeadCreate, db = Depends(get_db)):
    """创建 Lead"""
    from app.crm.services.lead import create_lead as create_lead_service

    try:
        lead = await create_lead_service(db, lead_data.model_dump())
        return _ok(LeadResponse(**lead).model_dump(mode="json"))
    except ValueError as e:
        raise _to_error(400, 4002, str(e))


@router.post("/from-conversation/{conversation_id}", response_model=dict, status_code=201, summary="从对话创建 Lead")
async def create_lead_from_conversation(
    conversation_id: UUID,
    auto_link_customer: bool = Query(True, description="自动关联客户"),
    dedup_customer: bool = Query(False, description="客户级去重: 该客户已有 conversation 来源 Lead 时复用而不新建 (默认关, 手动触发允许人工覆盖自动去重)"),
    db = Depends(get_db),
):
    """
    手动从对话创建 Lead
    当检测到高意向对话时调用

    参数:
    - auto_link_customer: True (默认) Lead 继承对话的客户; False 解绑 (匿名线索)。
    - dedup_customer: True 时启用客户级去重 —— 该客户已有一条 conversation
      来源 Lead 则复用那条而不新建。默认 False: 手动触发保留人工覆盖自动
      去重的能力 (同一客户可因 *另一* 条对话再建一条 Lead)。自动触发路径
      (intent.classified -> ConversationLeadBridge) 始终按客户级去重处理。
    """
    from app.crm.services.lead import create_lead_from_conversation as create_service

    try:
        lead = await create_service(
            db,
            conversation_id,
            auto_link_customer,
            allow_customer_duplicate=not dedup_customer,
        )
        return _ok(LeadResponse(**lead).model_dump(mode="json"))
    except ValueError as e:
        raise _to_error(400, 4002, str(e))


@router.post("/auto-generate", response_model=dict, summary="批量自动生成 Lead")
async def auto_generate_leads(
    min_intent_score: int = Query(HIGH_INTENT_THRESHOLD, ge=0, le=100, description="最低意向分数阈值"),
    db = Depends(get_db),
):
    """
    批量为高意向对话自动生成 Lead
    可由定时任务或后台服务调用
    """
    from app.crm.services.lead import auto_generate_leads_for_conversations

    created_count = await auto_generate_leads_for_conversations(db, min_intent_score)
    return _ok({"created_count": created_count})


@router.get("/duplicate-check", response_model=dict, summary="检查重复 Lead")
async def check_duplicate_lead(
    customer_id: UUID = Query(..., description="客户 ID"),
    source_type: str = Query("conversation", description="来源类型"),
    source_id: str = Query(..., description="来源 ID"),
    db = Depends(get_db),
):
    """
    检查是否存在重复 Lead
    """
    from app.crm.services.lead import check_duplicate_lead as check_service

    is_duplicate = await check_service(db, customer_id, source_type, source_id)
    return _ok({"is_duplicate": is_duplicate})


@router.get("/customer/{customer_id}/duplicate-check", response_model=dict, summary="客户级重复 Lead 检测")
async def check_duplicate_lead_for_customer(
    customer_id: UUID,
    source_type: str = Query("conversation", description="来源类型 (默认 conversation)"),
    db = Depends(get_db),
):
    """
    判断该客户是否 *已存在* 一条 conversation 来源的未删除 Lead。
    用于 CRM+Conversation 集成保证「同一客户不会因多轮高意向对话被
    反复创建 Lead」：自动触发路径据此跳过；手动触发路径仍允许运营显式
    创建（人工覆盖自动去重）。
    """
    from app.crm.services.lead import check_duplicate_lead_for_customer as check_service

    is_duplicate = await check_service(db, customer_id, source_type)
    return _ok(
        {
            "customer_id": str(customer_id),
            "source_type": source_type,
            "is_duplicate": is_duplicate,
        }
    )


@router.get("/customer/{customer_id}/leads", response_model=dict, summary="获取客户的所有 Lead")
async def get_customer_leads(
    customer_id: UUID,
    db = Depends(get_db),
):
    """获取客户的所有 Lead"""
    from app.crm.services.lead import get_leads_by_customer

    leads = await get_leads_by_customer(db, customer_id)
    return _ok([LeadResponse(**lead).model_dump(mode="json") for lead in leads])


@router.get("/intent-config", response_model=dict, summary="获取 Intent Score 配置")
async def get_intent_config():
    """获取 Intent Score 计算配置（阈值 + 各维度权重）"""
    from app.crm.services import lead as lead_service

    config = IntentScoreConfig(
        threshold_high=lead_service.HIGH_INTENT_THRESHOLD,
        threshold_medium=lead_service.MEDIUM_INTENT_THRESHOLD,
        max_score=lead_service.INTENT_SCORE_MAX,
        weights=lead_service.INTENT_SCORE_WEIGHTS,
    )
    return _ok(config.model_dump(mode="json"))


# ==================== 动态路径 /{lead_id} (必须最后注册) ====================


@router.get("/{lead_id}", response_model=dict, summary="获取 Lead 详情")
async def get_lead(lead_id: UUID, db = Depends(get_db)):
    """获取单个 Lead 详情"""
    from app.crm.services.lead import get_lead as get_lead_service

    lead = await get_lead_service(db, lead_id)
    if not lead:
        raise _to_error(404, 4001, "Lead 不存在")
    return _ok(LeadResponse(**lead).model_dump(mode="json"))


@router.put("/{lead_id}", response_model=dict, summary="更新 Lead")
async def update_lead(lead_id: UUID, updates: LeadUpdate, db = Depends(get_db)):
    """更新 Lead"""
    from app.crm.services.lead import update_lead as update_lead_service

    try:
        lead = await update_lead_service(db, lead_id, updates.model_dump(exclude_unset=True))
    except ValueError as e:
        # 状态流转等业务规则冲突 -> 参数/状态错误
        raise _to_error(400, 4002, str(e))
    if not lead:
        raise _to_error(404, 4001, "Lead 不存在")
    return _ok(LeadResponse(**lead).model_dump(mode="json"))


@router.delete("/{lead_id}", status_code=204, summary="删除 Lead")
async def delete_lead(lead_id: UUID, db = Depends(get_db)):
    """删除 Lead（软删除）"""
    from app.crm.services.lead import delete_lead as delete_lead_service

    success = await delete_lead_service(db, lead_id)
    if not success:
        raise _to_error(404, 4001, "Lead 不存在")


@router.post("/{lead_id}/transition", response_model=dict, summary="状态流转")
async def transition_lead_status(
    lead_id: UUID,
    transition: LeadStatusTransition,
    db = Depends(get_db),
):
    """
    Lead 状态流转（New → Contacted → Qualified → Converted）

    Request Body:
    - new_status: 目标状态
    - reason: 流转原因（可选）
    - operator: 操作人（可选）
    """
    from app.crm.services.lead import update_lead

    valid_statuses = ["new", "contacted", "qualified", "converted"]
    if transition.new_status not in valid_statuses:
        raise _to_error(400, 4002, f"无效的状态值，有效值为: {', '.join(valid_statuses)}")

    updates: dict = {"status": transition.new_status}
    if transition.reason:
        updates["notes"] = f"[{transition.reason}]"
    if transition.operator:
        updates["operator"] = transition.operator

    try:
        lead = await update_lead(db, lead_id, updates)
    except ValueError as e:
        # 非法状态流转（业务规则）-> 参数/状态错误
        raise _to_error(400, 4002, str(e))
    if not lead:
        raise _to_error(404, 4001, "Lead 不存在")

    return _ok(LeadResponse(**lead).model_dump(mode="json"))
