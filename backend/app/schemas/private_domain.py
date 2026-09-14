"""Pydantic schemas for Private Domain module"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field


# ========== PrivateChannel Schemas ==========

class PrivateChannelBase(BaseModel):
    """Base schema for private channel"""
    platform_id: str = Field(..., min_length=1, max_length=50)
    channel_type: str = Field(..., pattern="^(wechat|wechat_work|email|sms|whatsapp|line|other)$")
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    contact_info: Optional[dict] = None
    avatar_url: Optional[str] = None
    tags: Optional[List[str]] = None
    extra_config: Optional[dict] = None


class PrivateChannelCreate(PrivateChannelBase):
    """Schema for creating a private channel"""
    account_id: UUID
    pass


class PrivateChannelUpdate(BaseModel):
    """Schema for updating a private channel"""
    platform_id: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    contact_info: Optional[dict] = None
    avatar_url: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|inactive|paused|online|offline|error)$")
    connection_status: Optional[str] = Field(None, pattern="^(online|offline|error)$")
    tags: Optional[List[str]] = None
    extra_config: Optional[dict] = None


class PrivateChannelResponse(PrivateChannelBase):
    """Schema for private channel response"""
    id: UUID
    account_id: UUID
    status: str
    connection_status: Optional[str] = None
    last_connection: Optional[datetime] = None
    contact_count: int
    message_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PrivateChannelListResponse(BaseModel):
    """Paginated private channel list response"""
    items: List[PrivateChannelResponse]
    total: int
    page: int
    page_size: int


# ========== NurturePlan Schemas ==========

class NurturePlanBase(BaseModel):
    """Base schema for nurture plan"""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    schedule_type: str = Field(default="fixed", pattern="^(fixed|drip|triggered)$")
    schedule_config: Optional[dict] = None
    # LEGACY input (ruling t_1814d03d / t_4b55abe8, Contract B): reconciled
    # into the nurture_plan_item table (single source of truth); the legacy
    # JSON column is retired ([]). Accepted for backward compatibility only.
    sequence_steps: Optional[List[dict]] = None
    trigger_conditions: Optional[List[dict]] = None
    target_segment_id: Optional[UUID] = None


class NurturePlanCreate(NurturePlanBase):
    """Schema for creating a nurture plan"""
    channel_id: UUID
    account_id: UUID


class NurturePlanUpdate(BaseModel):
    """Schema for updating a nurture plan"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(draft|active|paused|completed|archived)$")
    schedule_type: Optional[str] = Field(None, pattern="^(fixed|drip|triggered)$")
    schedule_config: Optional[dict] = None
    # LEGACY input (ruling t_1814d03d / t_4b55abe8, Contract B): if provided,
    # reconciled into the nurture_plan_item table; the legacy JSON column is
    # never written.
    sequence_steps: Optional[List[dict]] = None
    trigger_conditions: Optional[List[dict]] = None
    target_segment_id: Optional[UUID] = None


class NurturePlanResponse(NurturePlanBase):
    """Schema for nurture plan response"""
    id: UUID
    channel_id: UUID
    account_id: UUID
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NurturePlanListResponse(BaseModel):
    """Paginated nurture plan list response"""
    items: List[NurturePlanResponse]
    total: int
    page: int
    page_size: int


# ========== ContentItem Schemas ==========

class ContentItemBase(BaseModel):
    """Base schema for content item"""
    content_type: str = Field(..., pattern="^(text|image|video|pdf|html)$")
    title: str = Field(..., min_length=1, max_length=200)
    summary: Optional[str] = None
    body: Optional[str] = None
    media_urls: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None


class ContentItemCreate(ContentItemBase):
    """Schema for creating a content item"""
    account_id: UUID
    channel_id: Optional[UUID] = None
    pass


class ContentItemUpdate(BaseModel):
    """Schema for updating a content item"""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    summary: Optional[str] = None
    body: Optional[str] = None
    media_urls: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(draft|published|archived|deleted)$")


class ContentItemResponse(ContentItemBase):
    """Schema for content item response"""
    id: UUID
    account_id: UUID
    channel_id: Optional[UUID]
    status: str
    version: int
    usage_count: int = Field(default=0)
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ContentItemListResponse(BaseModel):
    """Paginated content item list response"""
    items: List[ContentItemResponse]
    total: int
    page: int
    page_size: int


class ContentSearchFilter(BaseModel):
    """Search filter parameters for content items"""
    keyword: Optional[str] = None  # Search in title, summary, body
    content_type: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    tag: Optional[str] = None  # Filter by tag (exact match)
    min_usage_count: Optional[int] = Field(default=None, ge=0)
    max_usage_count: Optional[int] = Field(default=None, ge=0)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    sort_by: str = Field(default="created_at", pattern="^(created_at|updated_at|usage_count|title)$")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ContentSearchResponse(BaseModel):
    """Search results response"""
    items: List[ContentItemResponse]
    total: int
    page: int
    page_size: int
    keywords: Optional[str] = None


