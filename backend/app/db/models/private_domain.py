"""Private Domain Models for Phase 5"""
from datetime import datetime
from enum import Enum
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from .base import Base
from app.security.crypto import EncryptedJSON


class ChannelType(str, Enum):
    """Private channel type enum"""
    WECHAT = "wechat"
    WECHAT_WORK = "wechat_work"
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    LINE = "line"
    OTHER = "other"


class ChannelStatus(str, Enum):
    """Channel status enum (covers both business and connection states)"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PAUSED = "paused"
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class PlanStatus(str, Enum):
    """Nurture plan status enum"""
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ContentStatus(str, Enum):
    """Content status enum"""
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    DELETED = "deleted"


class TaskStatus(str, Enum):
    """Follow-up task status enum"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


class SegmentType(str, Enum):
    """Customer segment type enum"""
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    DYNAMIC = "dynamic"


class DealStageStatus(str, Enum):
    """Deal stage status enum"""
    ACTIVE = "active"
    INACTIVE = "inactive"


class DealItemStatus(str, Enum):
    """Deal item status enum"""
    OPEN = "open"
    WON = "won"
    LOST = "lost"
    DRAFT = "draft"


# ========== PrivateChannel ==========

class PrivateChannel(Base):
    """Private channel entity"""
    __tablename__ = "private_channel"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id = Column(PGUUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False)
    platform_id = Column(String(50), nullable=False, index=True)  # 'wechat', 'email', etc.
    channel_type = Column(String(50), nullable=False, default=ChannelType.WECHAT.value)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    contact_info = Column(EncryptedJSON(), nullable=True, default=dict)  # email, phone, etc. (encrypted at rest)
    avatar_url = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default=ChannelStatus.ACTIVE.value)
    connection_status = Column(String(20), nullable=True, default=None)  # online/offline/error
    last_connection = Column(DateTime(timezone=True), nullable=True)
    contact_count = Column(Integer, nullable=False, default=0)
    message_count = Column(Integer, nullable=False, default=0)
    tags = Column(JSON, nullable=True, default=list)
    extra_config = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    nurture_plans = relationship("NurturePlan", back_populates="channel", cascade="all, delete-orphan")
    content_items = relationship("ContentItem", back_populates="channel", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_private_channel_account", "account_id", postgresql_where=is_deleted == False),
        Index("idx_private_channel_type", "channel_type", postgresql_where=is_deleted == False),
        Index("idx_private_channel_status", "status", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<PrivateChannel(id={self.id}, name={self.name}, type={self.channel_type})>"


# ========== NurturePlan ==========

class NurturePlan(Base):
    """Nurture plan entity"""
    __tablename__ = "nurture_plan"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    channel_id = Column(PGUUID(as_uuid=True), ForeignKey("private_channel.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(PGUUID(as_uuid=True), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default=PlanStatus.DRAFT.value)
    schedule_type = Column(String(50), nullable=False, default="fixed")  # fixed, drip, triggered
    schedule_config = Column(JSON, nullable=True, default=dict)  # timing, intervals, etc.
    # LEGACY (ruling t_1814d03d / t_4b55abe8, P1 dual-track unification):
    # ordered steps live in the nurture_plan_item table (single source of truth).
    # This JSON column is retired - new code writes [] / never reads it; column
    # is kept for one release cycle until the ADR-011 revision drops it.
    sequence_steps = Column(JSON, nullable=True, default=list)  # legacy, see above
    target_segment_id = Column(PGUUID(as_uuid=True), ForeignKey("customer_segment.id"), nullable=True)
    trigger_conditions = Column(JSON, nullable=True, default=list)
    performance_metrics = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    channel = relationship("PrivateChannel", back_populates="nurture_plans")
    target_segment = relationship("CustomerSegment")
    plan_items = relationship("NurturePlanItem", back_populates="plan", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_nurture_plan_channel", "channel_id", postgresql_where=is_deleted == False),
        Index("idx_nurture_plan_status", "status", postgresql_where=is_deleted == False),
        Index("idx_nurture_plan_account", "account_id", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<NurturePlan(id={self.id}, name={self.name}, status={self.status})>"


class NurturePlanItem(Base):
    """Individual step in a nurture plan.

    Single source of truth for plan steps: the ordered step definitions live
    in this table, not in the legacy `nurture_plan.sequence_steps` JSON
    column (ADR ruling t_1814d03d / t_4b55abe8).
    """
    __tablename__ = "nurture_plan_item"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_id = Column(PGUUID(as_uuid=True), ForeignKey("nurture_plan.id", ondelete="CASCADE"), nullable=False)
    step_order = Column(Integer, nullable=False, default=0)
    content_id = Column(PGUUID(as_uuid=True), ForeignKey("content_item.id"), nullable=True)
    delay_hours = Column(Integer, nullable=False, default=0)
    trigger_type = Column(String(50), nullable=False, default="time_based")
    config = Column(JSON, nullable=True, default=dict)
    status = Column(String(20), nullable=False, default="active")
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    plan = relationship("NurturePlan", back_populates="plan_items")
    content = relationship("ContentItem", foreign_keys=[content_id])

    __table_args__ = (
        Index("idx_nurture_plan_item_plan", "plan_id"),
        Index("idx_nurture_plan_item_order", "plan_id", "step_order"),
    )

    def __repr__(self):
        return f"<NurturePlanItem(id={self.id}, step={self.step_order})>"


# ========== ContentItem ==========

class ContentItem(Base):
    """Content library item"""
    __tablename__ = "content_item"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id = Column(PGUUID(as_uuid=True), nullable=False)
    channel_id = Column(PGUUID(as_uuid=True), ForeignKey("private_channel.id", ondelete="SET NULL"), nullable=True)
    content_type = Column(String(50), nullable=False)  # text, image, video, pdf, html
    title = Column(String(200), nullable=False)
    summary = Column(Text, nullable=True)
    body = Column(Text, nullable=True)
    media_urls = Column(JSON, nullable=True, default=list)
    tags = Column(JSON, nullable=True, default=list)
    category = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default=ContentStatus.DRAFT.value)
    preview_data = Column(JSON, nullable=True, default=dict)
    version = Column(Integer, nullable=False, default=1)
    usage_count = Column(Integer, nullable=False, default=0)  # Times used
    last_used_at = Column(DateTime(timezone=True), nullable=True)  # Last usage timestamp
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    channel = relationship("PrivateChannel", back_populates="content_items")
    nurture_plan_items = relationship("NurturePlanItem", back_populates="content", foreign_keys=[NurturePlanItem.content_id])

    __table_args__ = (
        Index("idx_content_item_account", "account_id", postgresql_where=is_deleted == False),
        Index("idx_content_item_channel", "channel_id", postgresql_where=is_deleted == False),
        Index("idx_content_item_type", "content_type", postgresql_where=is_deleted == False),
        Index("idx_content_item_status", "status", postgresql_where=is_deleted == False),
        Index("idx_content_item_category", "category", postgresql_where=is_deleted == False),
        Index("idx_content_item_usage", "usage_count", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<ContentItem(id={self.id}, title={self.title}, type={self.content_type})>"


# ========== FollowUpTask ==========

class FollowUpTask(Base):
    """Follow-up task entity"""
    __tablename__ = "follow_up_task"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id = Column(PGUUID(as_uuid=True), nullable=False)
    customer_id = Column(PGUUID(as_uuid=True), ForeignKey("customer.id"), nullable=True)
    lead_id = Column(PGUUID(as_uuid=True), ForeignKey("lead.id"), nullable=True)
    task_type = Column(String(50), nullable=False)  # call, email, wechat, meeting
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default=TaskStatus.PENDING.value)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    priority = Column(Integer, nullable=False, default=0)
    reminder_config = Column(JSON, nullable=True, default=dict)
    result = Column(JSON, nullable=True, default=dict)
    notes = Column(Text, nullable=True)
    created_by = Column(String(100), nullable=True)
    assigned_to = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_follow_up_task_account", "account_id", postgresql_where=is_deleted == False),
        Index("idx_follow_up_task_customer", "customer_id", postgresql_where=is_deleted == False),
        Index("idx_follow_up_task_status", "status", postgresql_where=is_deleted == False),
        Index("idx_follow_up_task_due", "due_date", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<FollowUpTask(id={self.id}, title={self.title}, status={self.status})>"


# ========== CustomerSegment ==========

class CustomerSegment(Base):
    """Customer segment entity"""
    __tablename__ = "customer_segment"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id = Column(PGUUID(as_uuid=True), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    segment_type = Column(String(50), nullable=False, default=SegmentType.MANUAL.value)
    filter_config = Column(JSON, nullable=True, default=dict)
    member_count = Column(Integer, nullable=False, default=0)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    nurture_plans = relationship("NurturePlan", back_populates="target_segment")

    __table_args__ = (
        Index("idx_customer_segment_account", "account_id", postgresql_where=is_deleted == False),
        Index("idx_customer_segment_type", "segment_type", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<CustomerSegment(id={self.id}, name={self.name}, type={self.segment_type})>"


class SegmentMember(Base):
    """Segment membership (manual additions)"""
    __tablename__ = "segment_member"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    segment_id = Column(PGUUID(as_uuid=True), ForeignKey("customer_segment.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(PGUUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False)
    added_by = Column(String(100), nullable=True)
    added_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_segment_member_segment", "segment_id"),
        Index("idx_segment_member_customer", "customer_id"),
        Index("idx_segment_member_unique", "segment_id", "customer_id", unique=True),
    )

    def __repr__(self):
        return f"<SegmentMember(id={self.id}, segment={self.segment_id}, customer={self.customer_id})>"


# ========== DealPipeline ==========

class DealPipeline(Base):
    """Deal pipeline entity"""
    __tablename__ = "deal_pipeline"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id = Column(PGUUID(as_uuid=True), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    pipeline_type = Column(String(50), nullable=False, default="sales")
    stages = Column(JSON, nullable=True, default=list)  # ordered stage definitions
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    deal_items = relationship("DealItem", back_populates="pipeline", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_deal_pipeline_account", "account_id", postgresql_where=is_deleted == False),
        Index("idx_deal_pipeline_default", "is_default", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<DealPipeline(id={self.id}, name={self.name})>"


class DealStage(Base):
    """Deal stage entity (standalone for flexibility)"""
    __tablename__ = "deal_stage"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    pipeline_id = Column(PGUUID(as_uuid=True), ForeignKey("deal_pipeline.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    order = Column(Integer, nullable=False, default=0)
    probability = Column(Integer, nullable=False, default=0)  # win probability %
    config = Column(JSON, nullable=True, default=dict)
    status = Column(String(20), nullable=False, default=DealStageStatus.ACTIVE.value)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    pipeline = relationship("DealPipeline")
    deal_items = relationship("DealItem", back_populates="stage")

    __table_args__ = (
        Index("idx_deal_stage_pipeline", "pipeline_id"),
        Index("idx_deal_stage_order", "pipeline_id", "order"),
    )

    def __repr__(self):
        return f"<DealStage(id={self.id}, name={self.name}, pipeline={self.pipeline_id})>"


class DealItem(Base):
    """Deal item entity"""
    __tablename__ = "deal_item"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    pipeline_id = Column(PGUUID(as_uuid=True), ForeignKey("deal_pipeline.id", ondelete="CASCADE"), nullable=False)
    stage_id = Column(PGUUID(as_uuid=True), ForeignKey("deal_stage.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(PGUUID(as_uuid=True), nullable=False)
    customer_id = Column(PGUUID(as_uuid=True), ForeignKey("customer.id"), nullable=True)
    lead_id = Column(PGUUID(as_uuid=True), ForeignKey("lead.id"), nullable=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    value = Column(Integer, nullable=True)  # estimated value in cents
    currency = Column(String(3), nullable=False, default="CNY")
    expected_close_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, default=DealItemStatus.OPEN.value)
    winner_reason = Column(String(200), nullable=True)
    loser_reason = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    pipeline = relationship("DealPipeline", back_populates="deal_items")
    stage = relationship("DealStage", back_populates="deal_items")

    __table_args__ = (
        Index("idx_deal_item_pipeline", "pipeline_id", postgresql_where=is_deleted == False),
        Index("idx_deal_item_stage", "stage_id", postgresql_where=is_deleted == False),
        Index("idx_deal_item_customer", "customer_id", postgresql_where=is_deleted == False),
        Index("idx_deal_item_status", "status", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<DealItem(id={self.id}, name={self.name}, value={self.value})>"
