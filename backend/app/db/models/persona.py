"""Persona model for Phase 1"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class Persona(Base):
    """Persona entity with version management"""
    __tablename__ = "persona"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    personality = Column(JSONB, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    parent_id = Column(PGUUID(as_uuid=True), ForeignKey("persona.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    parent = relationship("Persona", remote_side=[id], backref="versions")
    agent_bindings = relationship("AgentPersonaBinding", back_populates="persona", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_persona_parent_version", "parent_id", "version", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<Persona(id={self.id}, name={self.name}, version={self.version})>"