class ContentUsageStats(BaseModel):
    """Content usage statistics"""
    content_id: UUID
    title: str
    content_type: str
    category: Optional[str]
    usage_count: int
    last_used_at: Optional[datetime]
    used_in_plans: int  # Number of nurture plans using this content
    used_in_tasks: int  # Number of follow-up tasks referencing this content


class ContentTypeStats(BaseModel):
    """Content type distribution statistics"""
    content_type: str
    count: int
    total_usage: int


class ContentCategoryStats(BaseModel):
    """Content category distribution statistics"""
    category: Optional[str]
    count: int
    total_usage: int


# ========== FollowUpTask Schemas ==========

class FollowUpTaskBase(BaseModel):
    """Base schema for follow-up task"""
    task_type: str = Field(..., pattern="^(call|email|wechat|meeting|sms|other)$")
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    priority: int = Field(default=0, ge=0, le=100)
    scheduled_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
    reminder_config: Optional[dict] = None


class FollowUpTaskCreate(FollowUpTaskBase):
    """Schema for creating a follow-up task"""
    account_id: UUID
    customer_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    assigned_to: Optional[str] = None
    status: str = Field(default="pending", pattern="^(pending|in_progress|completed|cancelled|overdue)$")
    pass


class FollowUpTaskUpdate(BaseModel):
    """Schema for updating a follow-up task"""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(pending|in_progress|completed|cancelled|overdue)$")
    priority: Optional[int] = Field(None, ge=0, le=100)
    scheduled_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
    result: Optional[dict] = None
    notes: Optional[str] = None
    assigned_to: Optional[str] = None


class FollowUpTaskResponse(FollowUpTaskBase):
    """Schema for follow-up task response"""
    id: UUID
    account_id: UUID
    customer_id: Optional[UUID]
    lead_id: Optional[UUID]
    status: str
    created_by: Optional[str] = None
    assigned_to: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FollowUpTaskListResponse(BaseModel):
    """Paginated follow-up task list response"""
    items: List[FollowUpTaskResponse]
    total: int
    page: int
    page_size: int


# ========== CustomerSegment Schemas ==========

class CustomerSegmentBase(BaseModel):
    """Base schema for customer segment"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    segment_type: str = Field(default="manual", pattern="^(manual|automatic|dynamic)$")
    filter_config: Optional[dict] = None


class CustomerSegmentCreate(CustomerSegmentBase):
    """Schema for creating a customer segment"""
    account_id: UUID
    pass


class CustomerSegmentUpdate(BaseModel):
    """Schema for updating a customer segment"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    filter_config: Optional[dict] = None


class CustomerSegmentResponse(CustomerSegmentBase):
    """Schema for customer segment response"""
    id: UUID
    account_id: UUID
    member_count: int
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CustomerSegmentListResponse(BaseModel):
    """Paginated customer segment list response"""
    items: List[CustomerSegmentResponse]
    total: int
    page: int
    page_size: int


# ========== DealPipeline Schemas ==========

class DealPipelineBase(BaseModel):
    """Base schema for deal pipeline"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    pipeline_type: str = Field(default="sales", pattern="^(sales|marketing|support)$")
    is_default: bool = False


class DealPipelineCreate(DealPipelineBase):
    """Schema for creating a deal pipeline"""
    account_id: UUID
    stages: Optional[List[dict]] = None
    pass


class DealPipelineUpdate(BaseModel):
    """Schema for updating a deal pipeline"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    stages: Optional[List[dict]] = None


