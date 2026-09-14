"""Analytics business services (Phase 6 / P6AN-01).

CRUD + experiment state-machine logic for the five analytics entities.
Services depend only on an ``AsyncSession`` (repo convention — see
``QueueWorkerEngine`` / ``NurturePlanService``) so they are unit-testable
against a fake session. The router layer translates the domain exceptions
below into HTTP status codes; no business rule lives in a route handler.

Uniqueness rules (funnel step seq, metric code, experiment code) are
backed by partial unique indexes in migration 028 — the service catches
the integrity violation and surfaces it as :class:`AnalyticsConflictError`
(409) instead of a raw 500.

Pagination here is offset/limit on *definition* data (small, curated
catalogs): one query for the page rows, one for the count. No
cursor-based paging needed at this scale.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal

from app.db.models.analytics import (
    DashboardWidget,
    Experiment,
    ExperimentResult,
    EXPERIMENT_TRANSITIONS,
    FunnelStep,
    MetricDefinition,
)
from app.schemas.analytics import (
    DashboardWidgetCreate,
    DashboardWidgetUpdate,
    ExperimentCreate,
    ExperimentStatusUpdate,
    ExperimentUpdate,
    ExperimentResultCreate,
    ExperimentResultUpdate,
    ExperimentResultSummaryMetric,
    ExperimentResultSummaryResponse,
    ExperimentResultSummaryRow,
    FunnelStepCreate,
    FunnelStepUpdate,
    MetricDefinitionCreate,
    MetricDefinitionUpdate,
)

logger = logging.getLogger(__name__)


# ========== Domain exceptions (router translates to HTTP) ==========

class AnalyticsEntityNotFoundError(Exception):
    """Raised when an analytics entity id (or soft ref) does not resolve to a live row."""

    def __init__(self, entity: str, identifier: Any):
        self.entity = entity
        self.identifier = identifier
        super().__init__(f"{entity} {identifier} not found")


class AnalyticsConflictError(Exception):
    """Raised on a uniqueness conflict (seq / code already taken by a live row)."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class ExperimentStatusError(Exception):
    """Raised on an illegal experiment status transition (or missing terminate reason)."""

    def __init__(self, from_state: str, to_state: str, message: str):
        self.from_state = from_state
        self.to_state = to_state
        self.message = message
        super().__init__(message)


# ========== Shared helpers ==========

async def _select_one(db: AsyncSession, model: type, where: Any) -> Any:
    """Return the single live row matching ``where`` (or None)."""
    res = await db.execute(
        select(model).where(*where, model.is_deleted == False)  # noqa: E712
    )
    return res.scalar_one_or_none()


# ========== DashboardWidgetService ==========

