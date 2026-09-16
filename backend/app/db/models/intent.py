"""Intent database models for Phase 2"""
from sqlalchemy import Column, String, Text, Integer, Float, DateTime, Boolean, UUID as SQLAlchemyUUID, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.db.models.base import Base
import uuid
from datetime import datetime, timezone


class Intent(Base):
    """Intent classification record"""
    __tablename__ = "intents"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("conversation.id"), nullable=False, index=True)
    intent_type = Column(String(100), nullable=False, index=True)
    intent_name = Column(String(200), nullable=False)
    confidence = Column(Float, nullable=False)
    raw_input = Column(Text, nullable=False)
    extracted_entities = Column(JSONB, default=dict)
    context = Column(JSONB, default=dict)
    matched_action = Column(String(200), nullable=True)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    conversation = relationship("Conversation", back_populates="intents")
    action_logs = relationship("IntentActionLog", back_populates="intent")


class IntentActionLog(Base):
    """Log of intent-to-action mappings"""
    __tablename__ = "intent_action_logs"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    intent_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("intents.id"), nullable=True)
    action_type = Column(String(100), nullable=False)
    action_target = Column(String(500), nullable=True)
    action_params = Column(JSONB, default=dict)
    executed = Column(Boolean, default=False)
    execution_result = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    intent = relationship("Intent", back_populates="action_logs")
