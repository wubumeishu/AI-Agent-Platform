"""Analytics CRUD router (Phase 6 / P6AN-01).

Endpoints (all under ``/api/v1/analytics``):

    POST   /widgets                        create dashboard widget
    GET    /widgets                        list widgets (filter + pagination)
    GET    /widgets/{widget_id}            fetch one widget
    PUT    /widgets/{widget_id}            update mutable fields
    DELETE /widgets/{widget_id}            soft-delete

    POST   /funnel-steps                   register a funnel step
    GET    /funnel-steps                   list steps (funnel_code filter)
    GET    /funnel-steps/{step_id}        fetch one step
    PUT    /funnel-steps/{step_id}        update mutable fields
    DELETE /funnel-steps/{step_id}        soft-delete

    POST   /metrics                        register a metric definition
    GET    /metrics                        list metrics (category filter)
    GET    /metrics/{metric_id}           fetch by id
    PUT    /metrics/{metric_id}           update mutable fields
    DELETE /metrics/{metric_id}          soft-delete

    POST   /experiments                    create experiment (draft)
    GET    /experiments                    list experiments (status filter)
    GET    /experiments/{experiment_id}   fetch one experiment
    PUT    /experiments/{experiment_id}   update mutable fields
    POST   /experiments/{experiment_id}/status   drive the state machine
    DELETE /experiments/{experiment_id}  soft-delete

    POST   /experiments/{experiment_id}/results   record a result snapshot
    GET    /experiments/{experiment_id}/results   list result snapshots
    GET    /experiments/{experiment_id}/results/summary   P6AN-08 per-metric
                                                         variant comparison
    GET    /experiment-results/{result_id}        fetch one result
    PUT    /experiment-results/{result_id}        update one result
    DELETE /experiment-results/{result_id}        delete one result

P6AN-08 delta (this card)
=========================
- Variant traffic-allocation rule enforced on create/update of an
  experiment: once any variant carries a ``share``/``traffic``/
  ``traffic_share`` value, the provided shares must sum to 1.0
  (±1e-6). Violation → 409 (AnalyticsConflictError). Legacy free-form
  variant lists (no shares) pass through untouched.
- ``GET /experiments/{id}/results/summary`` returns the latest snapshot
  per (variant, metric), a derived lift vs the baseline variant, and a
  plain-language significance note. Basic comparison only — no
  statistical-inference library (out of scope for P6AN-08).

P6AN-03 delta (this card)
=========================
- ``GET /api/v1/analytics/funnel`` — acquisition-funnel computation
  (service: ``app.services.funnel_service.compute_funnel``). Reads
  ``Lead.status`` counts (single GROUP BY) and returns per-stage
  *reached* counts + stage/overall conversion rates. ``FunnelStep``
  definitions above are the catalog; this endpoint is the compute
  layer. Filters: ``agent_id``, ``platform_id``, ``range``
  (7d/30d/90d/365d/all), ``from``, ``to``, ``funnel_code``.
  Empty scope → 200 with all-stage counts 0 and null rates.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.analytics import (
    DashboardWidgetCreate,
    DashboardWidgetListResponse,
    DashboardWidgetResponse,
    DashboardWidgetUpdate,
    ExperimentCreate,
    ExperimentListResponse,
    ExperimentResponse,
    ExperimentStatusUpdate,
    ExperimentUpdate,
    ExperimentResultCreate,
    ExperimentResultListResponse,
    ExperimentResultResponse,
    ExperimentResultSummaryResponse,
    ExperimentResultUpdate,
    FunnelStepCreate,
    FunnelStepListResponse,
    FunnelStepResponse,
    FunnelStepUpdate,
    FunnelResponse,
    MetricDefinitionCreate,
    MetricDefinitionListResponse,
    MetricDefinitionResponse,
    MetricDefinitionUpdate,
)
from app.services.analytics_service import (
    AnalyticsConflictError,
    AnalyticsEntityNotFoundError,
    DashboardWidgetService,
    ExperimentService,
    ExperimentStatusError,
    FunnelStepService,
    MetricDefinitionService,
)
from app.schemas.conversation_metrics import ConversationMetricsResponse
from app.services.conversation_metrics_service import (
    DEFAULT_INTENT_ACCURACY_THRESHOLD,
    ConversationMetricsService,
)
from app.schemas.lead_conversion import LeadConversionResponse
from app.services.lead_conversion_service import (
    LeadConversionError,
    LeadConversionService,
)

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


# ========== helpers ==========

def _raise_conflict(err: AnalyticsConflictError) -> None:
    raise HTTPException(status_code=409, detail=err.detail)


def _raise_not_found(err: AnalyticsEntityNotFoundError) -> None:
    raise HTTPException(status_code=404, detail=str(err))


# ========== DashboardWidget ==========

@router.post("/widgets", response_model=DashboardWidgetResponse, status_code=201)
async def create_widget(
    data: DashboardWidgetCreate, db: AsyncSession = Depends(get_db)
):
    svc = DashboardWidgetService(db)
    return DashboardWidgetResponse.from_model(await svc.create(data))


@router.get("/widgets", response_model=DashboardWidgetListResponse)
async def list_widgets(
    widget_type: Optional[str] = Query(None, description="Filter by widget type"),
    enabled: Optional[bool] = Query(None, description="Filter by enabled flag"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    svc = DashboardWidgetService(db)
    items, total = await svc.list(widget_type=widget_type, enabled=enabled,
                                 page=page, page_size=page_size)
    return DashboardWidgetListResponse(
        items=[DashboardWidgetResponse.from_model(w) for w in items],
        total=total, page=page, page_size=page_size,
    )


@router.get("/widgets/{widget_id}", response_model=DashboardWidgetResponse)
async def get_widget(widget_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = DashboardWidgetService(db)
    widget = await svc.get(widget_id)
    if widget is None:
        raise HTTPException(status_code=404, detail=f"Dashboard widget {widget_id} not found")
    return DashboardWidgetResponse.from_model(widget)


@router.put("/widgets/{widget_id}", response_model=DashboardWidgetResponse)
async def update_widget(
    widget_id: UUID, data: DashboardWidgetUpdate, db: AsyncSession = Depends(get_db)
):
    svc = DashboardWidgetService(db)
    widget = await svc.get(widget_id)
    if widget is None:
        raise HTTPException(status_code=404, detail=f"Dashboard widget {widget_id} not found")
    return DashboardWidgetResponse.from_model(await svc.update(widget, data))


@router.delete("/widgets/{widget_id}", status_code=204)
async def delete_widget(widget_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = DashboardWidgetService(db)
    deleted = await svc.delete(widget_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Dashboard widget {widget_id} not found")
    return None


# ========== FunnelStep ==========

@router.post("/funnel-steps", response_model=FunnelStepResponse, status_code=201)
async def create_funnel_step(
    data: FunnelStepCreate, db: AsyncSession = Depends(get_db)
):
    svc = FunnelStepService(db)
    try:
        step = await svc.create(data)
    except AnalyticsConflictError as e:
        _raise_conflict(e)
    return FunnelStepResponse.from_model(step)


@router.get("/funnel-steps", response_model=FunnelStepListResponse)
async def list_funnel_steps(
    funnel_code: Optional[str] = Query(None, description="Filter by funnel code"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    svc = FunnelStepService(db)
    items, total = await svc.list(funnel_code=funnel_code, page=page, page_size=page_size)
    return FunnelStepListResponse(
        items=[FunnelStepResponse.from_model(s) for s in items],
        total=total, page=page, page_size=page_size,
    )


@router.get("/funnel-steps/{step_id}", response_model=FunnelStepResponse)
async def get_funnel_step(step_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = FunnelStepService(db)
    step = await svc.get(step_id)
    if step is None:
        raise HTTPException(status_code=404, detail=f"Funnel step {step_id} not found")
    return FunnelStepResponse.from_model(step)


@router.put("/funnel-steps/{step_id}", response_model=FunnelStepResponse)
async def update_funnel_step(
    step_id: UUID, data: FunnelStepUpdate, db: AsyncSession = Depends(get_db)
):
    svc = FunnelStepService(db)
    step = await svc.get(step_id)
    if step is None:
        raise HTTPException(status_code=404, detail=f"Funnel step {step_id} not found")
    try:
        return FunnelStepResponse.from_model(await svc.update(step, data))
    except AnalyticsConflictError as e:
        _raise_conflict(e)


@router.delete("/funnel-steps/{step_id}", status_code=204)
async def delete_funnel_step(step_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = FunnelStepService(db)
    deleted = await svc.delete(step_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Funnel step {step_id} not found")
    return None


# ========== Funnel computation (P6AN-03) ==========

@router.get("/funnel", response_model=FunnelResponse)
async def compute_acquisition_funnel(
    agent_id: Optional[UUID] = Query(None, description="Restrict to leads bound to this agent."),
    platform_id: Optional[UUID] = Query(None, description="Restrict to leads under this platform."),
    range: Optional[str] = Query(
        "30d",
        pattern="^(7d|30d|90d|365d|all)$",
        description="Lead-entry window preset on lead.created_at.",
    ),
    from_date: Optional[str] = Query(
        None, alias="from", description="ISO date/ISO datetime lower bound (overrides range)."
    ),
    to_date: Optional[str] = Query(
        None, alias="to", description="ISO date/ISO datetime upper bound (exclusive)."
    ),
    funnel_code: Optional[str] = Query(
        None,
        description=(
            "A registered custom funnel_code (its funnel_step rows drive the "
            "stage order). Defaults to the built-in acquisition funnel."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """Compute the acquisition funnel: per-stage reached counts + conversion rates.

    Stages are ``new -> contacted -> qualified -> converted`` (the Lead
    status machine). ``count`` is the cumulative *reached* count; a lead in a
    later stage counts toward every earlier stage. Filters (agent / platform /
    time window) are composed into one GROUP-BY over live leads. An empty
    scope returns a well-formed empty funnel (all counts 0, null rates) --
    never a 500.
    """
    from app.services.funnel_service import compute_funnel

    return await compute_funnel(
        db,
        agent_id=agent_id,
        platform_id=platform_id,
        range=range,
        from_date=from_date,
        to_date=to_date,
        funnel_code=funnel_code,
    )


# ========== MetricDefinition ==========

@router.post("/metrics", response_model=MetricDefinitionResponse, status_code=201)
async def create_metric(
    data: MetricDefinitionCreate, db: AsyncSession = Depends(get_db)
):
    svc = MetricDefinitionService(db)
    try:
        metric = await svc.create(data)
    except AnalyticsConflictError as e:
        _raise_conflict(e)
    return MetricDefinitionResponse.from_model(metric)


@router.get("/metrics", response_model=MetricDefinitionListResponse)
async def list_metrics(
    category: Optional[str] = Query(None, description="Filter by category"),
    enabled: Optional[bool] = Query(None, description="Filter by enabled flag"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    svc = MetricDefinitionService(db)
    items, total = await svc.list(category=category, enabled=enabled,
                                 page=page, page_size=page_size)
    return MetricDefinitionListResponse(
        items=[MetricDefinitionResponse.from_model(m) for m in items],
        total=total, page=page, page_size=page_size,
    )


@router.get("/metrics/{metric_id}", response_model=MetricDefinitionResponse)
async def get_metric(metric_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = MetricDefinitionService(db)
    metric = await svc.get(metric_id)
    if metric is None:
        raise HTTPException(status_code=404, detail=f"Metric definition {metric_id} not found")
    return MetricDefinitionResponse.from_model(metric)


@router.put("/metrics/{metric_id}", response_model=MetricDefinitionResponse)
async def update_metric(
    metric_id: UUID, data: MetricDefinitionUpdate, db: AsyncSession = Depends(get_db)
):
    svc = MetricDefinitionService(db)
    metric = await svc.get(metric_id)
    if metric is None:
        raise HTTPException(status_code=404, detail=f"Metric definition {metric_id} not found")
    return MetricDefinitionResponse.from_model(await svc.update(metric, data))


@router.delete("/metrics/{metric_id}", status_code=204)
async def delete_metric(metric_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = MetricDefinitionService(db)
    deleted = await svc.delete(metric_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Metric definition {metric_id} not found")
    return None


# ========== Experiment ==========

@router.post("/experiments", response_model=ExperimentResponse, status_code=201)
async def create_experiment(
    data: ExperimentCreate, db: AsyncSession = Depends(get_db)
):
    svc = ExperimentService(db)
    try:
        exp = await svc.create(data)
    except AnalyticsConflictError as e:
        _raise_conflict(e)
    return ExperimentResponse.from_model(exp)


@router.get("/experiments", response_model=ExperimentListResponse)
async def list_experiments(
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    svc = ExperimentService(db)
    items, total = await svc.list(status=status, page=page, page_size=page_size)
    return ExperimentListResponse(
        items=[ExperimentResponse.from_model(e) for e in items],
        total=total, page=page, page_size=page_size,
    )


@router.get("/experiments/{experiment_id}", response_model=ExperimentResponse)
async def get_experiment(experiment_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = ExperimentService(db)
    exp = await svc.get(experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    return ExperimentResponse.from_model(exp)


@router.put("/experiments/{experiment_id}", response_model=ExperimentResponse)
async def update_experiment(
    experiment_id: UUID, data: ExperimentUpdate, db: AsyncSession = Depends(get_db)
):
    svc = ExperimentService(db)
    exp = await svc.get(experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    try:
        return ExperimentResponse.from_model(await svc.update(exp, data))
    except AnalyticsConflictError as e:
        # P6AN-08: a rejected variant traffic allocation is a 409, not a 500.
        _raise_conflict(e)


@router.post("/experiments/{experiment_id}/status", response_model=ExperimentResponse)
async def set_experiment_status(
    experiment_id: UUID, data: ExperimentStatusUpdate, db: AsyncSession = Depends(get_db)
):
    svc = ExperimentService(db)
    exp = await svc.get(experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    try:
        updated = await svc.set_status(exp, data)
    except ExperimentStatusError as e:
        raise HTTPException(
            status_code=409,
            detail={"experiment_id": str(experiment_id),
                    "from_state": e.from_state, "to_state": e.to_state,
                    "message": e.message},
        )
    return ExperimentResponse.from_model(updated)


@router.delete("/experiments/{experiment_id}", status_code=204)
async def delete_experiment(experiment_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = ExperimentService(db)
    deleted = await svc.delete(experiment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    return None


# ========== ExperimentResult ==========

@router.post(
    "/experiments/{experiment_id}/results",
    response_model=ExperimentResultResponse,
    status_code=201,
)
async def create_experiment_result(
    experiment_id: UUID, data: ExperimentResultCreate, db: AsyncSession = Depends(get_db)
):
    svc = ExperimentService(db)
    # Path is the source of truth for the owning experiment.
    data.experiment_id = experiment_id
    try:
        result = await svc.add_result(data)
    except AnalyticsEntityNotFoundError as e:
        _raise_not_found(e)
    return ExperimentResultResponse.from_model(result)


@router.get(
    "/experiments/{experiment_id}/results",
    response_model=ExperimentResultListResponse,
)
async def list_experiment_results(
    experiment_id: UUID,
    variant_label: Optional[str] = Query(None, description="Filter by variant label"),
    metric_code: Optional[str] = Query(None, description="Filter by metric code"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    svc = ExperimentService(db)
    exp = await svc.get(experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    items, total = await svc.list_results(
        experiment_id, variant_label=variant_label, metric_code=metric_code,
        page=page, page_size=page_size,
    )
    return ExperimentResultListResponse(
        items=[ExperimentResultResponse.from_model(r) for r in items],
        total=total, page=page, page_size=page_size,
    )


@router.get(
    "/experiments/{experiment_id}/results/summary",
    response_model=ExperimentResultSummaryResponse,
)
async def summarize_experiment_results(
    experiment_id: UUID,
    significance_threshold: float = Query(
        0.05, ge=0.0, le=1.0,
        description="p-value cutoff used for the 'significant' note (no inference lib this wave).",
    ),
    db: AsyncSession = Depends(get_db),
):
    """P6AN-08: per-metric variant comparison for one experiment.

    Returns the latest result snapshot per (variant, metric), a derived lift
    vs the baseline variant, and a plain-language significance note. Basic
    comparison only — no statistical-inference library (out of scope for
    P6AN-08).
    """
    svc = ExperimentService(db)
    try:
        return await svc.summarize_results(
            experiment_id, significance_threshold=significance_threshold
        )
    except AnalyticsEntityNotFoundError as e:
        _raise_not_found(e)


@router.get("/experiment-results/{result_id}", response_model=ExperimentResultResponse)
async def get_experiment_result(result_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = ExperimentService(db)
    result = await svc.get_result(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Experiment result {result_id} not found")
    return ExperimentResultResponse.from_model(result)


@router.put("/experiment-results/{result_id}", response_model=ExperimentResultResponse)
async def update_experiment_result(
    result_id: UUID, data: ExperimentResultUpdate, db: AsyncSession = Depends(get_db)
):
    svc = ExperimentService(db)
    result = await svc.get_result(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Experiment result {result_id} not found")
    return ExperimentResultResponse.from_model(await svc.update_result(result, data))


@router.delete("/experiment-results/{result_id}", status_code=204)
async def delete_experiment_result(result_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = ExperimentService(db)
    deleted = await svc.delete_result(result_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Experiment result {result_id} not found")
    return None


# ========== Conversation Metrics (Phase 6 / P6AN-04) ==========
#
# AI conversation quality & efficiency. Read-only aggregation over
# conversation / message / intents (no writes, no ORM session churn).
# Filter by agent (via customer binding), by platform (channel), by intent
# type, and over a time ``range``. Empty scope returns safe default values.

@router.get(
    "/conversations",
    response_model=ConversationMetricsResponse,
    summary="P6AN-04: AI conversation quality & efficiency metrics",
)
async def get_conversation_metrics(
    agent_id: Optional[UUID] = Query(
        None,
        description="Scope to conversations whose customer is bound to this agent "
                    "(via agent_customer_binding, live rows only).",
    ),
    range: str = Query(
        "30d",
        description="Time window on conversation.created_at: one of 1d/7d/30d/90d/365d. "
                    "Unknown values fall back to 30d.",
    ),
    intent_type: Optional[str] = Query(
        None,
        max_length=100,
        description="Only count conversations carrying at least one live intent of this type.",
    ),
    channel: Optional[str] = Query(
        None,
        max_length=50,
        description="Platform / channel filter (conversation.channel), e.g. wechat, web, douyin.",
    ),
    accuracy_threshold: float = Query(
        DEFAULT_INTENT_ACCURACY_THRESHOLD,
        ge=0.0,
        le=1.0,
        description="Confidence bar for the intent-accuracy proxy: an intent counts as "
                    "accurate when confidence >= threshold AND an action was matched.",
    ),
    db: AsyncSession = Depends(get_db),
):
    svc = ConversationMetricsService(db)
    return await svc.compute(
        agent_id=agent_id,
        range_value=range,
        intent_type=intent_type,
        channel=channel,
        threshold=accuracy_threshold,
    )


# ========== Lead Conversion (Phase 6 / P6AN-05) ==========
#
# Lead funnel (new -> contacted -> qualified -> converted) + average
# conversion cycle, read-only aggregation over lead / agent_customer_binding /
# agent / conversation / lifecycle_stage_log. Filter by Agent and/or channel,
# over a created_at window; group by Agent or channel. No writes.

@router.get(
    "/leads/conversion",
    response_model=LeadConversionResponse,
    summary="P6AN-05: lead conversion funnel + average conversion cycle",
)
async def get_lead_conversion(
    agent_id: Optional[UUID] = Query(
        None,
        description="Scope to leads whose customer is bound to this agent "
                    "(via agent_customer_binding, live rows).",
    ),
    channel: Optional[str] = Query(
        None,
        max_length=50,
        description="Platform / channel filter (conversation.channel) for "
                    "conversation-source leads, e.g. wechat, web, douyin. "
                    "Non-conversation leads are excluded when set.",
    ),
    from_date: Optional[datetime] = Query(
        None,
        description="Inclusive lower bound on lead.created_at (UTC).",
    ),
    to_date: Optional[datetime] = Query(
        None,
        description="Inclusive upper bound on lead.created_at (UTC).",
    ),
    group_by: str = Query(
        "overall",
        pattern="^(overall|agent|channel)$",
        description="Aggregation: overall | agent | channel.",
    ),
    db: AsyncSession = Depends(get_db),
):
    svc = LeadConversionService(db)
    try:
        data = await svc.compute(
            agent_id=agent_id,
            channel=channel,
            from_date=from_date,
            to_date=to_date,
            group_by=group_by,
        )
    except LeadConversionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return LeadConversionResponse(**data)
