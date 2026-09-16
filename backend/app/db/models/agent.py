"""Agent model for CRM integration"""
from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Boolean, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class Agent(Base):
    """Agent entity - AI agent that manages customers"""
    __tablename__ = "agent"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="active")  # active, inactive, paused
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    customer_bindings = relationship(
        "AgentCustomerBinding",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    __table_args__ = (
        Index("idx_agent_status", "status", postgresql_where=is_deleted == False),
        Index("idx_agent_name", "name", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<Agent(id={self.id}, name={self.name}, status={self.status})>"


class AgentCustomerBinding(Base):
    """Binding between Agent and Customer - represents responsibility relationship"""
    __tablename__ = "agent_customer_binding"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id = Column(PGUUID(as_uuid=True), ForeignKey("agent.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(PGUUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    assigned_by = Column(PGUUID(as_uuid=True), nullable=True)  # User who assigned
    notes = Column(Text, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    agent = relationship("Agent", back_populates="customer_bindings")
    customer = relationship("Customer", back_populates="agent_bindings")

    __table_args__ = (
        Index("idx_agent_customer_agent", "agent_id", postgresql_where=is_deleted == False),
        Index("idx_agent_customer_customer", "customer_id", postgresql_where=is_deleted == False),
        Index("idx_agent_customer_unique", "agent_id", "customer_id", unique=True, postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<AgentCustomerBinding(agent={self.agent_id}, customer={self.customer_id})>"


# Add back-reference to Customer model
from app.db.models.customer import Customer
Customer.agent_bindings = relationship(
    "AgentCustomerBinding",
    back_populates="customer",
    cascade="all, delete-orphan",
    lazy="selectin"
)
