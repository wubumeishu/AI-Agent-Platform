"""Tag Model with associations and hierarchy support"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey, Index, Table
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from .base import Base


# 关联表：Tag <-> Customer
tag_customer = Table(
    "tag_customer",
    Base.metadata,
    Column("tag_id", PGUUID(as_uuid=True), ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
    Column("customer_id", PGUUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), primary_key=True),
    Index("idx_tc_customer", "customer_id"),
)


# 关联表：Tag <-> Lead
tag_lead = Table(
    "tag_lead",
    Base.metadata,
    Column("tag_id", PGUUID(as_uuid=True), ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
    Column("lead_id", PGUUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), primary_key=True),
    Index("idx_tl_lead", "lead_id"),
)


class Tag(Base):
    """Tag (标签) 实体 — 支持层级结构与批量关联"""
    __tablename__ = "tag"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(50), nullable=False, index=True)
    color = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)
    parent_id = Column(PGUUID(as_uuid=True), ForeignKey("tag.id", ondelete="SET NULL"), nullable=True)
    usage_count = Column(Integer, nullable=False, default=0)  # 使用次数（统计用）
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # 自引用父子关系
    parent = relationship("Tag", remote_side=[id], backref="children")

    # 多对多关联
    customers = relationship("Customer", secondary=tag_customer, back_populates="tags", lazy="selectin")
    leads = relationship("Lead", secondary=tag_lead, back_populates="tags", lazy="selectin")

    __table_args__ = (
        Index("idx_tag_parent", "parent_id"),
        Index("idx_tag_deleted", "is_deleted"),
    )

    class Config:
        arbitrary_types_allowed = True
