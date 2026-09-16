"""
Lifecycle Stage Schemas: Pydantic models for stage config + funnel pipeline

规则（auto-transition rules）存放于 lifecycle_stage.config JSON 列的
``rules`` 数组中；Pydantic 在此层统一校验，防止脏 JSON 落入数据库。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

# on_trigger 合法取值；引擎侧 (app.crm.services.auto) 保持同一白名单
VALID_TRIGGERS = ("intent_score", "status_change", "conversation_activity")


class LifecycleStageRule(BaseModel):
    """单条自动流转规则。

    on_trigger 语义:
      - intent_score: 当 Lead.intent_score >= min_intent_score 时命中
      - status_change: 当 Lead.status == when_status 时命中
        （when_status 省略时，任意 contacted/qualified/converted 状态即命中）
      - conversation_activity: 当近 7 天对话消息数 >= min_messages 时命中
    """

    on_trigger: str = Field(..., description="触发器类型")
    target_stage_code: str = Field(..., min_length=1, description="命中后流转到的目标阶段 code")
    min_intent_score: Optional[int] = Field(None, ge=0, le=100, description="intent_score 触发：最低意向分")
    when_status: Optional[str] = Field(None, description="status_change 触发：匹配的 Lead 状态")
    min_messages: Optional[int] = Field(None, ge=0, description="conversation_activity 触发：最少消息数")

    @model_validator(mode="after")
    def validate_on_trigger(self) -> "LifecycleStageRule":
        if self.on_trigger not in VALID_TRIGGERS:
            raise ValueError(
                f"on_trigger 必须是以下之一: {', '.join(VALID_TRIGGERS)}（实际: {self.on_trigger!r}）"
            )
        if self.on_trigger == "intent_score" and self.min_intent_score is None:
            raise ValueError("on_trigger=intent_score 必须提供 min_intent_score")
        if self.on_trigger == "conversation_activity" and (
            self.min_messages is None or self.min_messages < 1
        ):
            raise ValueError("on_trigger=conversation_activity 必须提供 min_messages >= 1")
        return self


class LifecycleStageConfig(BaseModel):
    """lifecycle_stage.config 列的结构化视图。"""

    auto_transition_rules: List[LifecycleStageRule] = Field(default_factory=list)

    def to_config_dict(self) -> Dict[str, Any]:
        return {"rules": [r.model_dump() for r in self.auto_transition_rules]}


class LifecycleStageCreate(BaseModel):
    """创建阶段请求。

    code 省略时取 name 作为编码（保持与早期 dict 版 API 的兼容：
    调用方既可以直接 POST 裸 dict 带 config，也可以用本模型）。

    规则二选一（同时提供时 auto_transition_rules 优先）：
      - ``auto_transition_rules``：已校验的 rule 对象列表（推荐）
      - ``config``：自由 dict，``config["rules"]`` 会被校验（旧式用法）
    """

    code: Optional[str] = Field(None, min_length=1, max_length=50, description="阶段编码（唯一）；省略时取 name")
    name: str = Field(..., min_length=1, max_length=100, description="阶段名称")
    description: Optional[str] = Field(None, description="阶段描述")
    sort_order: int = Field(0, description="排序顺序")
    auto_transition_rules: List[LifecycleStageRule] = Field(
        default_factory=list,
        description="自动流转规则列表（写入 config.rules，已校验）",
    )
    config: Optional[Dict[str, Any]] = Field(
        None,
        description="旧式自由 config；其中的 rules 会被校验。auto_transition_rules 优先。",
    )

    @model_validator(mode="after")
    def fill_code_from_name(self) -> "LifecycleStageCreate":
        if not self.code:
            self.code = self.name
        return self

    def to_stage_kwargs(self) -> Dict[str, Any]:
        # rules 优先：用校验过的 auto_transition_rules；否则回退到 config.rules。
        if self.auto_transition_rules:
            config: Dict[str, Any] = {"rules": [r.model_dump() for r in self.auto_transition_rules]}
            if self.config:
                merged = dict(self.config)
                merged["rules"] = config["rules"]
                config = merged
        else:
            config = self.config or {}
        return {
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "sort_order": self.sort_order,
            "config": config,
        }


class LifecycleStageUpdate(BaseModel):
    """更新阶段请求。code 不可改（作为日志与 Lead 的引用键），is_deleted 走 DELETE 端点。"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    sort_order: Optional[int] = None
    config: Optional[Dict[str, Any]] = Field(None, description="直接替换 config（旧式用法）")
    auto_transition_rules: Optional[List[LifecycleStageRule]] = Field(
        None,
        description="替换 config.rules（与 config 同时提供时，rules 优先）",
    )


class LifecycleTransitionRequest(BaseModel):
    """POST /stages/transition 请求体。"""

    lead_id: UUID = Field(..., description="目标 Lead ID")
    new_stage_code: str = Field(..., min_length=1, description="目标阶段 code")
    reason: str = Field("manual", description="流转原因")
    operator: Optional[str] = Field(None, description="操作人")
    metadata: Optional[Dict[str, Any]] = Field(None, description="扩展元数据")


class LifecycleTransitionResponse(BaseModel):
    """阶段流转结果。"""

    id: UUID
    lead_id: UUID
    old_stage_code: Optional[str]
    new_stage_code: str
    transition_reason: str
    operator: Optional[str]
    metadata: Dict[str, Any]
    created_at: Optional[datetime]


class FunnelStageStat(BaseModel):
    """单个漏斗阶段统计。"""

    code: str
    name: str
    sort_order: int
    customer_count: int
    conversion_rate: float = 0.0  # 相对漏斗顶部阶段的累计通过率（0.0-1.0）


class FunnelResponse(BaseModel):
    """漏斗统计响应。data 为按 sort_order 升序的阶段统计列表。"""

    code: int = 0
    message: str = "success"
    data: List[FunnelStageStat] = []