class DashboardWidgetService:
    """CRUD for dashboard widget definitions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: DashboardWidgetCreate) -> DashboardWidget:
        widget = DashboardWidget(
            name=data.name,
            description=data.description,
            widget_type=data.widget_type,
            config=data.config or {},
            metric_code=data.metric_code,
            funnel_code=data.funnel_code,
            refresh_interval_seconds=data.refresh_interval_seconds,
            position=data.position,
            enabled=data.enabled,
            account_id=data.account_id,
        )
        self.db.add(widget)
        await self.db.commit()
        await self.db.refresh(widget)
        logger.info("Created dashboard widget %s (%s)", widget.id, widget.name)
        return widget

    async def get(self, widget_id: UUID) -> Optional[DashboardWidget]:
        return await _select_one(
            self.db, DashboardWidget, [DashboardWidget.id == widget_id]
        )

    async def list(self, widget_type: Optional[str] = None,
                   enabled: Optional[bool] = None,
                   page: int = 1, page_size: int = 20) -> Tuple[List[DashboardWidget], int]:
        q = select(DashboardWidget).where(DashboardWidget.is_deleted == False)  # noqa: E712
        if widget_type:
            q = q.where(DashboardWidget.widget_type == widget_type)
        if enabled is not None:
            q = q.where(DashboardWidget.enabled == enabled)
        total = len((await self.db.execute(q)).scalars().all())
        page_q = (
            q.order_by(DashboardWidget.position, DashboardWidget.created_at)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.db.execute(page_q)).scalars().all())
        return items, total

    async def update(self, widget: DashboardWidget,
                     data: DashboardWidgetUpdate) -> DashboardWidget:
        if data.name is not None:
            widget.name = data.name
        if data.description is not None:
            widget.description = data.description
        if data.widget_type is not None:
            widget.widget_type = data.widget_type
        if data.config is not None:
            widget.config = data.config
        if data.metric_code is not None:
            widget.metric_code = data.metric_code
        if data.funnel_code is not None:
            widget.funnel_code = data.funnel_code
        if data.refresh_interval_seconds is not None:
            widget.refresh_interval_seconds = data.refresh_interval_seconds
        if data.position is not None:
            widget.position = data.position
        if data.enabled is not None:
            widget.enabled = data.enabled
        await self.db.commit()
        await self.db.refresh(widget)
        return widget

    async def delete(self, widget_id: UUID) -> bool:
        widget = await self.get(widget_id)
        if widget is None:
            return False
        widget.is_deleted = True
        await self.db.commit()
        logger.info("Soft-deleted dashboard widget %s", widget_id)
        return True


# ========== FunnelStepService ==========

class FunnelStepService:
    """CRUD for funnel step definitions (seq unique per funnel among live rows)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: FunnelStepCreate) -> FunnelStep:
        step = FunnelStep(
            funnel_code=data.funnel_code,
            name=data.name,
            description=data.description,
            seq=data.seq,
            entry_criteria=data.entry_criteria or {},
            conversion_criteria=data.conversion_criteria,
            config=data.config or {},
            account_id=data.account_id,
        )
        self.db.add(step)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise AnalyticsConflictError(
                f"Funnel step seq={data.seq} already exists for funnel "
                f"{data.funnel_code!r}"
            ) from None
        await self.db.refresh(step)
        logger.info("Created funnel step %s (%s, seq=%s)", step.id, step.funnel_code, step.seq)
        return step

    async def get(self, step_id: UUID) -> Optional[FunnelStep]:
        return await _select_one(
            self.db, FunnelStep, [FunnelStep.id == step_id]
        )

    async def list(self, funnel_code: Optional[str] = None,
                   page: int = 1, page_size: int = 20) -> Tuple[List[FunnelStep], int]:
        q = select(FunnelStep).where(FunnelStep.is_deleted == False)  # noqa: E712
        if funnel_code:
            q = q.where(FunnelStep.funnel_code == funnel_code)
        total = len((await self.db.execute(q)).scalars().all())
        page_q = (
            q.order_by(FunnelStep.funnel_code, FunnelStep.seq)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.db.execute(page_q)).scalars().all())
        return items, total

    async def update(self, step: FunnelStep, data: FunnelStepUpdate) -> FunnelStep:
        if data.name is not None:
            step.name = data.name
        if data.description is not None:
            step.description = data.description
        if data.seq is not None:
            step.seq = data.seq
        if data.entry_criteria is not None:
            step.entry_criteria = data.entry_criteria
        if data.conversion_criteria is not None:
            step.conversion_criteria = data.conversion_criteria
        if data.config is not None:
            step.config = data.config
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise AnalyticsConflictError(
                f"Funnel step seq={step.seq} already exists for funnel {step.funnel_code!r}"
            ) from None
        await self.db.refresh(step)
        return step

    async def delete(self, step_id: UUID) -> bool:
        step = await self.get(step_id)
        if step is None:
            return False
        step.is_deleted = True
        await self.db.commit()
        logger.info("Soft-deleted funnel step %s", step_id)
        return True


# ========== MetricDefinitionService ==========

