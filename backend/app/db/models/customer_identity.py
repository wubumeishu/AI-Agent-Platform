"""CustomerIdentity Model"""
from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey, Index, Float, Table
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from .base import Base
from app.security.crypto import EncryptedString


class CustomerIdentity(Base):
    """Customer Identity (客户跨平台身份) 实体
    
    用于管理同一客户在不同平台的身份信息，支持身份归并。
    """
    __tablename__ = "customer_identity"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    customer_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("customer.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # 平台信息
    platform = Column(String(50), nullable=False, index=True)  # wechat, douyin, bilibili, etc.
    # 身份标识 (restricted identifiers) — encrypted at rest; the unique
    # (platform, platform_account_id) index still enforces uniqueness because
    # AES-SIV is deterministic.
    platform_account_id = Column(EncryptedString(), nullable=False)
    platform_username = Column(String(100), nullable=True)  # 平台用户名/昵称

    # 身份标识 (PII) — encrypted at rest, equality lookups still work.
    phone = Column(EncryptedString(), nullable=True, index=True)  # 手机号
    email = Column(EncryptedString(), nullable=True, index=True)  # 邮箱
    external_id = Column(EncryptedString(), nullable=True)  # 外部系统ID
    
    # 匹配权重
    match_score = Column(Float, nullable=True, default=0.0)  # 身份匹配得分
    confidence = Column(String(20), nullable=True, default="low")  # low/medium/high
    
    # 来源信息
    source = Column(String(50), nullable=True)  # conversation, manual, import
    source_id = Column(String(500), nullable=True)  # 来源记录ID
    
    # 元数据
    extra_data = Column(JSON, nullable=True, default=dict)
    # P6AN-17 P2-3: aware-UTC timestamptz (was naive timestamp + utcnow).
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, nullable=False, default=False)

    # 关联
    customer = relationship("Customer", back_populates="identities")

    __table_args__ = (
        Index("idx_ci_platform_account", "platform", "platform_account_id", unique=True),
        Index("idx_ci_phone", "phone"),
        Index("idx_ci_email", "email"),
        Index("idx_ci_external_id", "external_id"),
    )

    def __repr__(self):
        return f"<CustomerIdentity(id={self.id}, platform={self.platform}, customer={self.customer_id})>"
