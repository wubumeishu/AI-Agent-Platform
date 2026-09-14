"""
Lifecycle Stage + Funnel Pipeline Services
基于 SQLAlchemy ORM

Rule-based auto-transition lives in ``app.crm.services.auto``; this module
exposes the stage CRUD + funnel + logging surface and delegates rule
evaluation to the engine.
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.db.models.lifecycle import LifecycleStage, LifecycleStageLog
from app.db.models.lead import Lead

logger = logging.getLogger(__name__)


# ---------------- Domain event publishing (workflow-CRM integration) ----------------
def _publish_stage_changed(lead_id: UUID, old_stage: str, new_stage: str,
                           reason: str, operator: Optional[str]) -> None:
    """Queue a ``lead.stage_changed`` event after a committed stage move.

    ``transition_lifecycle_stage`` mutates the lead's stage directly (not via
    ``update_lead``), so it publishes here. No-op when the stage is unchanged.
    """
    if old_stage == new_stage:
        return
    try:
        from app.services.crm_events import get_crm_publisher

        pub = get_crm_publisher()
        pub.publish_nowait(
            pub.build(
                "lead.stage_changed",
                "lead",
                lead_id,
                {
                    "old_stage": old_stage,
                    "new_stage": new_stage,
                    "reason": reason,
                    "operator": operator,
                },
            )
        )
    except Exception:
        logger.debug("failed to queue lead.stage_changed event", exc_info=True)


# 默认阶段定义
DEFAULT_STAGES = [
    {"code": "陌生", "name": "陌生", "description": "尚未建立联系的潜在客户", "sort_order": 0},
    {"code": "潜客", "name": "潜客", "description": "已建立初步联系，有潜在兴趣", "sort_order": 1},
    {"code": "有效线索", "name": "有效线索", "description": "确认有需求，意向明确", "sort_order": 2},
    {"code": "高意向", "name": "高意向", "description": "强烈购买意向，正在深入沟通", "sort_order": 3},
    {"code": "商机", "name": "商机", "description": "已进入商务谈判阶段", "sort_order": 4},
    {"code": "成交", "name": "成交", "description": "已完成交易", "sort_order": 5},
]


def _stage_to_dict(stage: LifecycleStage) -> dict:
    """统一把 ORM 阶段对象序列化成 API dict。"""
    return {
        "id": str(stage.id),
        "code": stage.code,
        "name": stage.name,
        "description": stage.description,
        "sort_order": stage.sort_order,
        "config": stage.config or {},
        "created_at": stage.created_at.isoformat() if stage.created_at else None,
        "updated_at": stage.updated_at.isoformat() if stage.updated_at else None,
    }


def _validate_config_rules(config: Any) -> None:
    """校验 ``config['rules']``（dict 路径）。

    对每条规则调用 Pydantic ``LifecycleStageRule``，在脏数据进入数据库前
    就抛出 ValueError → 路由转 400。合法/缺省/非 dict 的 config 直接放行。
    """
    if not isinstance(config, dict):
        return
    rules = config.get("rules")
    if not rules:
        return
    from app.schemas.lifecycle import LifecycleStageRule

    for i, rule in enumerate(rules):
        try:
            if isinstance(rule, LifecycleStageRule):
                continue
            LifecycleStageRule(**rule)
        except Exception as exc:  # pydantic.ValidationError is a ValueError
            raise ValueError(f"config.rules[{i}] 校验失败: {exc}")


async def get_lifecycle_stages(db: AsyncSession, active_only: bool = True, skip: int = 0, limit: int = 20) -> List[dict]:
    """获取生命周期阶段列表"""
    query = select(LifecycleStage)
    if active_only:
        query = query.where(LifecycleStage.is_deleted == False)
    query = query.order_by(LifecycleStage.sort_order.asc())
    query = query.offset(skip).limit(limit)
    
    result = await db.execute(query)
    stages = result.scalars().all()
    
    return [_stage_to_dict(s) for s in stages]


async def get_lifecycle_stage(db: AsyncSession, stage_code: str) -> Optional[dict]:
    """获取单个生命周期阶段"""
    result = await db.execute(
        select(LifecycleStage).where(
            LifecycleStage.code == stage_code,
            LifecycleStage.is_deleted == False
        )
    )
    stage = result.scalar_one_or_none()
    
    if not stage:
        return None

    return _stage_to_dict(stage)


async def create_lifecycle_stage(db: AsyncSession, stage_data: Any) -> dict:
    """创建生命周期阶段。

    ``stage_data`` 可以是：
    - ``LifecycleStageCreate``（Pydantic 模型，已校验 rules）
    - 裸 dict（旧式 API，键须为 code/name/description/sort_order/config）

    无论哪条路径，``config.rules``（如存在）都会过 Pydantic 校验，
    拒绝触发器类型不合法 / 缺必填参数的脏规则（400 而非静默入库）。
    """
    if hasattr(stage_data, "to_stage_kwargs"):
        kwargs = stage_data.to_stage_kwargs()
    else:
        kwargs = dict(stage_data)

    _validate_config_rules(kwargs.get("config"))

    # 检查 code 是否已存在
    existing = await db.execute(
        select(LifecycleStage).where(LifecycleStage.code == kwargs["code"])
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"阶段编码 '{kwargs['code']}' 已存在")

    new_stage = LifecycleStage(**kwargs)
    db.add(new_stage)
    await db.commit()
    await db.refresh(new_stage)

    return _stage_to_dict(new_stage)


async def update_lifecycle_stage(db: AsyncSession, stage_code: str, updates: Any) -> dict:
    """更新生命周期阶段。

    ``updates`` 可以是：
    - ``LifecycleStageUpdate``（Pydantic 模型；``auto_transition_rules``
      优先于 ``config``，两者同时提供时写 ``config.rules``）
    - 裸 dict（旧式 API，键须为 ORM 列名）

    ``code`` 与 ``is_deleted`` 不可通过本端点修改。
    """
    result = await db.execute(
        select(LifecycleStage).where(
            LifecycleStage.code == stage_code,
            LifecycleStage.is_deleted == False
        )
    )
    stage = result.scalar_one_or_none()

    if not stage:
        raise ValueError(f"阶段 '{stage_code}' 不存在")

    # Resolve the effective field dict from either the model or the raw dict.
    updatable_fields = ["name", "description", "sort_order", "config"]
    if hasattr(updates, "model_dump"):
        raw = updates.model_dump(exclude_unset=True)
        # auto_transition_rules takes precedence over a flat config blob.
        if raw.get("auto_transition_rules") is not None:
            raw["config"] = {"rules": [r for r in raw.pop("auto_transition_rules")]}
        field_values = {k: v for k, v in raw.items() if k in updatable_fields}
        _validate_config_rules(field_values.get("config"))
    else:
        field_values = {k: v for k, v in updates.items() if k in updatable_fields}
        _validate_config_rules(field_values.get("config"))

    for key, value in field_values.items():
        if value is not None and hasattr(stage, key):
            setattr(stage, key, value)

    await db.commit()
    await db.refresh(stage)

    return _stage_to_dict(stage)


async def delete_lifecycle_stage(db: AsyncSession, stage_code: str) -> bool:
    """删除生命周期阶段（软删除）"""
    result = await db.execute(
        select(LifecycleStage).where(
            LifecycleStage.code == stage_code,
            LifecycleStage.is_deleted == False
        )
    )
    stage = result.scalar_one_or_none()
    
    if not stage:
        return False
    
    stage.is_deleted = True
    await db.commit()
    return True


async def get_lifecycle_stage_logs(
    db: AsyncSession,
    stage_code: str,
    lead_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 20
) -> List[dict]:
    """获取阶段变更日志"""
    query = select(LifecycleStageLog).where(
        LifecycleStageLog.new_stage_code == stage_code
    )
    
    if lead_id:
        query = query.where(LifecycleStageLog.lead_id == lead_id)
    
    query = query.order_by(LifecycleStageLog.created_at.desc())
    query = query.offset(skip).limit(limit)
    
    result = await db.execute(query)
    logs = result.scalars().all()
    
    return [
        {
            "id": str(log.id),
            "lead_id": str(log.lead_id),
            "old_stage_code": log.old_stage_code,
            "new_stage_code": log.new_stage_code,
            "transition_reason": log.transition_reason,
            "operator": log.operator,
            "metadata": log.extra_data or {},
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


async def transition_lifecycle_stage(
    db: AsyncSession, 
    lead_id: UUID, 
    new_stage_code: str, 
    reason: str = "manual", 
    operator: Optional[str] = None, 
    metadata: Optional[dict] = None
) -> dict:
    """执行阶段流转"""
    # 验证 Lead 存在
    lead_result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.is_deleted == False)
    )
    lead = lead_result.scalar_one_or_none()
    
    if not lead:
        raise ValueError(f"Lead {lead_id} 不存在")
    
    old_stage_code = lead.lifecycle_stage_code
    
    # 创建日志记录
    log_entry = LifecycleStageLog(
        lead_id=lead_id,
        old_stage_code=old_stage_code,
        new_stage_code=new_stage_code,
        transition_reason=reason,
        operator=operator,
        extra_data=metadata or {},
    )
    db.add(log_entry)
    
    # 更新 Lead 的阶段
    lead.lifecycle_stage_code = new_stage_code
    
    await db.commit()
    await db.refresh(log_entry)

    _publish_stage_changed(lead_id, old_stage_code, new_stage_code, reason, operator)

    return {
        "id": str(log_entry.id),
        "lead_id": str(log_entry.lead_id),
        "old_stage_code": log_entry.old_stage_code,
        "new_stage_code": log_entry.new_stage_code,
        "transition_reason": log_entry.transition_reason,
        "operator": log_entry.operator,
        "metadata": log_entry.extra_data or {},
        "created_at": log_entry.created_at.isoformat() if log_entry.created_at else None,
    }


async def get_funnel_stats(db: AsyncSession) -> List[dict]:
    """获取商机漏斗统计数据。

    两条查询：活跃阶段 + 各阶段 Lead 数量（单次 GROUP BY，避免 N+1）。
    """
    stages_result = await db.execute(
        select(LifecycleStage).where(
            LifecycleStage.is_deleted == False
        ).order_by(LifecycleStage.sort_order.asc())
    )
    stages = stages_result.scalars().all()

    if not stages:
        return []

    # 单次 GROUP BY 一次性取回所有阶段计数
    counts_result = await db.execute(
        select(Lead.lifecycle_stage_code, func.count(Lead.id))
        .where(Lead.is_deleted == False)
        .group_by(Lead.lifecycle_stage_code)
    )
    counts = {row[0]: row[1] for row in counts_result.all()}

    return [
        {
            "code": stage.code,
            "name": stage.name,
            "sort_order": stage.sort_order,
            "customer_count": counts.get(stage.code, 0),
        }
        for stage in stages
    ]


async def init_default_stages(db: AsyncSession):
    """初始化默认生命周期阶段"""
    existing = await db.execute(
        select(LifecycleStage).where(LifecycleStage.is_deleted == False).limit(1)
    )
    if existing.scalar_one_or_none():
        return
    
    for stage_data in DEFAULT_STAGES:
        stage = LifecycleStage(**stage_data)
        db.add(stage)
    
    await db.commit()
    logger.info(f"Initialized {len(DEFAULT_STAGES)} default lifecycle stages")
