"""P5MSG-02 — receipt/delivery columns for the messages table (P5MSG-01 scaffold).

Revision ID: 023_messages_receipt
Revises: 022_lead_conversation_dedup_index, 022_messages_channel
Create Date: 2026-09-14

This revision has TWO down-revisions: P5MSG-01 shipped the ``messages`` table
as ``022_messages_channel`` while the CRM pool shipped ``022_lead_conversation_dedup_index``
in parallel. Both chain off ``021_phase1_persona_trigger``; Alembic therefore
holds two heads. Following the precedent of ``019_linearize_heads``, this
revision merges them (the upgrade path applies nothing from either head —
both DDLs were shipped by their own migrations; this is a linearization +
delivery-receipt column addition).

Adds to the ``messages`` table (see P5MSG-02 card, "已读回执与投递状态机"):

  * ``receipts``  JSONB — append-only audit trail of delivery/read receipts,
                   each entry ``{status, at, source}`` where ``source`` is
                   ``"provider"`` (channel adapter, P5MSG-03) or
                   ``"manual"`` (API override).
  * ``last_receipt_at`` timestamptz — fast "when was it last acknowledged"
                   for the receipt read endpoint.

Both nullable with safe server defaults so legacy rows (status already
queued/sent/...) keep working. Downgrade drops the two columns.

Idempotency: columns are added with ``IF NOT EXISTS`` semantics via a
pre-check (same style as 020) so re-running on an already-migrated DB is a
no-op; downgrade drops unconditionally (standard).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "023_messages_receipt"
down_revision = ("022_lead_conversation_dedup_index", "022_messages_channel")
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("messages")}

    if "receipts" not in cols:
        op.add_column(
            "messages",
            sa.Column(
                "receipts",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )
    if "last_receipt_at" not in cols:
        op.add_column(
            "messages",
            sa.Column(
                "last_receipt_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
    op.create_index(
        "idx_messages_last_receipt_at", "messages", ["last_receipt_at"],
        unique=False, if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_messages_last_receipt_at", table_name="messages")
    op.drop_column("messages", "last_receipt_at")
    op.drop_column("messages", "receipts")
