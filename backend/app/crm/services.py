"""
CRM Services: Lifecycle Stage + Funnel Pipeline
基于 SQLAlchemy ORM
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

# 默认阶段定义
DEFAULT_STAGES = [
    {"code": "陌生", "name": "陌生", "description": "尚未建立联系的潜在客户", "sort_order": 0},
    {"code": "潜客", "name": "潜客", "description": "已建立初步联系，有潜在兴趣", "sort_order": 1},
    {"code": "有效线索", "name": "有效线索", "description": "确认有需求，意向明确", "sort_order": 2},
    {"code": "高意向", "name": "高意向", "description": "强烈购买意向，正在深入沟通", "sort_order": 3},
    {"code": "商机", "name": "商机", "description": "已进入商务谈判阶段", "sort_order": 4},
    {"code": "成交", "name": "成交", "description": "已完成交易", "sort_order": 5},
]


async def get_lifecycle_stages(db: AsyncSession, active_only: bool = True, skip: int = 0, limit: int = 20) -> List[dict]:
    """获取生命周期阶段列表"""
    query = select(LifecycleStage)
    if active_only:
        query = query.where(LifecycleStage.is_deleted == False)
    query = query.order_by(LifecycleStage.sort_order.asc())
    query = query.offset(skip).limit(limit)
    
    result = await db.execute(query)
    stages = result.scalars().all()
    
    return [
        {
            "id": str(s.id),
            "code": s.code,
            "name": s.name,
            "description": s.description,
            "sort_order": s.sort_order,
            "config": s.config or {},
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in stages
    ]


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


async def create_lifecycle_stage(db: AsyncSession, stage_data: dict) -> dict:
    """创建生命周期阶段"""
    # 检查 code 是否已存在
    existing = await db.execute(
        select(LifecycleStage).where(LifecycleStage.code == stage_data["code"])
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"阶段编码 '{stage_data['code']}' 已存在")
    
    new_stage = LifecycleStage(**stage_data)
    db.add(new_stage)
    await db.commit()
    await db.refresh(new_stage)
    
    return {
        "id": str(new_stage.id),
        "code": new_stage.code,
        "name": new_stage.name,
        "description": new_stage.description,
        "sort_order": new_stage.sort_order,
        "config": new_stage.config or {},
        "created_at": new_stage.created_at.isoformat() if new_stage.created_at else None,
        "updated_at": new_stage.updated_at.isoformat() if new_stage.updated_at else None,
    }


async def update_lifecycle_stage(db: AsyncSession, stage_code: str, updates: dict) -> dict:
    """更新生命周期阶段"""
    result = await db.execute(
        select(LifecycleStage).where(
            LifecycleStage.code == stage_code,
            LifecycleStage.is_deleted == False
        )
    )
    stage = result.scalar_one_or_none()
    
    if not stage:
        raise ValueError(f"阶段 '{stage_code}' 不存在")
    
    for key, value in updates.items():
        if value is not None and hasattr(stage, key):
            setattr(stage, key, value)
    
    await db.commit()
    await db.refresh(stage)
    
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
    """获取商机漏斗统计数据"""
    # 查询所有活跃阶段
    stages_result = await db.execute(
        select(LifecycleStage).where(
            LifecycleStage.is_deleted == False
        ).order_by(LifecycleStage.sort_order.asc())
    )
    stages = stages_result.scalars().all()
    
    funnel_stats = []
    for stage in stages:
        # 统计该阶段的 Lead 数量
        count_result = await db.execute(
            select(func.count()).where(
                and_(
                    Lead.lifecycle_stage_code == stage.code,
                    Lead.is_deleted == False
                )
            )
        )
        count = count_result.scalar() or 0
        
        funnel_stats.append({
            "code": stage.code,
            "name": stage.name,
            "sort_order": stage.sort_order,
            "customer_count": count,
        })
    
    return funnel_stats


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
