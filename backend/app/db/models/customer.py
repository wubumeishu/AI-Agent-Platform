"""Customer Model"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Boolean, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from .base import Base
from app.security.crypto import EncryptedString


class Customer(Base):
    """Customer (客户) 实体"""
    __tablename__ = "customer"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(100), nullable=False)
    # PII at rest: encrypted (deterministic AES-SIV) so a DB dump does not
    # expose plaintext phone/email; equality lookups still work.
    email = Column(EncryptedString(), nullable=True)
    phone = Column(EncryptedString(), nullable=True)
    company = Column(String(200), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    extra_info = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # 多对多关联到标签
    tags = relationship("Tag", secondary="tag_customer", back_populates="customers", lazy="selectin")
    
    # 一对多关联到身份
    identities = relationship("CustomerIdentity", back_populates="customer", cascade="all, delete-orphan", lazy="selectin")

    class Config:
        arbitrary_types_allowed = True