class DealPipelineResponse(DealPipelineBase):
    """Schema for deal pipeline response"""
    id: UUID
    account_id: UUID
    stages: Optional[List[dict]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DealPipelineListResponse(BaseModel):
    """Paginated deal pipeline list response"""
    items: List[DealPipelineResponse]
    total: int
    page: int
    page_size: int


# ========== DealStage Schemas ==========

class DealStageBase(BaseModel):
    """Base schema for deal stage"""
    name: str = Field(..., min_length=1, max_length=100)
    order: int = Field(default=0, ge=0)
    probability: int = Field(default=0, ge=0, le=100)
    config: Optional[dict] = None


class DealStageCreate(DealStageBase):
    """Schema for creating a deal stage"""
    pipeline_id: UUID
    pass


class DealStageUpdate(BaseModel):
    """Schema for updating a deal stage"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    order: Optional[int] = Field(None, ge=0)
    probability: Optional[int] = Field(None, ge=0, le=100)
    status: Optional[str] = Field(None, pattern="^(active|inactive)$")
    config: Optional[dict] = None


class DealStageResponse(DealStageBase):
    """Schema for deal stage response"""
    id: UUID
    pipeline_id: UUID
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DealStageListResponse(BaseModel):
    """Paginated deal stage list response"""
    items: List[DealStageResponse]
    total: int
    page: int
    page_size: int


# ========== DealItem Schemas ==========

class DealItemBase(BaseModel):
    """Base schema for deal item"""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    value: Optional[int] = None
    currency: str = Field(default="CNY", max_length=3)
    expected_close_date: Optional[datetime] = None


class DealItemCreate(DealItemBase):
    """Schema for creating a deal item"""
    pipeline_id: UUID
    account_id: UUID
    stage_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    pass


class DealItemUpdate(BaseModel):
    """Schema for updating a deal item"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    value: Optional[int] = None
    expected_close_date: Optional[datetime] = None
    stage_id: Optional[UUID] = None
    status: Optional[str] = Field(None, pattern="^(open|won|lost|draft)$")
    winner_reason: Optional[str] = Field(None, max_length=200)
    loser_reason: Optional[str] = Field(None, max_length=200)


class DealItemResponse(DealItemBase):
    """Schema for deal item response"""
    id: UUID
    pipeline_id: UUID
    stage_id: Optional[UUID]
    account_id: UUID
    customer_id: Optional[UUID]
    lead_id: Optional[UUID]
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DealItemListResponse(BaseModel):
    """Paginated deal item list response"""
    items: List[DealItemResponse]
    total: int
    page: int
    page_size: int


# ========== Common Pagination Schemas ==========

class PaginationParams(BaseModel):
    """Common pagination parameters"""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    sort_by: Optional[str] = None
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")
    filter: Optional[dict] = None


# ========== Deal Stage Transition Schema ==========

class DealItemTransition(BaseModel):
    """Schema for transitioning a deal item to a new stage"""
    stage_id: UUID
    status: Optional[str] = Field(None, pattern="^(open|won|lost|draft)$")
    winner_reason: Optional[str] = Field(None, max_length=200)
    loser_reason: Optional[str] = Field(None, max_length=200)


# ========== Deal Pipeline Statistics Schema ==========

class DealPipelineStats(BaseModel):
    """Schema for deal pipeline statistics"""
    pipeline_id: UUID
    pipeline_name: str
    pipeline_type: str
    total_deals: int
    open_deals: int
    won_deals: int
    lost_deals: int
    total_value: int
    won_value: int
    open_value: int
    conversion_rate: float
    stages: List[Dict[str, Any]]


class DealPipelineStatsDetail(BaseModel):
    """Schema for a single pipeline's statistics detail"""
    pipeline_id: UUID
    total_deals: int
    open_deals: int
    won_deals: int
    lost_deals: int
    total_value: int
    won_value: int
    open_value: int
    conversion_rate: float
    stages: List[Dict[str, Any]]


# ========== Integration Schemas ==========\

class LeadConversionRequest(BaseModel):
    """Request schema for converting a lead to customer"""
    channel_id: Optional[UUID] = Field(None, description="Private channel to associate with")
    name: Optional[str] = Field(None, description="Customer name")
    email: Optional[str] = Field(None, description="Customer email")
    phone: Optional[str] = Field(None, description="Customer phone")
    company: Optional[str] = Field(None, description="Company name")


class LeadConversionResponse(BaseModel):
    """Response schema for lead conversion"""
    customer: Dict[str, Any]
    lead: Optional[Dict[str, Any]]
    private_channel: Optional[Dict[str, Any]]
    converted_at: str


class CustomerChannelAssociation(BaseModel):
    """Response for customer-channel association"""
    customer_id: str
    channel_id: str
    channel_name: str
    channel_type: str
    updated_at: str


class NurturePlanApplication(BaseModel):
    """Response for nurture plan application"""
    success: bool
    plan: Dict[str, Any]
    customer: Dict[str, Any]
    applied_at: str
    added_to_segment: bool


class DealCreationWithCustomer(BaseModel):
    """Response for deal creation with customer linkage"""
    id: str
    pipeline_id: str
    account_id: str
    customer_id: Optional[str]
    lead_id: Optional[str]
    name: str
    value: Optional[int]
    currency: str
    status: str
    created_at: str


class DataConsistencyResult(BaseModel):
    """Result of data consistency validation"""
    account_id: str
    validated_at: str
    issues_count: int
    is_consistent: bool
    issues: List[Dict[str, Any]]


class OrphanedReferenceFix(BaseModel):
    """Result of fixing orphaned references"""
    account_id: str
    fixes_applied: int
    fixed_at: str


class IntegrationStats(BaseModel):
    """Cross-module integration statistics"""
    account_id: str
    statistics: Dict[str, Any]
    calculated_at: str
