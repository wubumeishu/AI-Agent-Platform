"""Analytics API request / response schemas (Phase 6 / P6AN-01).

Covers the CRUD surface for the five analytics entities
(``dashboard_widget`` / ``funnel_step`` / ``metric_definition`` /
``experiment`` / ``experiment_result``).

Validation mirrors the model-layer value domains (``WIDGET_TYPES``,
``METRIC_CATEGORIES``, ...); the one state-machine rule (experiment
status transitions) is enforced in the service layer, not here — the
schemas only constrain each field to the legal set.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models.analytics import (
    EXPERIMENT_STATUSES,
    METRIC_AGGREGATIONS,
    METRIC_CATEGORIES,
    METRIC_VALUE_TYPES,
    WIDGET_TYPES,
)

_EXP_STATUS_PATTERN = "^(" + "|".join(EXPERIMENT_STATUSES) + ")$"
_WIDGET_TYPE_PATTERN = "^(" + "|".join(WIDGET_TYPES) + ")$"
_METRIC_CATEGORY_PATTERN = "^(" + "|".join(METRIC_CATEGORIES) + ")$"
_METRIC_VALUE_TYPE_PATTERN = "^(" + "|".join(METRIC_VALUE_TYPES) + ")$"
_METRIC_AGG_PATTERN = "^(" + "|".join(METRIC_AGGREGATIONS) + ")$"


# ========== DashboardWidget ==========

class DashboardWidgetCreate(BaseModel):
    """Create a dashboard widget definition."""

    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    widget_type: str = Field("kpi", pattern=_WIDGET_TYPE_PATTERN)
    config: Dict[str, Any] = Field(default_factory=dict)
    metric_code: Optional[str] = Field(None, max_length=100)
    funnel_code: Optional[str] = Field(None, max_length=100)
    refresh_interval_seconds: int = Field(300, ge=1, le=86_400 * 30)
    position: int = Field(0, ge=0)
    enabled: bool = True
    account_id: Optional[UUID] = None


class DashboardWidgetUpdate(BaseModel):
    """Mutable fields of a dashboard widget (all optional)."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    widget_type: Optional[str] = Field(None, pattern=_WIDGET_TYPE_PATTERN)
    config: Optional[Dict[str, Any]] = None
    metric_code: Optional[str] = Field(None, max_length=100)
    funnel_code: Optional[str] = Field(None, max_length=100)
    refresh_interval_seconds: Optional[int] = Field(None, ge=1, le=86_400 * 30)
    position: Optional[int] = Field(None, ge=0)
    enabled: Optional[bool] = None


class DashboardWidgetResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    widget_type: str
    config: Dict[str, Any] = Field(default_factory=dict)
    metric_code: Optional[str] = None
    funnel_code: Optional[str] = None
    refresh_interval_seconds: int
    position: int
    enabled: bool
    account_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, w: Any) -> "DashboardWidgetResponse":
        return cls(
            id=w.id,
            name=w.name,
            description=w.description,
            widget_type=w.widget_type,
            config=w.config or {},
            metric_code=w.metric_code,
            funnel_code=w.funnel_code,
            refresh_interval_seconds=w.refresh_interval_seconds,
            position=w.position,
            enabled=w.enabled,
            account_id=w.account_id,
            created_at=w.created_at,
            updated_at=w.updated_at,
        )


class DashboardWidgetListResponse(BaseModel):
    items: List[DashboardWidgetResponse]
    total: int
    page: int
    page_size: int


# ========== FunnelStep ==========

class FunnelStepCreate(BaseModel):
    """Register one step of a named funnel. ``seq`` is 1-based and unique
    per (funnel_code, account scope) among live rows."""

    funnel_code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    seq: int = Field(..., ge=1, le=1000)
    entry_criteria: Dict[str, Any] = Field(default_factory=dict)
    conversion_criteria: Optional[Dict[str, Any]] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    account_id: Optional[UUID] = None


class FunnelStepUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    seq: Optional[int] = Field(None, ge=1, le=1000)
    entry_criteria: Optional[Dict[str, Any]] = None
    conversion_criteria: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None


class FunnelStepResponse(BaseModel):
    id: UUID
    funnel_code: str
    name: str
    description: Optional[str] = None
    seq: int
    entry_criteria: Dict[str, Any] = Field(default_factory=dict)
    conversion_criteria: Optional[Dict[str, Any]] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    account_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, s: Any) -> "FunnelStepResponse":
        return cls(
            id=s.id,
            funnel_code=s.funnel_code,
            name=s.name,
            description=s.description,
            seq=s.seq,
            entry_criteria=s.entry_criteria or {},
            conversion_criteria=s.conversion_criteria,
            config=s.config or {},
            account_id=s.account_id,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )


class FunnelStepListResponse(BaseModel):
    items: List[FunnelStepResponse]
    total: int
    page: int
    page_size: int


# ========== MetricDefinition ==========

class MetricDefinitionCreate(BaseModel):
    """Register a metric definition (stable ``code`` other objects reference)."""

    code: str = Field(..., min_length=1, max_length=100,
                      pattern="^[a-z0-9_:.]+$",
                      description="Lower-case dotted code, e.g. 'conversation.sent_count'.")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    category: str = Field("custom", pattern=_METRIC_CATEGORY_PATTERN)
    value_type: str = Field("numeric", pattern=_METRIC_VALUE_TYPE_PATTERN)
    unit: Optional[str] = Field(None, max_length=50)
    aggregation: Optional[str] = Field(None, pattern=_METRIC_AGG_PATTERN)
    formula: Dict[str, Any] = Field(default_factory=dict,
                                    description="JSONB metric spec (source + agg + filters); no raw SQL.")
    source: Optional[str] = Field(None, max_length=100)
    window_days: int = Field(30, ge=1, le=3650)
    enabled: bool = True
    account_id: Optional[UUID] = None


class MetricDefinitionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = Field(None, pattern=_METRIC_CATEGORY_PATTERN)
    value_type: Optional[str] = Field(None, pattern=_METRIC_VALUE_TYPE_PATTERN)
    unit: Optional[str] = Field(None, max_length=50)
    aggregation: Optional[str] = Field(None, pattern=_METRIC_AGG_PATTERN)
    formula: Optional[Dict[str, Any]] = None
    source: Optional[str] = Field(None, max_length=100)
    window_days: Optional[int] = Field(None, ge=1, le=3650)
    enabled: Optional[bool] = None


class MetricDefinitionResponse(BaseModel):
    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    category: str
    value_type: str
    unit: Optional[str] = None
    aggregation: Optional[str] = None
    formula: Dict[str, Any] = Field(default_factory=dict)
    source: Optional[str] = None
    window_days: int
    enabled: bool
    account_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, m: Any) -> "MetricDefinitionResponse":
        return cls(
            id=m.id,
            code=m.code,
            name=m.name,
            description=m.description,
            category=m.category,
            value_type=m.value_type,
            unit=m.unit,
            aggregation=m.aggregation,
            formula=m.formula or {},
            source=m.source,
            window_days=m.window_days,
            enabled=m.enabled,
            account_id=m.account_id,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )


class MetricDefinitionListResponse(BaseModel):
    items: List[MetricDefinitionResponse]
    total: int
    page: int
    page_size: int


# ========== Experiment ==========

