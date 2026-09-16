"""Analytics data models (Phase 6 / P6AN-01 — analytics foundation layer).

Five entities backing the analytics surface (dashboard, funnel, metrics,
experiments):

    DashboardWidget   -- a configurable widget on an analytics dashboard
    FunnelStep        -- an ordered step of a named acquisition funnel
    MetricDefinition  -- a registered metric (code + formula spec)
    Experiment        -- an A/B / strategy experiment lifecycle record
    ExperimentResult  -- an observed result snapshot of one experiment variant

Design notes
------------
- Conventions match the resource-layer modules (``channel_config``,
  ``workflow_runtime``): UUID PK, aware-UTC ``created_at``/``updated_at``
  (P2-1 precedent), ``is_deleted`` soft-delete, JSONB for evolving
  configuration, and partial (live-row) indexes via
  ``postgresql_where=is_deleted == False``.
- Cross-domain references stay **soft** (String codes, not FKs): a widget
  or metric may reference ``metric_definition.code`` / a funnel code /
  workflow or CRM concepts without hard-coupling the analytics module to
  them (same principle as ``channel_config.platform_code`` — the schema
  must not block registering analytics definitions before the referenced
  domain entity exists).
- The one *hard* FK besides ``account_id`` is
  ``experiment_result.experiment_id -> experiment.id`` (CASCADE): results
  are owned by their experiment and both tables are created atomically by
  the same migration, so the constraint is safe on fresh and legacy DBs.
- ``account_id`` (nullable, SET NULL) scopes an analytics definition to an
  Account when relevant; NULL means platform-wide.
- This module is the *definition* layer (schema + CRUD). Computation of
  metric values from source data is a later Phase-6 wave (out of scope
  for P6AN-01: no SQL free-report engine, no realtime data pipeline).
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import relationship
from uuid import uuid4

from .base import Base


# ===== Allowed value sets (validation + docs) =====
WIDGET_TYPES = ("kpi", "chart", "table", "funnel", "trend")
METRIC_CATEGORIES = (
    "acquisition",
    "conversion",
    "retention",
    "revenue",
    "agent_performance",
    "roi",
    "custom",
)
METRIC_VALUE_TYPES = ("numeric", "integer", "ratio", "percentage")
METRIC_AGGREGATIONS = ("sum", "avg", "min", "max", "unique_count", "count", "ratio")
EXPERIMENT_STATUSES = ("draft", "running", "paused", "completed", "terminated")

# Legal experiment status transitions (enforced by the service layer).
EXPERIMENT_TRANSITIONS = {
    "draft": frozenset({"running", "terminated"}),
    "running": frozenset({"paused", "completed", "terminated"}),
    "paused": frozenset({"running", "terminated"}),
    "completed": frozenset(),
    "terminated": frozenset(),
}
EXPERIMENT_TERMINAL_STATUSES = ("completed", "terminated")


def _now() -> datetime:
    # P2-1 precedent (workflow_runtime): aware-UTC default so the module
    # stays consistent with the rest of the app's timezone-aware columns.
    return datetime.now(timezone.utc)


class DashboardWidget(Base):
    """A configurable widget on an analytics dashboard (table: ``dashboard_widget``)."""

    __tablename__ = "dashboard_widget"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    widget_type = Column(Text, nullable=False, default="kpi")  # WIDGET_TYPES
    # Layout / chart options (chart kind, axis mapping, filters...). Evolves
    # as JSONB without schema churn.
    config = Column(JSONB, nullable=False, default=dict)
    # Soft references to registered analytics definitions (no FK on purpose).
    metric_code = Column(Text, nullable=True, index=True)
    funnel_code = Column(Text, nullable=True, index=True)
    refresh_interval_seconds = Column(Integer, nullable=False, default=300)
    position = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    account_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("account.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    account = relationship("Account")  # unidirectional, no backref

    __table_args__ = (
        Index(
            "idx_widget_type",
            "widget_type",
            postgresql_where=is_deleted == False,  # noqa: E712
        ),
    )

    def __repr__(self) -> str:
        return f"<DashboardWidget(id={self.id}, name={self.name!r}, type={self.widget_type})>"


class FunnelStep(Base):
    """An ordered step of a named funnel (table: ``funnel_step``).

    Steps of the same ``funnel_code`` are ordered by ``seq`` (1-based,
    unique per funnel among live rows — enforced by the partial unique
    index). ``entry_criteria`` / ``conversion_criteria`` are JSONB specs a
    later analytics-compute wave evaluates; this card ships the
    definitions only.
    """

    __tablename__ = "funnel_step"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    funnel_code = Column(Text, nullable=False, index=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    seq = Column(Integer, nullable=False)  # 1-based order within the funnel
    entry_criteria = Column(JSONB, nullable=False, default=dict)
    conversion_criteria = Column(JSONB, nullable=True)
    config = Column(JSONB, nullable=False, default=dict)
    account_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("account.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    account = relationship("Account")  # unidirectional, no backref

    __table_args__ = (
        Index(
            "uq_funnel_step_code_seq",
            "funnel_code",
            "seq",
            unique=True,
            postgresql_where=is_deleted == False,  # noqa: E712
        ),
    )

    def __repr__(self) -> str:
        return f"<FunnelStep(id={self.id}, funnel={self.funnel_code!r}, seq={self.seq})>"


class MetricDefinition(Base):
    """A registered metric definition (table: ``metric_definition``).

    ``code`` is the stable identifier other analytics objects reference
    (widgets, experiments). ``formula`` is a JSONB spec
    (source + aggregation + filters) that the later analytics-compute
    wave evaluates; ``value_type`` / ``unit`` document how results render.
    """

    __tablename__ = "metric_definition"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    code = Column(Text, nullable=False, index=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(Text, nullable=False, default="custom")  # METRIC_CATEGORIES
    value_type = Column(Text, nullable=False, default="numeric")  # METRIC_VALUE_TYPES
    unit = Column(Text, nullable=True)
    aggregation = Column(Text, nullable=True)  # METRIC_AGGREGATIONS (nullable = custom formula)
    # JSONB metric spec: e.g. {"source": "conversation", "agg": "count",
    # "filters": {...}, "window_days": 30}. No SQL in this column — a free
    # report engine is out of scope for P6AN-01.
    formula = Column(JSONB, nullable=False, default=dict)
    source = Column(Text, nullable=True)  # conceptual source domain (conversation, execution_log, ...)
    window_days = Column(Integer, nullable=False, default=30)
    enabled = Column(Boolean, nullable=False, default=True)
    account_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("account.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    account = relationship("Account")  # unidirectional, no backref

    __table_args__ = (
        Index(
            "uq_metric_definition_code",
            "code",
            unique=True,
            postgresql_where=is_deleted == False,  # noqa: E712
        ),
        Index(
            "idx_metric_category",
            "category",
            postgresql_where=is_deleted == False,  # noqa: E712
        ),
    )

    def __repr__(self) -> str:
        return f"<MetricDefinition(id={self.id}, code={self.code!r}, category={self.category})>"


class Experiment(Base):
    """An A/B / strategy experiment (table: ``experiment``).

    ``status`` walks the ``EXPERIMENT_TRANSITIONS`` graph
    (draft -> running -> [paused] -> completed/terminated); the service
    layer enforces the graph, the DB does not (VARCHAR + service rule,
    matching ``workflow_task`` where state legality lives in the engine).
    ``variants`` is a JSONB list of variant configs
    (label / traffic share / config) so adding experiment types does not
    require schema churn.

    P6AN-08 structured traffic-allocation rule (enforced in
    ``analytics_service._validate_variants``; see
    ``docs/ANALYTICS-API.md`` § P6AN-08):

    - canonical shape: ``[{"label": str, "share": 0..1, "config": dict}]``
      (share aliases: ``traffic`` / ``traffic_share``; a string numeric
      share is coerced).
    - ``share`` is optional. As soon as ANY variant carries a share, the
      sum of the provided shares must equal 1.0 (±1e-6) — a partial
      allocation is a 409.
    - Label-less / free-form legacy entries (plain strings, dicts without
      a recognized share key, label-less dicts) pass through untouched,
      so experiments created under P6AN-01's free-form contract keep
      working; structured entries are normalized on write.
    """

    __tablename__ = "experiment"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    code = Column(Text, nullable=False, index=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    hypothesis = Column(Text, nullable=True)
    # Soft references to registered metrics (no FK on purpose).
    primary_metric_code = Column(Text, nullable=True, index=True)
    secondary_metric_codes = Column(JSONB, nullable=False, default=list)
    variants = Column(JSONB, nullable=False, default=list)
    status = Column(Text, nullable=False, default="draft")  # EXPERIMENT_STATUSES
    owner = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    account_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("account.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    account = relationship("Account")  # unidirectional, no backref
    # No forward `results` relationship: the single unidirectional
    # ExperimentResult.experiment (matching the workflow_runtime precedent)
    # avoids the ORM's overlaps warning on the same FK.

    __table_args__ = (
        Index(
            "uq_experiment_code",
            "code",
            unique=True,
            postgresql_where=is_deleted == False,  # noqa: E712
        ),
        Index(
            "idx_experiment_status",
            "status",
            postgresql_where=is_deleted == False,  # noqa: E712
        ),
    )

    def __repr__(self) -> str:
        return f"<Experiment(id={self.id}, code={self.code!r}, status={self.status})>"


class ExperimentResult(Base):
    """One observed result snapshot for an experiment variant + metric
    (table: ``experiment_result``).

    Multiple snapshots per (experiment, variant, metric) are allowed —
    results are computed on demand and appended over time; consumers read
    the latest (or aggregate). Owned by the experiment: CASCADE on
    ``experiment_id`` (both tables are created atomically by migration 028,
    so the hard FK is safe on fresh and legacy DBs alike).
    """

    __tablename__ = "experiment_result"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    experiment_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("experiment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant_label = Column(Text, nullable=False)
    metric_code = Column(Text, nullable=False, index=True)
    sample_size = Column(Integer, nullable=False, default=0)
    metric_value = Column(Numeric(18, 6), nullable=False)
    baseline_value = Column(Numeric(18, 6), nullable=True)
    lift_percent = Column(Numeric(8, 4), nullable=True)
    p_value = Column(Numeric(8, 6), nullable=True)
    is_significant = Column(Boolean, nullable=True)
    # Raw stats dump (test used, alpha, CI...) — JSONB, not schema.
    stats = Column(JSONB, nullable=False, default=dict)
    computed_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    experiment = relationship("Experiment")  # unidirectional, no backref

    def __repr__(self) -> str:
        return (
            f"<ExperimentResult(id={self.id}, experiment={self.experiment_id}, "
            f"variant={self.variant_label!r}, metric={self.metric_code!r})>"
        )
