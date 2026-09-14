"""Decision Log model - audit trail for AI decisions (Phase 2)."""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, DateTime,
    ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class DecisionLog(Base):
    """Decision Log (决策记录) - explainable audit trail for AI decisions.

    Each row captures a decision-engine invocation: which intent drove it,
    which strategy produced the response, how the response was validated,
    and whether a fallback fired. This makes every AI decision reproducible
    and auditable — a core acceptance criterion.
    """
    __tablename__ = "decision_log"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(
        PGUUID(as_uuid=True), ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    customer_id = Column(
        PGUUID(as_uuid=True), ForeignKey("customer.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    persona_id = Column(
        PGUUID(as_uuid=True), ForeignKey("persona.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Intent state that drove the decision
    intent_type = Column(String(100), nullable=False, default="unknown")
    intent_confidence = Column(Float, nullable=True)

    # Strategy + outcome
    strategy = Column(String(20), nullable=False, default="rule_based")  # rule_based | llm | fallback
    action_type = Column(String(100), nullable=False)
    response_text = Column(Text, nullable=False)
    fallback_used = Column(Boolean, nullable=False, default=False)
    fallback_reason = Column(Text, nullable=True)

    # Quality validation
    quality_score = Column(Float, nullable=True)
    quality_passed = Column(Boolean, nullable=True)

    # Explainability (the "decision logic is explainable" criterion)
    explanation = Column(JSONB, nullable=False, default=dict)

    # Raw input snapshot for reproducibility
    input_snapshot = Column(JSONB, nullable=False, default=dict)
    processing_time_ms = Column(Float, nullable=True)

    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), index=True,
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    conversation = relationship("Conversation", back_populates="decision_logs")

    __table_args__ = (
        Index("idx_decision_log_conversation", "conversation_id"),
        Index("idx_decision_log_strategy", "strategy"),
        Index("idx_decision_log_created", "created_at"),
    )

    def __repr__(self):
        return (
            f"<DecisionLog(id={self.id}, intent={self.intent_type}, "
            f"strategy={self.strategy}, quality={self.quality_score})>"
        )