class ExperimentCreate(BaseModel):
    """Create an experiment in ``draft`` status."""

    code: str = Field(..., min_length=1, max_length=100, pattern="^[a-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    hypothesis: Optional[str] = Field(None, max_length=4000)
    primary_metric_code: Optional[str] = Field(None, max_length=100)
    secondary_metric_codes: List[str] = Field(default_factory=list,
                                               description="List of registered metric codes.")
    variants: List[Dict[str, Any]] = Field(default_factory=list,
                                           description='Variant configs, e.g. [{"label":"control","share":0.5,"config":{}}].')
    owner: Optional[str] = Field(None, max_length=100)
    account_id: Optional[UUID] = None


class ExperimentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    hypothesis: Optional[str] = Field(None, max_length=4000)
    primary_metric_code: Optional[str] = Field(None, max_length=100)
    secondary_metric_codes: Optional[List[str]] = None
    variants: Optional[List[Dict[str, Any]]] = None
    owner: Optional[str] = Field(None, max_length=100)


class ExperimentStatusUpdate(BaseModel):
    """Drive the experiment through its state machine."""

    status: str = Field(..., pattern=_EXP_STATUS_PATTERN,
                        description="Target status; must be a legal transition from the current status.")
    reason: Optional[str] = Field(None, max_length=500,
                                  description="Required for 'terminated'.")


class ExperimentResponse(BaseModel):
    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    hypothesis: Optional[str] = None
    primary_metric_code: Optional[str] = None
    secondary_metric_codes: List[str] = Field(default_factory=list)
    variants: List[Dict[str, Any]] = Field(default_factory=list)
    status: str
    owner: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    account_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, e: Any) -> "ExperimentResponse":
        return cls(
            id=e.id,
            code=e.code,
            name=e.name,
            description=e.description,
            hypothesis=e.hypothesis,
            primary_metric_code=e.primary_metric_code,
            secondary_metric_codes=e.secondary_metric_codes or [],
            variants=e.variants or [],
            status=e.status,
            owner=e.owner,
            started_at=e.started_at,
            ended_at=e.ended_at,
            account_id=e.account_id,
            created_at=e.created_at,
            updated_at=e.updated_at,
        )


class ExperimentListResponse(BaseModel):
    items: List[ExperimentResponse]
    total: int
    page: int
    page_size: int


# ========== ExperimentResult ==========

class ExperimentResultCreate(BaseModel):
    """Record one computed result snapshot for an experiment variant + metric.

    ``experiment_id`` is carried by the path
    (``/experiments/{experiment_id}/results``) — the body field is optional
    and the router overwrites it with the path value, so an omitted body
    field is valid.
    """

    experiment_id: Optional[UUID] = None
    variant_label: str = Field(..., min_length=1, max_length=100)
    metric_code: str = Field(..., min_length=1, max_length=100)
    sample_size: int = Field(0, ge=0)
    metric_value: Decimal = Field(..., decimal_places=6,
                                  description="Observed metric value for the variant.")
    baseline_value: Optional[Decimal] = Field(None, decimal_places=6,
                                              description="Control / baseline value for the same metric.")
    lift_percent: Optional[Decimal] = Field(None, decimal_places=4,
                                            description="Relative lift vs baseline, in percent.")
    p_value: Optional[Decimal] = Field(None, decimal_places=6, ge=0, le=1)
    is_significant: Optional[bool] = None
    stats: Dict[str, Any] = Field(default_factory=dict,
                                  description="Raw test stats (test used, alpha, CI bounds...).")
    computed_at: Optional[datetime] = None


class ExperimentResultUpdate(BaseModel):
    sample_size: Optional[int] = Field(None, ge=0)
    metric_value: Optional[Decimal] = Field(None, decimal_places=6)
    baseline_value: Optional[Decimal] = Field(None, decimal_places=6)
    lift_percent: Optional[Decimal] = Field(None, decimal_places=4)
    p_value: Optional[Decimal] = Field(None, decimal_places=6, ge=0, le=1)
    is_significant: Optional[bool] = None
    stats: Optional[Dict[str, Any]] = None
    computed_at: Optional[datetime] = None


