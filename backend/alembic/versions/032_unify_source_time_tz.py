"""Unify Phase 1-5 source-table time columns to aware-UTC timestamptz.

Revision ID: 032_unify_source_time_tz
Revises: 031_align_deal_item_customer_id_uuid
Create Date: 2026-09-15

P6AN-17 P2-3 (from P6AN-16 arch review §4.2): the Phase 1-5 *source* tables
carry a naive/tz split that is the root of a recurring bug class in Analytics.

    naive `timestamp` family : lead, customer, customer_identity,
                                lifecycle_stage, lifecycle_stage_log, tag
    `timestamptz` family     : conversation, message, agent, deal_item,
                                follow_up_task, nurture_step_execution, ...

Every analytics service had to per-table `_naive_utc`-strip aware-UTC window
bounds before binding them to the naive columns. P6AN-02's live 对撞 caught
three real bugs from this naive/timestamptz mixing. This revision unifies the
naive columns to aware-UTC `timestamptz` so the whole schema speaks one
timezone and the per-service stripping is no longer required.

Session-timezone hazard (the load-bearing detail)
-------------------------------------------------
The PostgreSQL server / role ``TimeZone`` here is **Asia/Tokyo (JST)**, not
UTC. Consequences, both probe-verified against the live server:

* A naive `timestamp` value re-typed with a bare
  ``CAST(col AS timestamptz)`` (or ``ALTER ... TYPE timestamptz`` with no
  USING) is re-interpreted in the *session* tz. On this JST server that reads
  the naive UTC wall-clock ``2026-09-01 12:00`` as JST and stores the instant
  ``2026-08-31 15:00 UTC`` — a silent −9h drift.
* The correct, session-tz-independent re-type is
  ``USING (col AT TIME ZONE 'UTC')``: it treats the stored naive value as a
  UTC wall-clock and produces the exact same absolute instant
  (``2026-09-01 12:00 UTC``). Probe-verified to round-trip losslessly.

This revision is **idempotent and re-runnable**: each ALTER only fires while
the column is still a naive ``timestamp without time zone``; once it is
``timestamp with time zone`` the ALTER is skipped. So it is safe to run on a
fresh DB (already at head) and on the legacy stamped production DB alike.

Scope
-----
Only the six naive *source* tables above are touched. The already-aware
tables (conversation / message / agent / deal_item / ...) are untouched. The
ORM defaults and the service write/read paths are aligned to aware-UTC in the
same card (P6AN-17 P2-3); the ``_naive_utc`` helpers in the analytics
services become unnecessary and are removed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "032_unify_source_time_tz"
down_revision: Union[str, None] = "031_align_deal_item_customer_id_uuid"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column) pairs that are currently naive `timestamp without time zone`
# and must be unified to aware-UTC `timestamptz`.
_MIGRATED_COLUMNS: Sequence[tuple[str, str]] = (
    ("lead", "created_at"),
    ("lead", "updated_at"),
    ("customer", "created_at"),
    ("customer", "updated_at"),
    ("customer_identity", "created_at"),
    ("customer_identity", "updated_at"),
    ("lifecycle_stage", "created_at"),
    ("lifecycle_stage", "updated_at"),
    ("lifecycle_stage_log", "created_at"),
    ("tag", "created_at"),
)


def _column_data_type(bind, table: str, column: str) -> str | None:
    """Live, transaction-aware read of a column's ``data_type`` (or None)."""
    return bind.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t "
            "AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()


def _table_exists(bind, table: str) -> bool:
    return bool(
        bind.execute(
            sa.text("SELECT to_regclass('public.' || :t) IS NOT NULL"),
            {"t": table},
        ).scalar()
    )


def upgrade() -> None:
    """Re-type every naive source column to aware-UTC ``timestamptz``.

    Each ALTER is guarded to fire only while the column is still a naive
    ``timestamp without time zone``; a column already ``timestamptz`` is a
    no-op, so the migration is safe to re-run.
    """
    bind = op.get_bind()
    for table, column in _MIGRATED_COLUMNS:
        if not _table_exists(bind, table):
            # Table not present on this DB shape (e.g. a partial legacy fork);
            # skip rather than fail the whole migration.
            op.execute(sa.text(
                f"SELECT 'skip {table}.{column} (table absent)'"
            ))
            continue
        current = _column_data_type(bind, table, column)
        if current == "timestamp with time zone":
            # Already unified — idempotent no-op.
            continue
        # current is 'timestamp without time zone' (or unexpected): re-type,
        # re-interpreting the stored naive UTC wall-clock as an absolute
        # instant via AT TIME ZONE 'UTC' (session-tz independent).
        op.execute(sa.text(
            f"ALTER TABLE public.{table} ALTER COLUMN {column} "
            f"TYPE timestamp with time zone "
            f"USING ({column} AT TIME ZONE 'UTC')"
        ))


def downgrade() -> None:
    """Convert the unified columns back to naive UTC ``timestamp``.

    ``AT TIME ZONE 'UTC'`` on a ``timestamptz`` yields the UTC wall-clock,
    so the re-interpreted value is lossless with respect to the original
    naive data. Guarded to fire only while the column is still ``timestamptz``
    (idempotent on re-run).
    """
    bind = op.get_bind()
    for table, column in _MIGRATED_COLUMNS:
        if not _table_exists(bind, table):
            continue
        current = _column_data_type(bind, table, column)
        if current != "timestamp with time zone":
            continue
        op.execute(sa.text(
            f"ALTER TABLE public.{table} ALTER COLUMN {column} "
            f"TYPE timestamp without time zone "
            f"USING ({column} AT TIME ZONE 'UTC')"
        ))
