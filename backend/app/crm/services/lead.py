"""
Lead Service: CRUD + Conversation Integration
实现 Conversation → Lead 自动转换、重复检测、手动触发
基于 SQLAlchemy ORM
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from app.db.models.lead import Lead
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.lifecycle import LifecycleStage

logger = logging.getLogger(__name__)


# ---------------- Domain event publishing (workflow-CRM integration) ----------------
# Publishes AFTER commit, never blocks the caller, and can be fully disabled
# by not importing the workflow-CRM subscriber. Failures are logged only.

def _publish_lead_created(lead: "Lead") -> None:
    """Queue a ``lead.created`` domain event for the lead just persisted."""
    try:
        from app.services.crm_events import get_crm_publisher

        pub = get_crm_publisher()
        pub.publish_nowait(
            pub.build(
                "lead.created",
                "lead",
                lead.id,
                {
                    "status": lead.status,
                    "lifecycle_stage_code": lead.lifecycle_stage_code,
                    "customer_id": str(lead.customer_id) if lead.customer_id else None,
                    "source_type": lead.source_type,
                },
            )
        )
    except Exception:
        logger.debug("failed to queue lead.created event", exc_info=True)


def _publish_lead_status_changed(lead: "Lead", old_status: str, operator: Optional[str] = None) -> None:
    """Queue a ``lead.status_changed`` event after the status move committed."""
    try:
        from app.services.crm_events import get_crm_publisher

        pub = get_crm_publisher()
        pub.publish_nowait(
            pub.build(
                "lead.status_changed",
                "lead",
                lead.id,
                {
                    "old_status": old_status,
                    "new_status": lead.status,
                    "operator": operator,
                },
            )
        )
    except Exception:
        logger.debug("failed to queue lead.status_changed event", exc_info=True)


def _publish_lead_stage_changed(lead: "Lead", old_stage: str, operator: Optional[str] = None) -> None:
    """Queue a ``lead.stage_changed`` event after the stage move committed."""
    try:
        from app.services.crm_events import get_crm_publisher
    except Exception:
        logger.debug("crm_events import failed in _publish_lead_stage_changed")
        return
    try:
        pub = get_crm_publisher()
        pub.publish_nowait(
            pub.build(
                "lead.stage_changed",
                "lead",
                lead.id,
                {
                    "old_stage": old_stage,
                    "new_stage": lead.lifecycle_stage_code,
                    "operator": operator,
                },
            )
        )
    except Exception:
        logger.debug("failed to queue lead.stage_changed event", exc_info=True)

# ---------------- Intent scoring configuration ----------------
# Single source of truth for the intent-scoring algorithm. Routers expose
# these values via ``GET /intent-config`` so operators can inspect the
# active configuration; tests may monkeypatch the module constants.

# 高意向判断阈值
HIGH_INTENT_THRESHOLD = 70
MEDIUM_INTENT_THRESHOLD = 60
INTENT_SCORE_MIN = 0
INTENT_SCORE_MAX = 100
# 基准分（未应用任何对话信号前的初始分）
INTENT_BASE_SCORE = 50

# Dimension bonuses applied inside calculate_intent_score:
#   conversation_quality -> message-count bonus (>20 msgs: 30, >10 msgs: 20)
#   interaction_frequency -> duration bonus (>600s: 30, >300s: 20)
#   response_time -> reserved, not yet wired (response-latency tracking is a
#   Phase 2 conversation feature); contributes 0 in V1
#   sentiment -> positive: 20, neutral: 10
INTENT_SCORE_WEIGHTS = {
    "conversation_quality": 0.4,
    "interaction_frequency": 0.3,
    "response_time": 0.2,
    "sentiment": 0.1,
}

# 合法的状态流转
VALID_STATUS_TRANSITIONS = {
    "new": ["contacted"],
    "contacted": ["qualified", "new"],
    "qualified": ["converted", "contacted"],
    "converted": [],  # 终态，不可再流转
}


async def get_lead(db: AsyncSession, lead_id: UUID) -> Optional[dict]:
    """获取单个 Lead"""
    result = await db.execute(
        select(Lead)
        .options(
            selectinload(Lead.tags),
            selectinload(Lead.lifecycle_logs)
        )
        .where(Lead.id == lead_id, Lead.is_deleted == False)
    )
    lead = result.scalar_one_or_none()
    
    if not lead:
        return None
    
    return {
        "id": str(lead.id),
        "customer_id": str(lead.customer_id) if lead.customer_id else None,
        "lifecycle_stage_code": lead.lifecycle_stage_code,
        "intent_score": lead.intent_score,
        "source_type": lead.source_type,
        "source_id": lead.source_id,
        "status": lead.status,
        "notes": lead.notes,
        "operator": lead.operator,
        "tags": [
            {"id": str(t.id), "name": t.name, "color": t.color}
            for t in lead.tags
        ],
        "lifecycle_logs": [
            {
                "id": str(l.id),
                "old_stage_code": l.old_stage_code,
                "new_stage_code": l.new_stage_code,
                "transition_reason": l.transition_reason,
                "operator": l.operator,
                "metadata": l.extra_data or {},
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in lead.lifecycle_logs
        ],
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }


async def list_leads(
    db: AsyncSession,
    customer_id: Optional[UUID] = None,
    status: Optional[str] = None,
    lifecycle_stage: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> Dict[str, Any]:
    """列出 Lead 列表（支持筛选、分页）"""
    query = select(Lead).where(Lead.is_deleted == False)
    
    if customer_id:
        query = query.where(Lead.customer_id == customer_id)
    
    if status:
        query = query.where(Lead.status == status)
    
    if lifecycle_stage:
        query = query.where(Lead.lifecycle_stage_code == lifecycle_stage)
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # 分页
    query = query.order_by(Lead.created_at.desc()).offset(skip).limit(limit)
    
    result = await db.execute(
        query
        .options(selectinload(Lead.tags))
    )
    leads = result.scalars().all()
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "data": [
            {
                "id": str(l.id),
                "customer_id": str(l.customer_id) if l.customer_id else None,
                "lifecycle_stage_code": l.lifecycle_stage_code,
                "intent_score": l.intent_score,
                "source_type": l.source_type,
                "source_id": l.source_id,
                "status": l.status,
                "tags": [
                    {"id": str(t.id), "name": t.name}
                    for t in l.tags
                ],
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ],
    }


async def create_lead(db: AsyncSession, lead_data: dict) -> dict:
    """创建 Lead（手动或程序化）"""
    # 验证状态合法性
    status = lead_data.get("status", "new")
    valid_statuses = ["new", "contacted", "qualified", "converted"]
    if status not in valid_statuses:
        raise ValueError(f"无效的状态值，有效值为: {', '.join(valid_statuses)}")
    
    # 验证来源类型
    # "workflow" is a valid attribution source: the Phase 4 workflow-crm
    # executor (WorkflowCrmExecutor._action_create_lead) creates leads with
    # source_type="workflow" for lead-follow-up automation. Keep it in the
    # whitelist or every default workflow create_lead action fails with a
    # business-rule rejection (t_fbeb5e48 P1).
    source_type = lead_data.get("source_type")
    valid_source_types = ["platform", "account", "agent", "campaign", "conversation", "manual", "workflow"]
    if source_type and source_type not in valid_source_types:
        raise ValueError(f"无效的来源类型，有效值为: {', '.join(valid_source_types)}")

    # ``LeadCreate`` ships ``tags=None`` by default and the router forwards
    # ``model_dump()`` verbatim; a None relationship value makes the ORM
    # constructor raise. Drop the key when it is empty (creation-time tag
    # linking is handled by the tag service / a follow-up API call, not here).
    if lead_data.get("tags") is None:
        lead_data = {k: v for k, v in lead_data.items() if k != "tags"}

    new_lead = Lead(**lead_data)
    db.add(new_lead)
    await db.commit()
    await db.refresh(new_lead)
    
    logger.info(f"Created lead: {new_lead.id}, customer={lead_data.get('customer_id')}")
    _publish_lead_created(new_lead)
    return await get_lead(db, new_lead.id)


async def update_lead(db: AsyncSession, lead_id: UUID, updates: dict) -> Optional[dict]:
    """更新 Lead"""
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.is_deleted == False)
    )
    lead = result.scalar_one_or_none()

    if not lead:
        return None

    # 验证状态流转
    old_status = lead.status
    old_stage = lead.lifecycle_stage_code
    if "status" in updates and updates["status"] is not None:
        current_status = lead.status
        new_status = updates["status"]
        valid_next = VALID_STATUS_TRANSITIONS.get(current_status, [])
        if new_status not in valid_next:
            raise ValueError(
                f"状态流转无效: 当前状态 '{current_status}' 不能直接流转到 '{new_status}'"
            )

    updatable_fields = ["lifecycle_stage_code", "intent_score", "status", "notes", "operator"]

    for key, value in updates.items():
        if key in updatable_fields and value is not None:
            setattr(lead, key, value)

    lead.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(lead)

    # Queue domain events only when something actually changed (idempotent
    # semantics: no-op updates do not fire workflows).
    operator = updates.get("operator")
    if lead.status != old_status:
        _publish_lead_status_changed(lead, old_status, operator)
    if lead.lifecycle_stage_code != old_stage:
        _publish_lead_stage_changed(lead, old_stage, operator)

    # Auto-transition: when the update moved the lead's *signals* (status or
    # intent_score), re-evaluate the configured stage rules. A stage that was
    # explicitly set in this call is excluded so the rule that produced it
    # cannot immediately bounce it back.
    signals_changed = lead.status != old_status or (
        "intent_score" in updates and updates.get("intent_score") is not None
    )
    if signals_changed:
        await _apply_auto_transitions_after_update(db, lead, skip_stages=[lead.lifecycle_stage_code])

    logger.info(f"Updated lead: {lead_id}")
    return await get_lead(db, lead_id)


async def _apply_auto_transitions_after_update(db, lead, skip_stages=None):
    """Evaluate lifecycle auto-transition rules after a lead update.

    Isolated so the main update path stays readable and so the rule engine
    (and its conversation-activity provider) can be injected/tested. Failures
    are logged but not propagated: an auto-transition must never corrupt the
    already-committed field update that triggered it.
    """
    try:
        from app.crm.services.auto import apply_auto_transitions

        applied = await apply_auto_transitions(db, lead, skip_stages=skip_stages)
        if applied:
            logger.info(
                "auto-transition applied for lead %s: %s -> %s",
                lead.id,
                applied[0]["old_stage_code"],
                applied[0]["new_stage_code"],
            )
    except ValueError:
        # Lead no longer exists or an invalid transition — not a bug in the
        # update path; log and keep the committed update intact.
        logger.warning("auto-transition could not be applied for lead %s", lead.id, exc_info=True)
    except Exception:
        logger.exception("auto-transition evaluation failed for lead %s", lead.id)


async def delete_lead(db: AsyncSession, lead_id: UUID) -> bool:
    """删除 Lead（软删除）"""
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.is_deleted == False)
    )
    lead = result.scalar_one_or_none()
    
    if not lead:
        return False
    
    lead.is_deleted = True
    await db.commit()
    
    logger.info(f"Deleted lead: {lead_id}")
    return True


async def create_lead_from_conversation(
    db: AsyncSession,
    conversation_id: UUID,
    auto_link_customer: bool = True,
    allow_customer_duplicate: bool = True,
) -> Optional[dict]:
    """
    从 Conversation 创建/复用 Lead
    当对话识别为高意向时调用此函数

    ``allow_customer_duplicate`` (CRM+Conversation 集成 t_crm_007):
      - True  (默认, 手动触发/批量回填): 仅做 per-conversation 去重。
        同一对话再次触发返回已存在的那条（幂等）；同一客户的 *另一*
        对话仍允许再建一条 Lead（人工可覆盖自动去重）。
      - False (自动触发路径, 见 ConversationLeadBridge): 额外做客户级去重。
        若该客户的某条对话 *已经* 产生过 conversation 来源 Lead，则复用
        那条而不新建 —— 保证「同一客户不会因多轮高意向对话被反复
        创建 Lead」。
    """
    # 获取对话信息
    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.is_deleted == False)
    )
    conversation = conv_result.scalar_one_or_none()

    if not conversation:
        raise ValueError(f"对话 {conversation_id} 不存在")

    # 检查是否已经为此对话创建过 Lead
    existing = await db.execute(
        select(Lead).where(
            and_(
                Lead.source_type == "conversation",
                Lead.source_id == str(conversation_id),
                Lead.is_deleted == False,
            )
        )
    )
    existing_lead = existing.scalar_one_or_none()

    if existing_lead:
        logger.info(f"Lead already exists for conversation {conversation_id}")
        return await get_lead(db, existing_lead.id)

    # 客户级去重 (自动触发路径): 该客户的另一条对话若已有 conversation
    # 来源 Lead，则复用那条而不是重复创建。
    if not allow_customer_duplicate and conversation.customer_id is not None:
        cust_dup = await db.execute(
            select(Lead)
            .where(
                and_(
                    Lead.customer_id == conversation.customer_id,
                    Lead.source_type == "conversation",
                    Lead.is_deleted == False,
                )
            )
            .limit(1)
        )
        cust_dup_lead = cust_dup.scalars().first()
        if cust_dup_lead is not None:
            logger.info(
                f"Customer {conversation.customer_id} already has a "
                f"conversation-source lead {cust_dup_lead.id}; reusing it "
                f"instead of creating a duplicate for conversation {conversation_id}"
            )
            return await get_lead(db, cust_dup_lead.id)

    # 确定生命周期阶段
    lifecycle_stage = "潜客"
    intent_score = conversation.metadata_.get("intent_score", 50) if conversation.metadata_ else 50
    sentiment = conversation.sentiment

    # 根据情感评分调整阶段
    if intent_score >= HIGH_INTENT_THRESHOLD or sentiment == "positive":
        lifecycle_stage = "高意向"
    elif intent_score >= 60:
        lifecycle_stage = "有效线索"

    # 客户关联：Conversation.customer_id 是 NOT NULL 外键，每个对话天然
    # 归属一个客户，Lead 直接继承该客户（架构分离：客户↔身份归并由
    # Customer/CustomerIdentity 模块负责，本服务只负责 Lead 落库）。
    #
    # ``auto_link_customer`` 参数保留在签名上以保持 API 兼容：
    # - True (默认): Lead.customer_id = 对话的客户（自动关联）。
    # - False       : Lead.customer_id = None（解绑，用于匿名线索场景）。
    customer_id = conversation.customer_id if auto_link_customer else None

    # 创建 Lead
    lead_data = {
        "customer_id": customer_id,
        "lifecycle_stage_code": lifecycle_stage,
        "intent_score": intent_score,
        "source_type": "conversation",
        "source_id": str(conversation_id),
        "status": "new",
        "notes": f"自动从对话创建，来源：{conversation.subject or '无主题'}",
        "operator": "system",
    }

    new_lead = Lead(**lead_data)
    db.add(new_lead)
    await db.commit()
    await db.refresh(new_lead)

    # 与 create_lead 保持一致：Lead 落库后发布 domain event（workflow-crm
    # 集成可据此触发下游自动化）。publish 失败不影响请求。
    _publish_lead_created(new_lead)

    logger.info(f"Created lead from conversation {conversation_id}: {new_lead.id}, customer={customer_id}")
    return await get_lead(db, new_lead.id)


async def check_duplicate_lead_for_customer(
    db: AsyncSession,
    customer_id: UUID,
    source_type: str = "conversation",
) -> bool:
    """客户级重复 Lead 检测。

    判断该客户是否 *已存在* 一条未删除的 ``source_type`` 来源 Lead
    （默认 conversation 来源）。用于 CRM+Conversation 集成保证「同一
    客户不会因多轮高意向对话被反复创建 Lead」：

    - 单条对话重复（同一 conversation_id 再次触发）→ 由
      ``create_lead_from_conversation`` 的 per-conversation 去重拦截，
      返回已存在的那条（幂等）。
    - 跨对话重复（该客户在 *另一个* 对话已产生 Lead）→ 由本函数拦截，
      自动触发路径（ConversationLeadBridge）据此跳过创建；手动触发路径
      仍允许运营显式创建（人工覆盖自动去重）。
    """
    if customer_id is None:
        return False
    result = await db.execute(
        select(Lead)
        .where(
            and_(
                Lead.customer_id == customer_id,
                Lead.source_type == source_type,
                Lead.is_deleted == False,  # noqa: E712
            )
        )
        .limit(1)
    )
    return result.scalars().first() is not None


async def check_duplicate_lead(
    db: AsyncSession,
    customer_id: UUID,
    source_type: str,
    source_id: str,
) -> bool:
    """
    检查是否已存在重复 Lead
    """
    result = await db.execute(
        select(Lead).where(
            and_(
                Lead.customer_id == customer_id,
                Lead.source_type == source_type,
                Lead.source_id == source_id,
                Lead.is_deleted == False,
            )
        )
    )
    return result.scalar_one_or_none() is not None


async def auto_generate_leads_for_conversations(
    db: AsyncSession,
    min_intent_score: int = HIGH_INTENT_THRESHOLD,
) -> int:
    """
    批量为高意向对话生成 Lead
    返回创建的 Lead 数量
    """
    # 查找所有已被关联到 Lead 的对话 ID
    existing_leads_result = await db.execute(
        select(Lead.source_id)
        .where(Lead.source_type == "conversation", Lead.is_deleted == False)
    )
    existing_source_ids = {row[0] for row in existing_leads_result.fetchall()}
    # Lead.source_id is stored as TEXT (uuid string). Conversation.id is a
    # PGUUID column, so filtering ``~Conversation.id.in_(...)`` needs real
    # UUIDs (comparing a uuid column to text raises an operator type error
    # in Postgres). Coerce defensively: any un-parseable id is skipped.
    existing_conv_uuids = []
    for raw in existing_source_ids:
        try:
            existing_conv_uuids.append(UUID(raw))
        except (ValueError, TypeError):
            continue

    # 查找所有未被关联到 Lead 的高意向对话
    conversations_result = await db.execute(
        select(Conversation)
        .where(
            and_(
                Conversation.status == "active",
                Conversation.is_deleted == False,
                Conversation.sentiment.in_(["positive", "neutral"]),
                # 排除已有 Lead 的对话
                (~Conversation.id.in_(existing_conv_uuids)) if existing_conv_uuids else True,
            )
        )
    )
    conversations = conversations_result.scalars().all()
    
    created_count = 0
    for conversation in conversations:
        metadata = conversation.metadata_ or {}
        intent_score = metadata.get("intent_score", 50)
        
        if intent_score >= min_intent_score:
            await create_lead_from_conversation(db, conversation.id)
            created_count += 1
    
    logger.info(f"Auto-generated {created_count} leads from conversations")
    return created_count


# ==================== Intent Scoring ====================


async def calculate_intent_score(
    db: AsyncSession,
    conversation_id: UUID,
) -> int:
    """
    基于对话质量计算意向分数
    实现策略:
    - 对话时长 (>5min: +20, >10min: +30)
    - 消息数量 (>10条: +20, >20条: +30)
    - 客户响应速度 (快: +10)
    - 情感分析 (positive: +20, neutral: +10)

    阈值与权重取自模块级配置常量（HIGH_INTENT_THRESHOLD、
    INTENT_SCORE_MIN/MAX、INTENT_SCORE_WEIGHTS 等），测试可通过
    monkeypatch 覆盖，生产可通过配置层注入。
    """
    conv_result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id, Conversation.is_deleted == False)
    )
    conversation = conv_result.scalar_one_or_none()

    if not conversation:
        return INTENT_BASE_SCORE  # 默认中等分数

    score = INTENT_BASE_SCORE  # 基准分

    # 对话时长评分
    if conversation.duration_seconds:
        if conversation.duration_seconds > 600:  # 10分钟
            score += 30
        elif conversation.duration_seconds > 300:  # 5分钟
            score += 20

    # 消息数量评分
    message_count = len(conversation.messages) if conversation.messages else 0
    if message_count > 20:
        score += 30
    elif message_count > 10:
        score += 20

    # 情感评分
    sentiment = conversation.sentiment
    if sentiment == "positive":
        score += 20
    elif sentiment == "neutral":
        score += 10

    # 限制在 [INTENT_SCORE_MIN, INTENT_SCORE_MAX] 范围内
    return max(INTENT_SCORE_MIN, min(INTENT_SCORE_MAX, score))


async def get_leads_by_customer(
    db: AsyncSession,
    customer_id: UUID,
) -> List[dict]:
    """获取客户的所有 Lead"""
    result = await db.execute(
        select(Lead)
        .options(selectinload(Lead.tags))
        .where(
            and_(
                Lead.customer_id == customer_id,
                Lead.is_deleted == False,
            )
        )
        .order_by(Lead.created_at.desc())
    )
    leads = result.scalars().all()
    
    return [
        {
            "id": str(l.id),
            # t_fbeb5e48 P1: LeadResponse requires customer_id/operator/
            # created_at/updated_at — the dict omitted customer_id & operator,
            # so the router's LeadResponse(**lead) raised ValidationError -> 500
            # on GET /crm/leads/customer/{id}/leads whenever a customer had
            # any lead. Populate every required field from the model.
            "customer_id": str(l.customer_id) if l.customer_id else None,
            "lifecycle_stage_code": l.lifecycle_stage_code,
            "intent_score": l.intent_score,
            "source_type": l.source_type,
            "source_id": l.source_id,
            "status": l.status,
            "notes": l.notes,
            "operator": l.operator,
            "tags": [
                {"id": str(t.id), "name": t.name, "color": t.color}
                for t in l.tags
            ],
            "created_at": l.created_at.isoformat() if l.created_at else None,
            "updated_at": l.updated_at.isoformat() if l.updated_at else None,
        }
        for l in leads
    ]
