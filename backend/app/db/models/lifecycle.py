"""Lifecycle Stage and Log Models"""
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from .base import Base


class LifecycleStage(Base):
    """生命周期阶段"""
    __tablename__ = "lifecycle_stage"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)
    
    # 关系将在 db/models/__init__.py 中延迟导入
    logs = None
    
    class Config:
        arbitrary_types_allowed = True


class LifecycleStageLog(Base):
    """生命周期阶段变更日志"""
    __tablename__ = "lifecycle_stage_log"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    lead_id = Column(PGUUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False)
    old_stage_code = Column(String(50), nullable=True)
    new_stage_code = Column(String(50), nullable=False, index=True)
    transition_reason = Column(String(200), nullable=False, default="manual")
    operator = Column(String(100), nullable=True)
    extra_data = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    lead = relationship("Lead", back_populates="lifecycle_logs")

    __table_args__ = (
        Index('idx_lifecycle_stage_log_lead', 'lead_id'),
        Index('idx_lifecycle_stage_log_time', 'created_at', postgresql_using='btree', postgresql_ops={'created_at': 'DESC'}),
    )

    class Config:
        arbitrary_types_allowed = True