class ExperimentResultResponse(BaseModel):
    id: UUID
    experiment_id: UUID
    variant_label: str
    metric_code: str
    sample_size: int
    metric_value: Decimal
    baseline_value: Optional[Decimal] = None
    lift_percent: Optional[Decimal] = None
    p_value: Optional[Decimal] = None
    is_significant: Optional[bool] = None
    stats: Dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime

    @classmethod
    def from_model(cls, r: Any) -> "ExperimentResultResponse":
        return cls(
            id=r.id,
            experiment_id=r.experiment_id,
            variant_label=r.variant_label,
            metric_code=r.metric_code,
            sample_size=r.sample_size,
            metric_value=r.metric_value,
            baseline_value=r.baseline_value,
            lift_percent=r.lift_percent,
            p_value=r.p_value,
            is_significant=r.is_significant,
            stats=r.stats or {},
            computed_at=r.computed_at,
        )


class ExperimentResultListResponse(BaseModel):
    items: List[ExperimentResultResponse]
    total: int
    page: int
    page_size: int


# ========== P6AN-08: results summary / variant comparison ==========

class ExperimentResultSummaryRow(BaseModel):
    """One variant's latest snapshot for one metric, with computed lift
    against the baseline variant when both exist and the baseline is
    non-zero. Lift is derived here from the two latest values — a
    *derived* field, not stored (the stored ``lift_percent`` of a single
    snapshot, when present, is carried through in ``stats.lift_percent``
    for provenance)."""

    variant_label: str
    metric_value: str
    sample_size: int
    baseline_value: Optional[str] = None
    computed_at: datetime
    # Derived comparison (None when the baseline variant has no row for
    # this metric, or its baseline value is zero):
    lift_vs_baseline_percent: Optional[str] = None
    p_value: Optional[str] = None
    is_significant: Optional[bool] = None


class ExperimentResultSummaryMetric(BaseModel):
    metric_code: str
    is_primary: bool
    baseline_variant: Optional[str] = None
    note: str = Field(
        "",
        description=(
            "Plain-language significance / comparison note. No statistical "
            "inference library is used this wave (out of scope per the task "
            "card): a row is reported significant when its own p_value is "
            "present and below the requested threshold; otherwise the note "
            "says so explicitly."
        ),
    )
    variants: List[ExperimentResultSummaryRow]


class ExperimentResultSummaryResponse(BaseModel):
    """GET /experiments/{id}/results/summary — per-metric variant
    comparison for one experiment (basic comparison only, P6AN-08)."""

    experiment_id: UUID
    code: str
    name: str
    status: str
    baseline_variant: Optional[str] = Field(
        None,
        description=(
            "Baseline variant label: the first variant labelled 'control' in "
            "the experiment's variants list, else the first variant's label, "
            "else null. Lifts are computed against this variant."
        ),
    )
    significance_threshold: float = 0.05
    metrics: List[ExperimentResultSummaryMetric]
    notes: List[str] = Field(default_factory=list)


# ========== Funnel (P6AN-03 — acquisition funnel computation) ==========

class FunnelStage(BaseModel):
    """One stage of a computed funnel.

    ``count`` is the *reached* (cumulative) count: leads that have reached at
    least this stage. ``conversion_rate`` is reached(this)/reached(previous)
    (None for the top stage or a zero denominator). ``overall_rate`` is
    reached(this)/reached(top).
    """

    key: str
    name: str
    status: Optional[str] = Field(
        None, description="The Lead.status this stage maps to (None = unresolvable)."
    )
    count: int = 0
    conversion_rate: Optional[float] = None
    overall_rate: Optional[float] = None


class FunnelResponse(BaseModel):
    """GET /api/v1/analytics/funnel — computed acquisition funnel.

    An empty scope returns a well-formed funnel with all stages at ``count=0``
    and null rates (never a 500). ``total`` is the top-of-funnel reached count.
    """

    funnel_code: str
    stages: List[FunnelStage]
    total: int = 0
    conversion_rate: Optional[float] = Field(
        None, description="End-to-end top -> bottom conversion rate (None when empty)."
    )
    filters: Dict[str, Any] = Field(
        default_factory=dict, description="Normalized request filters (echoed back)."
    )
