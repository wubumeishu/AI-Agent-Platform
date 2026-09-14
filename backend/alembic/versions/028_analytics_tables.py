"""Analytics foundation tables (Phase 6 / P6AN-01).

Revision ID: 028_analytics_tables
Revises: 027_seed_scheduler_queue
Create Date: 2026-09-15

Creates the five Phase-6 analytics definition tables:

    dashboard_widget    -- configurable widgets on analytics dashboards
    funnel_step         -- ordered steps of named acquisition funnels
    metric_definition   -- registered metrics (stable ``code`` + JSONB spec)
    experiment          -- A/B / strategy experiment lifecycle
    experiment_result   -- observed result snapshots per experiment variant

Design notes
------------
* Conventions mirror the resource-layer modules (024 ``channel_config``,
  020 ``workflow_runtime``): UUID PK, aware-UTC ``created_at``/``updated_at``,
  ``is_deleted`` soft-delete, JSONB for evolving configuration, partial
  (live-row) unique indexes via ``postgresql_where='is_deleted = false'``.
* Cross-domain references are soft (TEXT codes): widgets may reference
  metric / funnel codes and experiments may reference metric codes without
  hard-coupling the analytics module to the referenced domains (same
  principle as ``channel_config.platform_code`` — the schema must not block
  registering analytics definitions before the referenced entity exists).
* The one hard FK besides ``account_id`` is
  ``experiment_result.experiment_id -> experiment.id`` (CASCADE): both
  tables are created atomically by this revision, so the constraint is
  safe on fresh DBs and on the legacy stamped production DB alike.
* ``account_id`` (FK -> account.id, SET NULL, nullable) scopes a definition
  to an Account; NULL = platform-wide. ``account`` has existed since 002
  (fresh) / 026 (legacy), so the FK is valid on both paths.
* Idempotent and re-runnable: every ``CREATE`` / guard checks current
  database state through the *live* migration bind (``to_regclass`` /
  ``pg_indexes``) rather than a cached inspector — a cached
  ``inspect(bind)`` captured before ``create_table`` is stale within the
  transaction and would silently skip index creation on a fresh DB.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "028_analytics_tables"
down_revision: Union[str, None] = "027_seed_scheduler_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table: str) -> bool:
    """Live check (transaction-aware): is the table present right now?"""
    val = bind.execute(
        sa.text("SELECT to_regclass('public.' || :t) IS NOT NULL"),
        {"t": table},
    ).scalar()
    return bool(val)


def _index_names(bind, table: str) -> set:
    """Live set of index names currently on *table*."""
    rows = bind.execute(
        sa.text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = :t"
        ),
        {"t": table},
    ).fetchall()
    return {r[0] for r in rows}


def _create_indexes_if_absent(bind, table: str, indexes: list) -> None:
    """Create each named index only if it does not already exist.

    ``indexes`` is a list of (name, [cols], unique, where_or_None).
    """
    existing = _index_names(bind, table)
    for name, cols, unique, where in indexes:
        if name in existing:
            continue
        op.create_index(
            name, table, cols,
            unique=unique,
            postgresql_where=where,
        )


def upgrade() -> None:
    bind = op.get_bind()

    # ===== dashboard_widget =====
    if not _table_exists(bind, "dashboard_widget"):
        op.create_table(
            "dashboard_widget",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("widget_type", sa.Text(), nullable=False,
                      server_default="kpi"),
            sa.Column("config", JSONB(), nullable=False,
                      server_default="{}"),
            sa.Column("metric_code", sa.Text(), nullable=True),
            sa.Column("funnel_code", sa.Text(), nullable=True),
            sa.Column("refresh_interval_seconds", sa.Integer(), nullable=False,
                      server_default="300"),
            sa.Column("position", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("enabled", sa.Boolean(), nullable=False,
                      server_default="true"),
            sa.Column("account_id", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False,
                      server_default="false"),
            sa.ForeignKeyConstraint(["account_id"], ["account.id"],
                                   ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_indexes_if_absent(bind, "dashboard_widget", [
        ("ix_dashboard_widget_metric_code", ["metric_code"], False, None),
        ("ix_dashboard_widget_funnel_code", ["funnel_code"], False, None),
        ("idx_widget_account", ["account_id"], False, None),
        ("idx_widget_type", ["widget_type"], False, "is_deleted = false"),
    ])

    # ===== funnel_step =====
    if not _table_exists(bind, "funnel_step"):
        op.create_table(
            "funnel_step",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("funnel_code", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("entry_criteria", JSONB(), nullable=False,
                      server_default="{}"),
            sa.Column("conversion_criteria", JSONB(), nullable=True),
            sa.Column("config", JSONB(), nullable=False,
                      server_default="{}"),
            sa.Column("account_id", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False,
                      server_default="false"),
            sa.ForeignKeyConstraint(["account_id"], ["account.id"],
                                   ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    # (funnel_code, seq) unique among live rows: a funnel is a platform-level
    # definition at V1 scope (account-independent).
    _create_indexes_if_absent(bind, "funnel_step", [
        ("ix_funnel_step_funnel_code", ["funnel_code"], False, None),
        ("idx_funnel_step_account", ["account_id"], False, None),
        ("uq_funnel_step_code_seq", ["funnel_code", "seq"], True,
         "is_deleted = false"),
    ])

    # ===== metric_definition =====
    if not _table_exists(bind, "metric_definition"):
        op.create_table(
            "metric_definition",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.Text(), nullable=False,
                      server_default="custom"),
            sa.Column("value_type", sa.Text(), nullable=False,
                      server_default="numeric"),
            sa.Column("unit", sa.Text(), nullable=True),
            sa.Column("aggregation", sa.Text(), nullable=True),
            sa.Column("formula", JSONB(), nullable=False,
                      server_default="{}"),
            sa.Column("source", sa.Text(), nullable=True),
            sa.Column("window_days", sa.Integer(), nullable=False,
                      server_default="30"),
            sa.Column("enabled", sa.Boolean(), nullable=False,
                      server_default="true"),
            sa.Column("account_id", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False,
                      server_default="false"),
            sa.ForeignKeyConstraint(["account_id"], ["account.id"],
                                   ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_indexes_if_absent(bind, "metric_definition", [
        ("ix_metric_definition_code", ["code"], False, None),
        ("idx_metric_account", ["account_id"], False, None),
        ("uq_metric_definition_code", ["code"], True, "is_deleted = false"),
        ("idx_metric_category", ["category"], False, "is_deleted = false"),
    ])

    # ===== experiment =====
    if not _table_exists(bind, "experiment"):
        op.create_table(
            "experiment",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("hypothesis", sa.Text(), nullable=True),
            sa.Column("primary_metric_code", sa.Text(), nullable=True),
            sa.Column("secondary_metric_codes", JSONB(), nullable=False,
                      server_default="[]"),
            sa.Column("variants", JSONB(), nullable=False,
                      server_default="[]"),
            sa.Column("status", sa.Text(), nullable=False,
                      server_default="draft"),
            sa.Column("owner", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("account_id", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False,
                      server_default="false"),
            sa.ForeignKeyConstraint(["account_id"], ["account.id"],
                                   ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_indexes_if_absent(bind, "experiment", [
        ("ix_experiment_code", ["code"], False, None),
        ("ix_experiment_primary_metric_code", ["primary_metric_code"],
         False, None),
        ("idx_experiment_account", ["account_id"], False, None),
        ("uq_experiment_code", ["code"], True, "is_deleted = false"),
        ("idx_experiment_status", ["status"], False, "is_deleted = false"),
    ])

    # ===== experiment_result =====
    if not _table_exists(bind, "experiment_result"):
        op.create_table(
            "experiment_result",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("experiment_id", sa.Uuid(), nullable=False),
            sa.Column("variant_label", sa.Text(), nullable=False),
            sa.Column("metric_code", sa.Text(), nullable=False),
            sa.Column("sample_size", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("metric_value", sa.Numeric(18, 6), nullable=False),
            sa.Column("baseline_value", sa.Numeric(18, 6), nullable=True),
            sa.Column("lift_percent", sa.Numeric(8, 4), nullable=True),
            sa.Column("p_value", sa.Numeric(8, 6), nullable=True),
            sa.Column("is_significant", sa.Boolean(), nullable=True),
            sa.Column("stats", JSONB(), nullable=False,
                      server_default="{}"),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"],
                                   ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_indexes_if_absent(bind, "experiment_result", [
        ("ix_experiment_result_experiment_id", ["experiment_id"], False, None),
        ("ix_experiment_result_metric_code", ["metric_code"], False, None),
        ("idx_experiment_result_computed_at", ["computed_at"], False, None),
    ])


def downgrade() -> None:
    bind = op.get_bind()

    # Drop in reverse dependency order (results first, then their FK targets).
    if _table_exists(bind, "experiment_result"):
        _drop_indexes_if_present(bind, "experiment_result", [
            "ix_experiment_result_metric_code",
            "ix_experiment_result_experiment_id",
            "idx_experiment_result_computed_at",
        ])
        op.drop_table("experiment_result")

    if _table_exists(bind, "experiment"):
        _drop_indexes_if_present(bind, "experiment", [
            "idx_experiment_status",
            "uq_experiment_code",
            "idx_experiment_account",
            "ix_experiment_primary_metric_code",
            "ix_experiment_code",
        ])
        op.drop_table("experiment")

    if _table_exists(bind, "metric_definition"):
        _drop_indexes_if_present(bind, "metric_definition", [
            "idx_metric_category",
            "uq_metric_definition_code",
            "idx_metric_account",
            "ix_metric_definition_code",
        ])
        op.drop_table("metric_definition")

    if _table_exists(bind, "funnel_step"):
        _drop_indexes_if_present(bind, "funnel_step", [
            "uq_funnel_step_code_seq",
            "idx_funnel_step_account",
            "ix_funnel_step_funnel_code",
        ])
        op.drop_table("funnel_step")

    if _table_exists(bind, "dashboard_widget"):
        _drop_indexes_if_present(bind, "dashboard_widget", [
            "idx_widget_type",
            "idx_widget_account",
            "ix_dashboard_widget_funnel_code",
            "ix_dashboard_widget_metric_code",
        ])
        op.drop_table("dashboard_widget")


def _drop_indexes_if_present(bind, table: str, names: list) -> None:
    existing = _index_names(bind, table)
    for name in names:
        if name in existing:
            op.drop_index(name, table_name=table)
