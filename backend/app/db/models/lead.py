"""Lead Model"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from .base import Base


class Lead(Base):
    """Lead (线索) 实体"""
    __tablename__ = "lead"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    customer_id = Column(PGUUID(as_uuid=True), ForeignKey("customer.id"), nullable=True)
    lifecycle_stage_code = Column(String(50), nullable=True, default="陌生")
    intent_score = Column(Integer, nullable=True, default=0)
    source_type = Column(String(50), nullable=True)
    source_id = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="new")
    notes = Column(Text, nullable=True)
    operator = Column(String(100), nullable=True)
    # P6AN-17 P2-3: aware-UTC timestamptz (was naive timestamp + utcnow).
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, nullable=False, default=False)

    # 关系
    lifecycle_logs = relationship("LifecycleStageLog", back_populates="lead", cascade="all, delete-orphan")
    tags = relationship("Tag", secondary="tag_lead", back_populates="leads", lazy="selectin")

    __table_args__ = (
        Index('idx_lead_customer', 'customer_id'),
        Index('idx_lead_stage', 'lifecycle_stage_code'),
        Index('idx_lead_status', 'status'),
        Index('idx_lead_created', 'created_at'),
    )

    class Config:
        arbitrary_types_allowed = True
