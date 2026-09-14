"""Prompt template model for Phase 2"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class PromptTemplate(Base):
    """Prompt template entity with version management"""
    __tablename__ = "prompt_template"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    template_type = Column(String(50), nullable=False, default="custom")  # system, conversation, greeting
    category = Column(String(100), nullable=True)
    variables = Column(JSONB, nullable=False, default=list)  # List of variable names
    version = Column(Integer, nullable=False, default=1)
    parent_id = Column(PGUUID(as_uuid=True), ForeignKey("prompt_template.id", ondelete="SET NULL"), nullable=True)
    is_baseline = Column(Boolean, nullable=False, default=False)  # Whether this is the baseline version
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    parent = relationship("PromptTemplate", remote_side=[id], backref="versions")
    usages = relationship("PromptTemplateUsage", back_populates="template", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_template_parent_version", "parent_id", "version", postgresql_where=is_deleted == False),
        Index("idx_template_type_category", "template_type", "category", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<PromptTemplate(id={self.id}, name={self.name}, version={self.version})>"


class PromptTemplateUsage(Base):
    """Track prompt template usage for analytics"""
    __tablename__ = "prompt_template_usage"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    template_id = Column(PGUUID(as_uuid=True), ForeignKey("prompt_template.id", ondelete="CASCADE"), nullable=False)
    rendered_content = Column(Text, nullable=False)
    variables_used = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    template = relationship("PromptTemplate", back_populates="usages")

    __table_args__ = (
        Index("idx_usage_template_created", "template_id", "created_at"),
    )

    def __repr__(self):
        return f"<PromptTemplateUsage(template_id={self.template_id}, created_at={self.created_at})>"
