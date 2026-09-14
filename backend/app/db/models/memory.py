"""Memory Model - Short-term and Long-term Memory System"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey, Index, Float, JSON
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class Memory(Base):
    """Memory (记忆) 实体 - 长期记忆存储"""
    __tablename__ = "memory"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    customer_id = Column(PGUUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_type = Column(String(50), nullable=False, default="preference")  # preference, fact, history, insight
    category = Column(String(50), nullable=False, default="general")  # general, product, service, personal
    content = Column(Text, nullable=False)
    source = Column(String(50), nullable=False, default="conversation")  # conversation, manual, ai_generated
    importance = Column(Integer, nullable=False, default=5)  # 1-10
    confidence = Column(Float, nullable=False, default=1.0)  # 0-1, AI生成记忆的可信度
    tags = Column(JSONB, nullable=False, default=list)
    metadata_ = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)
    
    # 关系
    memories = relationship("MemoryFragment", back_populates="memory", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_memory_customer', 'customer_id'),
        Index('idx_memory_type', 'memory_type'),
        Index('idx_memory_category', 'category'),
        Index('idx_memory_created', 'created_at'),
        Index('idx_memory_tags', 'tags', postgresql_using='gin'),
    )
    
    def __repr__(self):
        return f"<Memory(id={self.id}, type={self.memory_type}, importance={self.importance})>"


class ActivityLog(Base):
    """Activity Log (活动记录) 实体"""
    __tablename__ = "activity_log"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    customer_id = Column(PGUUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False, index=True)
    activity_type = Column(String(50), nullable=False)  # call, email, meeting, note, tag_change, stage_change, etc.
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    related_lead_id = Column(PGUUID(as_uuid=True), ForeignKey("lead.id", ondelete="SET NULL"), nullable=True)
    metadata_ = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_activity_customer', 'customer_id'),
        Index('idx_activity_type', 'activity_type'),
        Index('idx_activity_created', 'created_at'),
    )
    
    def __repr__(self):
        return f"<ActivityLog(id={self.id}, type={self.activity_type})>"


class MemoryFragment(Base):
    """Memory Fragment (记忆片段) 实体 - 记忆的细分片段"""
    __tablename__ = "memory_fragment"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    memory_id = Column(PGUUID(as_uuid=True), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False, index=True)
    fragment_order = Column(Integer, nullable=False, default=0)  # 片段顺序
    content = Column(Text, nullable=False)
    embedding = Column(JSONB, nullable=True)  # 向量嵌入（用于语义搜索）
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    
    # 关系
    memory = relationship("Memory", back_populates="memories")
    
    __table_args__ = (
        Index('idx_fragment_memory', 'memory_id'),
    )
    
    def __repr__(self):
        return f"<MemoryFragment(id={self.id}, order={self.fragment_order})>"


class ConversationSummary(Base):
    """Conversation Summary (对话摘要) 实体 - 短期记忆摘要"""
    __tablename__ = "conversation_summary"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(PGUUID(as_uuid=True), ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True)
    summary_type = Column(String(50), nullable=False, default="brief")  # brief, detailed, executive
    content = Column(Text, nullable=False)
    key_points = Column(JSONB, nullable=False, default=list)  # 关键点列表
    sentiment = Column(String(20), nullable=True)  # positive, neutral, negative
    action_items = Column(JSONB, nullable=False, default=list)  # 待办事项
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    
    __table_args__ = (
        Index('idx_summary_conversation', 'conversation_id'),
        Index('idx_summary_created', 'created_at'),
    )
    
    def __repr__(self):
        return f"<ConversationSummary(id={self.id}, type={self.summary_type})>"


class ContextWindow(Base):
    """Context Window (上下文窗口) 实体 - 管理对话上下文状态"""
    __tablename__ = "context_window"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(PGUUID(as_uuid=True), ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, unique=True)
    current_tokens = Column(Integer, nullable=False, default=0)
    max_tokens = Column(Integer, nullable=False, default=4000)
    compressed_count = Column(Integer, nullable=False, default=0)
    last_compressed_at = Column(DateTime(timezone=True), nullable=True)
    summary_id = Column(PGUUID(as_uuid=True), ForeignKey("conversation_summary.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_context_window_conversation', 'conversation_id'),
    )
    
    def __repr__(self):
        return f"<ContextWindow(id={self.id}, tokens={self.current_tokens})>"
