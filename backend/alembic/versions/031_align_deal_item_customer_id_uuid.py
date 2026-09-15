"""Align legacy prod fork: re-type deal_item.customer_id to UUID.

Revision ID: 031_align_deal_item_customer_id_uuid
Revises: 030_align_phase5_analytics_cols
Create Date: 2026-09-15

Context (P6AN-17 P2-5 / prod DB drift, follow-on to 030)
--------------------------------------------------------
The production ``ai_agent_platform`` database is a legacy ``create_all`` fork
whose ``deal_item`` table still carries a ``customer_id`` typed
``character varying(36)`` (the fork predates the UUID reference columns).
The canonical ORM (``app.db.models.private_domain.DealItem``) declares
``customer_id`` as a UUID, and the Phase-6 analytics read path joins
``deal_item.customer_id`` to ``agent_customer_binding.customer_id``
(a UUID) — e.g. ``roi_analysis.ROIService.get_roi("agent")`` and the
agent-scoped branches of ``private_domain_conversion``. On the legacy fork
that join raises::

    operator does not exist: character varying = uuid

which is the last remaining 500 on a P6AN analytics endpoint once the
Phase-5 columns from 030 are in place.

This revision re-types ``deal_item.customer_id`` to UUID so the P6AN
analytics read path works on the legacy DB. It is a **no-op on a fresh
ORM-created database** (the column is already UUID there) and is
**idempotent / re-runnable** on the legacy fork (the re-type fires only
while the column is still a non-UUID type). ``deal_item`` carries 0 rows on
the prod fork, so the re-type touches no data.

Only ``customer_id`` is re-typed here — it is the single P6AN join column
with a type conflict. The remaining VARCHAR reference columns
(``deal_item.pipeline_id`` / ``stage_id`` / ``owner_id`` and the
``follow_up_task`` refs) are NOT joined by any P6AN analytics service and
are left for a broader legacy-fork full-alignment effort (out of scope for
P2-5, which targets the Phase-5 / analytics column set).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "031_align_deal_item_customer_id_uuid"
down_revision = "030_align_phase5_analytics_cols"
branch_labels = None
depends_on = None


def _col_data_type(bind, table: str, column: str) -> str | None:
    """Live (transaction-aware) read of a column's ``data_type`` (or None)."""
    return bind.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t "
            "AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()


def _retype_to_uuid_if_needed(bind, table: str, column: str) -> bool:
    """Re-type ``table.column`` to UUID if it is not already UUID.

    Returns True when a re-type actually happened. On a fresh ORM DB the
    column is already ``uuid`` so this is a no-op; on the legacy fork it is
    ``character varying`` and the guarded re-type applies.
    """
    dtype = _col_data_type(bind, table, column)
    if dtype is None:
        # Column absent (e.g. a fork that lacks it entirely): nothing to do.
        return False
    if dtype.lower() == "uuid":
        return False
    # Non-UUID (VARCHAR on the legacy fork): a direct ``::uuid`` cast is
    # safe — the table is empty on prod, and any existing UUID-shaped text
    # casts cleanly. (On a populated legacy fork this would be a data
    # migration; P2-5 scope assumes the empty/legacy case.)
    op.execute(
        sa.text(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE {UUID.__name__} USING {column}::uuid"
        )
    )
    return True


def upgrade() -> None:
    bind = op.get_bind()
    # Only the P6AN-joined reference column is re-typed (see module note).
    _retype_to_uuid_if_needed(bind, "deal_item", "customer_id")


def downgrade() -> None:
    # Restore the legacy VARCHAR width on the fork (no data loss on the
    # empty prod table; fresh DBs have no data either).
    bind = op.get_bind()
    if _col_data_type(bind, "deal_item", "customer_id") == "uuid":
        op.execute(
            sa.text(
                "ALTER TABLE deal_item ALTER COLUMN customer_id "
                "TYPE varchar(36) USING customer_id::text"
            )
        )
