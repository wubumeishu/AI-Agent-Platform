"""Platform model for Phase 1 Resource Layer"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Boolean, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class Platform(Base):
    """Platform registry entity"""
    __tablename__ = "platform"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    code = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(100), nullable=False)
    capabilities = Column(JSONB, nullable=False, default=[])
    adapter_class = Column(String(200), nullable=True)
    config = Column(JSONB, nullable=False, default={})
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    accounts = relationship("Account", back_populates="platform", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_platform_code", "code", postgresql_where=is_deleted == False),
        Index("idx_platform_status", "status", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<Platform(id={self.id}, code={self.code}, name={self.name}, status={self.status})>"


# Import Account here to create relationship without circular import
from app.db.models.account import Account

# Set up the relationship after both models are defined
Account.platform = relationship("Platform", back_populates="accounts")
