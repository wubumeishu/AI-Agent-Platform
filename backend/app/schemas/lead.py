"""
Lead Schemas: Pydantic models for Lead CRUD and Validation
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


# ==================== Lead Schemas ====================


class LeadCreate(BaseModel):
    """创建 Lead 的请求模型"""
    customer_id: Optional[UUID] = Field(None, description="关联的客户 ID")
    lifecycle_stage_code: str = Field("陌生", description="生命周期阶段编码")
    intent_score: Optional[int] = Field(0, ge=0, le=100, description="意向分数 (0-100)")
    source_type: str = Field(..., description="来源类型: platform/account/agent/campaign/conversation")
    source_id: Optional[str] = Field(None, description="来源 ID")
    status: str = Field("new", description="Lead 状态: new/contacted/qualified/converted")
    notes: Optional[str] = Field(None, description="备注")
    operator: Optional[str] = Field(None, description="操作人")
    tags: Optional[List[UUID]] = Field(None, description="关联的标签 ID 列表")


class LeadUpdate(BaseModel):
    """更新 Lead 的请求模型"""
    lifecycle_stage_code: Optional[str] = Field(None, description="生命周期阶段编码")
    intent_score: Optional[int] = Field(None, ge=0, le=100, description="意向分数 (0-100)")
    status: Optional[str] = Field(None, description="Lead 状态")
    notes: Optional[str] = Field(None, description="备注")
    operator: Optional[str] = Field(None, description="操作人")
    tags: Optional[List[UUID]] = Field(None, description="关联的标签 ID 列表")


class LeadResponse(BaseModel):
    """Lead 响应模型"""
    id: UUID
    customer_id: Optional[UUID]
    lifecycle_stage_code: str
    intent_score: Optional[int]
    source_type: Optional[str]
    source_id: Optional[str]
    status: str
    notes: Optional[str]
    operator: Optional[str]
    tags: List[Dict[str, Any]] = []
    lifecycle_logs: List[Dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadListItem(BaseModel):
    """Lead 列表项（slim）: 列表接口不携带 notes/operator/lifecycle_logs,
    详情字段走 GET /crm/leads/{lead_id}。"""
    id: UUID
    customer_id: Optional[UUID]
    lifecycle_stage_code: Optional[str]
    intent_score: Optional[int]
    source_type: Optional[str]
    source_id: Optional[str]
    status: str
    tags: List[Dict[str, Any]] = []
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class LeadListResponse(BaseModel):
    """Lead 列表响应模型"""
    total: int
    skip: int
    limit: int
    data: List[LeadListItem]


class LeadStatusTransition(BaseModel):
    """Lead 状态流转模型"""
    new_status: str = Field(..., description="新状态: new/contacted/qualified/converted")
    reason: Optional[str] = Field(None, description="流转原因")
    operator: Optional[str] = Field(None, description="操作人")


class IntentScoreConfig(BaseModel):
    """Intent Score 配置模型"""
    threshold_high: int = Field(70, ge=0, le=100, description="高意向阈值")
    threshold_medium: int = Field(60, ge=0, le=100, description="中等意向阈值")
    max_score: int = Field(100, ge=0, le=100, description="最大分数")
    weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "conversation_quality": 0.4,
            "interaction_frequency": 0.3,
            "response_time": 0.2,
            "sentiment": 0.1,
        },
        description="各维度权重"
    )