class MetricDefinitionService:
    """CRUD for metric definitions (code unique among live rows)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: MetricDefinitionCreate) -> MetricDefinition:
        metric = MetricDefinition(
            code=data.code,
            name=data.name,
            description=data.description,
            category=data.category,
            value_type=data.value_type,
            unit=data.unit,
            aggregation=data.aggregation,
            formula=data.formula or {},
            source=data.source,
            window_days=data.window_days,
            enabled=data.enabled,
            account_id=data.account_id,
        )
        self.db.add(metric)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise AnalyticsConflictError(
                f"Metric definition code {data.code!r} already exists"
            ) from None
        await self.db.refresh(metric)
        logger.info("Created metric definition %s (%s)", metric.id, metric.code)
        return metric

    async def get(self, metric_id: UUID) -> Optional[MetricDefinition]:
        return await _select_one(
            self.db, MetricDefinition, [MetricDefinition.id == metric_id]
        )

    async def get_by_code(self, code: str) -> Optional[MetricDefinition]:
        return await _select_one(
            self.db, MetricDefinition, [MetricDefinition.code == code]
        )

    async def list(self, category: Optional[str] = None,
                   enabled: Optional[bool] = None,
                   page: int = 1, page_size: int = 20) -> Tuple[List[MetricDefinition], int]:
        q = select(MetricDefinition).where(MetricDefinition.is_deleted == False)  # noqa: E712
        if category:
            q = q.where(MetricDefinition.category == category)
        if enabled is not None:
            q = q.where(MetricDefinition.enabled == enabled)
        total = len((await self.db.execute(q)).scalars().all())
        page_q = (
            q.order_by(MetricDefinition.code)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.db.execute(page_q)).scalars().all())
        return items, total

    async def update(self, metric: MetricDefinition,
                     data: MetricDefinitionUpdate) -> MetricDefinition:
        if data.name is not None:
            metric.name = data.name
        if data.description is not None:
            metric.description = data.description
        if data.category is not None:
            metric.category = data.category
        if data.value_type is not None:
            metric.value_type = data.value_type
        if data.unit is not None:
            metric.unit = data.unit
        if data.aggregation is not None:
            metric.aggregation = data.aggregation
        if data.formula is not None:
            metric.formula = data.formula
        if data.source is not None:
            metric.source = data.source
        if data.window_days is not None:
            metric.window_days = data.window_days
        if data.enabled is not None:
            metric.enabled = data.enabled
        await self.db.commit()
        await self.db.refresh(metric)
        return metric

    async def delete(self, metric_id: UUID) -> bool:
        metric = await self.get(metric_id)
        if metric is None:
            return False
        metric.is_deleted = True
        await self.db.commit()
        logger.info("Soft-deleted metric definition %s (%s)", metric_id, metric.code)
        return True


# ========== P6AN-08: variant traffic-allocation rules ==========

#: Keys under which a variant may carry its traffic share.
_VARIANT_SHARE_KEYS = ("share", "traffic", "traffic_share")
#: Tolerance for the "provided shares sum to 1.0" rule (float dust).
_VARIANT_SHARE_TOL = 1e-6
#: Tolerance for a "share within [0, 1]" check.
_VARIANT_SHARE_BOUNDS_TOL = 1e-9


def _variant_share(v: Any) -> Optional[float]:
    """Return the traffic share of a variant entry, or None if it carries none.

    Only dicts with one of ``_VARIANT_SHARE_KEYS`` participate in the
    structured rule; everything else (plain-string labels, config-only
    dicts, P6AN-01 legacy free-form entries) is treated as unallocated and
    skipped. A string numeric share ("0.5") is coerced; a non-numeric
    value raises ValueError.
    """
    if not isinstance(v, dict):
        return None
    for key in _VARIANT_SHARE_KEYS:
        if key in v and v[key] is not None:
            raw = v[key]
            try:
                return float(raw)
            except (TypeError, ValueError):
                raise AnalyticsConflictError(
                    f"Variant {key!r} must be a number in [0, 1], got {raw!r}"
                ) from None
    return None


def _variant_label(v: Any) -> Optional[str]:
    """Best-effort variant label (None for free-form entries without one)."""
    if isinstance(v, dict):
        lab = v.get("label")
        return str(lab) if lab is not None else None
    return None


def _validate_variants(variants: Any) -> List[Dict[str, Any]]:
    """P6AN-08 structured traffic-allocation rule for ``experiment.variants``.

    Accepts the P6AN-01 free-form list and returns a normalized copy:
    structured entries (dicts carrying a share) are type-checked, their
    share coerced to float and stored under the canonical ``share`` key;
    unstructured entries pass through unchanged, so legacy data keeps
    working.

    All-or-nothing rule (documented in ``docs/ANALYTICS-API.md``):
    once ANY entry carries a share, the sum of the provided shares must
    equal 1.0 (±1e-6). Out-of-range shares, a partial/over-allocated sum,
    and a malformed (non-numeric) share all raise
    :class:`AnalyticsConflictError` (→ HTTP 409). Entries that carry no
    share are ignored (legacy free-form lists keep working).

    A non-list ``variants`` value raises ValueError — defensively only;
    the API's Pydantic schema (``List[Dict[str, Any]]``) already guarantees
    a list, so this path is unreachable from the HTTP surface.
    """
    if not isinstance(variants, list):
        raise ValueError("'variants' must be a list")
    if len(variants) < 2:
        # 0/1 variants are legacy/edge configs without allocation rules.
        return list(variants)

    structured: List[Dict[str, Any]] = []
    provided: List[float] = []
    for i, v in enumerate(variants):
        share = _variant_share(v)
        if share is None:
            # Free-form / legacy entry: pass through untouched.
            structured.append(v if isinstance(v, (dict, str)) else {"config": v})
            continue
        if not (0.0 - _VARIANT_SHARE_BOUNDS_TOL <= share <= 1.0 + _VARIANT_SHARE_BOUNDS_TOL):
            cur_label = _variant_label(v)
            raise AnalyticsConflictError(
                f"Variant #{i} ({cur_label or f'variant_{i + 1}'}) "
                f"traffic share {share} is outside [0, 1]"
            )
        entry = dict(v) if isinstance(v, dict) else {"config": v}
        entry["share"] = share  # canonical key
        structured.append(entry)
        provided.append(share)

    if not provided:
        # No allocation anywhere → legacy free-form, nothing to enforce.
        return structured
    provided_sum = sum(provided)
    if abs(provided_sum - 1.0) > _VARIANT_SHARE_TOL:
        raise AnalyticsConflictError(
            "Experiment variant traffic shares "
            f"{' + '.join(f'{s:.6f}' for s in provided)} "
            f"sum to {provided_sum:.6f}; all-or-nothing rule requires the "
            "provided shares to sum to exactly 1.0 (±0.000001)"
        )
    return structured


# ========== ExperimentService ==========

class ExperimentService:
    """CRUD + state machine for experiments, plus result recording."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: ExperimentCreate) -> Experiment:
        variants = _validate_variants(data.variants or [])
        exp = Experiment(
            code=data.code,
            name=data.name,
            description=data.description,
            hypothesis=data.hypothesis,
            primary_metric_code=data.primary_metric_code,
            secondary_metric_codes=data.secondary_metric_codes or [],
            variants=variants,
            status="draft",
            owner=data.owner,
            account_id=data.account_id,
        )
        self.db.add(exp)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise AnalyticsConflictError(
                f"Experiment code {data.code!r} already exists"
            ) from None
        await self.db.refresh(exp)
        logger.info("Created experiment %s (%s)", exp.id, exp.code)
        return exp

    async def get(self, experiment_id: UUID) -> Optional[Experiment]:
        return await _select_one(
            self.db, Experiment, [Experiment.id == experiment_id]
        )

    async def get_by_code(self, code: str) -> Optional[Experiment]:
        return await _select_one(
            self.db, Experiment, [Experiment.code == code]
        )

    async def list(self, status: Optional[str] = None,
                   page: int = 1, page_size: int = 20) -> Tuple[List[Experiment], int]:
        q = select(Experiment).where(Experiment.is_deleted == False)  # noqa: E712
        if status:
            q = q.where(Experiment.status == status)
        total = len((await self.db.execute(q)).scalars().all())
        page_q = (
            q.order_by(Experiment.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.db.execute(page_q)).scalars().all())
        return items, total

    async def update(self, exp: Experiment, data: ExperimentUpdate) -> Experiment:
        if data.name is not None:
            exp.name = data.name
        if data.description is not None:
            exp.description = data.description
        if data.hypothesis is not None:
            exp.hypothesis = data.hypothesis
        if data.primary_metric_code is not None:
            exp.primary_metric_code = data.primary_metric_code
        if data.secondary_metric_codes is not None:
            exp.secondary_metric_codes = data.secondary_metric_codes
        if data.variants is not None:
            exp.variants = _validate_variants(data.variants)
        if data.owner is not None:
            exp.owner = data.owner
        await self.db.commit()
        await self.db.refresh(exp)
        return exp

    async def set_status(self, exp: Experiment,
                         data: ExperimentStatusUpdate) -> Experiment:
        """Apply the experiment state machine (``EXPERIMENT_TRANSITIONS``)."""
        current = exp.status
        allowed = EXPERIMENT_TRANSITIONS.get(current, frozenset())
        if data.status not in allowed:
            raise ExperimentStatusError(
                current,
                data.status,
                f"Illegal experiment status transition {current!r} -> {data.status!r} "
                f"(allowed: {sorted(allowed) or 'none'})",
            )
        if data.status == "terminated" and not (data.reason or "").strip():
            raise ExperimentStatusError(
                current,
                data.status,
                "Terminating an experiment requires a reason.",
            )
        now = datetime.now(timezone.utc)
        exp.status = data.status
        if data.status == "running" and exp.started_at is None:
            exp.started_at = now
        if data.status in ("completed", "terminated"):
            exp.ended_at = now
        await self.db.commit()
        await self.db.refresh(exp)
        logger.info(
            "Experiment %s status %s -> %s", exp.id, current, data.status,
        )
        return exp

    async def delete(self, experiment_id: UUID) -> bool:
        exp = await self.get(experiment_id)
        if exp is None:
            return False
        exp.is_deleted = True
        await self.db.commit()
        logger.info("Soft-deleted experiment %s (%s)", experiment_id, exp.code)
        return True

    # ----- results -----

    async def add_result(self, data: ExperimentResultCreate) -> ExperimentResult:
        exp = await self.get(data.experiment_id)
        if exp is None:
            raise AnalyticsEntityNotFoundError("Experiment", data.experiment_id)
        # Results may only be recorded for live experiments.
        result = ExperimentResult(
            experiment_id=exp.id,
            variant_label=data.variant_label,
            metric_code=data.metric_code,
            sample_size=data.sample_size,
            metric_value=data.metric_value,
            baseline_value=data.baseline_value,
            lift_percent=data.lift_percent,
            p_value=data.p_value,
            is_significant=data.is_significant,
            stats=data.stats or {},
            computed_at=data.computed_at or datetime.now(timezone.utc),
        )
        self.db.add(result)
        await self.db.commit()
        await self.db.refresh(result)
        logger.info(
            "Recorded experiment result %s (experiment %s, variant %s, metric %s)",
            result.id, exp.id, result.variant_label, result.metric_code,
        )
        return result

    async def list_results(self, experiment_id: UUID,
                           variant_label: Optional[str] = None,
                           metric_code: Optional[str] = None,
                           page: int = 1, page_size: int = 20
                           ) -> Tuple[List[ExperimentResult], int]:
        q = select(ExperimentResult).where(
            ExperimentResult.experiment_id == experiment_id
        )
        if variant_label:
            q = q.where(ExperimentResult.variant_label == variant_label)
        if metric_code:
            q = q.where(ExperimentResult.metric_code == metric_code)
        total = len((await self.db.execute(q)).scalars().all())
        page_q = (
            q.order_by(ExperimentResult.computed_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.db.execute(page_q)).scalars().all())
        return items, total

    async def update_result(self, result: ExperimentResult,
                            data: ExperimentResultUpdate) -> ExperimentResult:
        if data.sample_size is not None:
            result.sample_size = data.sample_size
        if data.metric_value is not None:
            result.metric_value = data.metric_value
        if data.baseline_value is not None:
            result.baseline_value = data.baseline_value
        if data.lift_percent is not None:
            result.lift_percent = data.lift_percent
        if data.p_value is not None:
            result.p_value = data.p_value
        if data.is_significant is not None:
            result.is_significant = data.is_significant
        if data.stats is not None:
            result.stats = data.stats
        if data.computed_at is not None:
            result.computed_at = data.computed_at
        await self.db.commit()
        await self.db.refresh(result)
        return result

    async def get_result(self, result_id: UUID) -> Optional[ExperimentResult]:
        res = await self.db.execute(
            select(ExperimentResult).where(ExperimentResult.id == result_id)
        )
        return res.scalar_one_or_none()

    async def delete_result(self, result_id: UUID) -> bool:
        result = await self.get_result(result_id)
        if result is None:
            return False
        await self.db.delete(result)
        await self.db.commit()
        logger.info("Deleted experiment result %s", result_id)
        return True

    # ----- P6AN-08: results summary / variant comparison -----

    @staticmethod
    def _baseline_variant_label(exp: Experiment) -> Optional[str]:
        """Resolve the baseline variant label for lift computation.

        Rule (documented in ANALYTICS-API.md § P6AN-08): the first variant
        labelled ``control`` in the experiment's ``variants`` list; else the
        first variant's label; else ``None`` (no baseline → no lift).
        """
        variants = exp.variants or []
        labels: List[Optional[str]] = []
        for v in variants:
            lab = _variant_label(v)
            labels.append(lab)
        # first explicit 'control'
        for lab in labels:
            if lab is not None and lab.lower() == "control":
                return lab
        # else first labelled variant
        for lab in labels:
            if lab is not None:
                return lab
        return None

    @staticmethod
    def _significance_note(is_sig: Optional[bool], p_value: Optional[Decimal],
                           threshold: float, lift: Optional[Decimal],
                           variant_label: str) -> str:
        """Plain-language note; NO statistical inference library (out of scope)."""
        if p_value is None:
            return (f"Variant {variant_label!r}: no p-value recorded — "
                    "significance not evaluated this wave (basic comparison only).")
        verdict = "significant" if (is_sig or (is_sig is None and p_value < threshold)) else "not significant"
        detail = f"Variant {variant_label!r} {verdict} (p={p_value} vs threshold {threshold})"
        if lift is not None:
            detail += f"; lift vs baseline {lift.quantize(Decimal('0.0001')):+} percent"
        detail += "."
        return detail

    async def summarize_results(
        self, experiment_id: UUID, significance_threshold: float = 0.05
    ) -> ExperimentResultSummaryResponse:
        """P6AN-08: per-metric variant comparison for one experiment.

        Builds the *latest* result snapshot per (variant, metric), computes
        a derived lift against the resolved baseline variant, and writes a
        plain-language significance note. Basic comparison only — no
        statistical-inference library (explicitly out of scope for this
        card).
        """
        exp = await self.get(experiment_id)
        if exp is None:
            raise AnalyticsEntityNotFoundError("Experiment", experiment_id)

        all_rows, _ = await self._all_results_unpaged(experiment_id)

        # Latest snapshot per (variant, metric).
        latest: Dict[Tuple[str, str], ExperimentResult] = {}
        for r in all_rows:
            key = (r.variant_label, r.metric_code)
            cur = latest.get(key)
            if cur is None or (r.computed_at or _now()) >= (cur.computed_at or _now()):
                latest[key] = r

        # Order metrics: primary first, then secondary, then any others
        # (first-seen), all limited to metric codes actually present.
        present_codes = sorted({code for (_v, code) in latest})
        ordered: List[str] = []
        if exp.primary_metric_code in present_codes:
            ordered.append(exp.primary_metric_code)
        for code in (exp.secondary_metric_codes or []):
            if code in present_codes and code not in ordered:
                ordered.append(code)
        for code in present_codes:
            if code not in ordered:
                ordered.append(code)

        baseline = self._baseline_variant_label(exp)

        # Baseline variant's latest value per metric.
        baseline_by_metric: Dict[str, Optional[Decimal]] = {}
        for code in ordered:
            brow = latest.get((baseline, code)) if baseline else None
            baseline_by_metric[code] = brow.metric_value if brow else None

        threshold = float(significance_threshold)
        metrics_out: List[ExperimentResultSummaryMetric] = []
        for code in ordered:
            rows: List[ExperimentResultSummaryRow] = []
            notes: List[str] = []
            for vlabel, _v in latest:
                if _v != code:
                    continue
                row = latest[(vlabel, code)]
                base_val = baseline_by_metric[code] if baseline and vlabel != baseline else None
                lift: Optional[Decimal] = None
                if vlabel != baseline and base_val is not None and base_val != 0:
                    lift = (row.metric_value - base_val) / base_val * Decimal(100)
                significant: Optional[bool] = None
                if row.p_value is not None:
                    significant = bool(row.is_significant) if row.is_significant is not None \
                        else row.p_value < threshold
                rows.append(ExperimentResultSummaryRow(
                    variant_label=row.variant_label,
                    metric_value=str(row.metric_value),
                    sample_size=row.sample_size,
                    baseline_value=str(base_val) if base_val is not None else None,
                    computed_at=row.computed_at,
                    lift_vs_baseline_percent=str(lift) if lift is not None else None,
                    p_value=str(row.p_value) if row.p_value is not None else None,
                    is_significant=significant,
                ))
                if not (baseline and vlabel == baseline):
                    notes.append(self._significance_note(
                        significant, row.p_value, threshold, lift, row.variant_label))
            rows.sort(key=lambda r: (r.variant_label != baseline, r.variant_label.lower()))
            metrics_out.append(ExperimentResultSummaryMetric(
                metric_code=code,
                is_primary=(code == exp.primary_metric_code),
                baseline_variant=baseline,
                note=" ".join(notes) if notes else "",
                variants=rows,
            ))

        top_notes: List[str] = []
        if not ordered:
            top_notes.append("No result snapshots recorded yet for this experiment.")
        elif baseline is None:
            top_notes.append("No baseline variant resolvable (no labelled variants) — lifts not computed.")

        return ExperimentResultSummaryResponse(
            experiment_id=exp.id,
            code=exp.code,
            name=exp.name,
            status=exp.status,
            baseline_variant=baseline,
            significance_threshold=threshold,
            metrics=metrics_out,
            notes=top_notes,
        )

    async def _all_results_unpaged(self, experiment_id: UUID) -> Tuple[List[ExperimentResult], int]:
        """All live result rows for an experiment (no pagination) for aggregation."""
        q = select(ExperimentResult).where(ExperimentResult.experiment_id == experiment_id)
        rows = list((await self.db.execute(q)).scalars().all())
        return rows, len(rows)
