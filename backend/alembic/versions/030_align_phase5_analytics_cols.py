"""Align legacy prod fork to current ORM for Phase-5 PII / analytics columns.

Revision ID: 030_align_phase5_analytics_cols
Revises: 029_p0_security_data_protection
Create Date: 2026-09-15

Context (P6AN-17 P2-5 / prod DB drift)
--------------------------------------
The production ``ai_agent_platform`` database is a legacy ``create_all``
fork: its ``deal_item`` / ``follow_up_task`` tables predate the Phase-5
resource-layer column set and are stamped at an older alembic head. The
Phase-6 analytics read path (``roi_analysis``, ``private_domain_conversion``)
selects the Phase-5 columns below, so on this legacy schema those queries
raise ``UndefinedColumn`` and the analytics endpoints 500.

This revision adds only the *missing* Phase-5 / P6AN columns to the two
affected tables, so the ORM and the analytics services work unchanged on
the legacy DB. It is a no-op on a fresh ORM-created database (every column
already exists) and is fully idempotent / re-runnable on the legacy fork.

Columns added (all are declared in ``app/db/models/private_domain.py``)::

    deal_item:       account_id, lead_id, status, currency,
                    winner_reason, loser_reason
    follow_up_task:  account_id, lead_id, task_type, scheduled_at,
                    reminder_config, result, notes, created_by

Idempotency
-----------
Each column is added only if ``information_schema.columns`` does not already
list it (live, transaction-aware check) — never a cached inspector. ``ADD
COLUMN`` is a no-op-safe guarded DDL, so the revision can be re-run on a
stamped/legacy DB without error or silent skips. FK targets
(``account.id`` / ``lead.id``) exist as UUID on both the fresh and legacy
schemas, so the column types are safe on both paths. ``account_id`` is
NOT NULL to match the ORM; both tables carry 0 rows on the prod fork, so
a NOT NULL add without a client default is valid (a server_default is
omitted because the column is a UUID reference with no meaningful global
default).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "030_align_phase5_analytics_cols"
down_revision = "029_p0_security_data_protection"
branch_labels = None
depends_on = None


def _col_exists(bind, table: str, column: str) -> bool:
    """Live (transaction-aware) check: does (table, column) exist right now?"""
    val = bind.execute(
        sa.text(
            "SELECT EXISTS("
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t "
            "AND column_name = :c)"
        ),
        {"t": table, "c": column},
    ).scalar()
    return bool(val)


def _add_col_if_absent(bind, table: str, column: str, colspec) -> None:
    """Add one column only if absent. ``colspec`` is an ``sa.Column``."""
    if _col_exists(bind, table, column):
        return
    op.add_column(table, colspec)


def upgrade() -> None:
    bind = op.get_bind()

    # ===== deal_item (6 columns) =====
    _add_col_if_absent(bind, "deal_item", "account_id",
        sa.Column("account_id", sa.Uuid(), nullable=False))
    _add_col_if_absent(bind, "deal_item", "lead_id",
        sa.Column("lead_id", sa.Uuid(), nullable=True))
    _add_col_if_absent(bind, "deal_item", "status",
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="open"))
    _add_col_if_absent(bind, "deal_item", "currency",
        sa.Column("currency", sa.String(length=3), nullable=False,
                  server_default="CNY"))
    _add_col_if_absent(bind, "deal_item", "winner_reason",
        sa.Column("winner_reason", sa.String(length=200), nullable=True))
    _add_col_if_absent(bind, "deal_item", "loser_reason",
        sa.Column("loser_reason", sa.String(length=200), nullable=True))

    # ===== follow_up_task (8 columns) =====
    _add_col_if_absent(bind, "follow_up_task", "account_id",
        sa.Column("account_id", sa.Uuid(), nullable=False))
    _add_col_if_absent(bind, "follow_up_task", "lead_id",
        sa.Column("lead_id", sa.Uuid(), nullable=True))
    _add_col_if_absent(bind, "follow_up_task", "task_type",
        sa.Column("task_type", sa.String(length=50), nullable=True))
    _add_col_if_absent(bind, "follow_up_task", "scheduled_at",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    _add_col_if_absent(bind, "follow_up_task", "reminder_config",
        sa.Column("reminder_config", JSONB(), nullable=True))
    _add_col_if_absent(bind, "follow_up_task", "result",
        sa.Column("result", JSONB(), nullable=True))
    _add_col_if_absent(bind, "follow_up_task", "notes",
        sa.Column("notes", sa.Text(), nullable=True))
    _add_col_if_absent(bind, "follow_up_task", "created_by",
        sa.Column("created_by", sa.String(length=100), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()

    for table, column in [
        ("follow_up_task", "created_by"),
        ("follow_up_task", "notes"),
        ("follow_up_task", "result"),
        ("follow_up_task", "reminder_config"),
        ("follow_up_task", "scheduled_at"),
        ("follow_up_task", "task_type"),
        ("follow_up_task", "lead_id"),
        ("follow_up_task", "account_id"),
        ("deal_item", "loser_reason"),
        ("deal_item", "winner_reason"),
        ("deal_item", "currency"),
        ("deal_item", "status"),
        ("deal_item", "lead_id"),
        ("deal_item", "account_id"),
    ]:
        if _col_exists(bind, table, column):
            op.drop_column(table, column)
