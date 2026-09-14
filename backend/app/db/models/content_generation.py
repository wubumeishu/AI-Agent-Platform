"""Content Generation Log model - audit trail for AI-generated nurture content (Phase 5)."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, DateTime,
    ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from uuid import UUID, uuid4

from .base import Base


class ContentGeneration(Base):
    """Content Generation Log (AI 内容生成记录) - reproducibility + history.

    Each row captures one AI content-generation invocation: the personalization
    context that drove it (segment / lifecycle stage / tags / persona), which
    strategy produced the content (llm vs deterministic template), whether a
    fallback fired, the quality score + pass verdict, and the links to the
    persisted ContentItem and the NurturePlan step it was injected into.

    This makes every AI-generated piece of content reproducible and auditable,
    and powers the "generation history" query endpoint.
    """
    __tablename__ = "content_generation"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Ownership
    account_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)

    # What was generated
    source = Column(String(40), nullable=False, default="ai_nurture")  # ai_nurture | ai_content
    content_type = Column(String(50), nullable=False)  # text, image, video, pdf, html
    strategy = Column(String(20), nullable=False, default="template")  # llm | template
    fallback_used = Column(Boolean, nullable=False, default=False)
    fallback_reason = Column(Text, nullable=True)

    # Personalization context that drove generation
    segment_id = Column(
        PGUUID(as_uuid=True), ForeignKey("customer_segment.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    stage_code = Column(String(50), nullable=True, index=True)

    # Links to persisted content + nurture plan step it was injected into
    content_id = Column(
        PGUUID(as_uuid=True), ForeignKey("content_item.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    nurture_plan_id = Column(
        PGUUID(as_uuid=True), ForeignKey("nurture_plan.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    plan_step_id = Column(
        PGUUID(as_uuid=True), ForeignKey("nurture_plan_item.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Quality evaluation (mirrors DecisionLog quality columns)
    quality_score = Column(Float, nullable=True)
    quality_passed = Column(Boolean, nullable=True)

    # Snapshots for reproducibility
    input_snapshot = Column(JSONB, nullable=False, default=dict)
    output_snapshot = Column(JSONB, nullable=False, default=dict)
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

    __table_args__ = (
        Index("idx_content_generation_account", "account_id"),
        Index("idx_content_generation_source", "source"),
        Index("idx_content_generation_strategy", "strategy"),
        Index("idx_content_generation_content", "content_id"),
        Index("idx_content_generation_plan", "nurture_plan_id"),
        Index("idx_content_generation_created", "created_at"),
    )

    def __repr__(self):
        return (
            f"<ContentGeneration(id={self.id}, source={self.source}, "
            f"strategy={self.strategy}, quality={self.quality_score}, "
            f"content_id={self.content_id})>"
        )
