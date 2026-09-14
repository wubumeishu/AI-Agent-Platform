"""Channel Message / dispatch-record schema (P5MSG-01).

Revision ID: 022_messages_channel
Revises: 021_phase1_persona_trigger
Create Date: 2026-09-14

Introduces the ``messages`` table — the *channel message dispatch / delivery
record* for the Roadmap Phase-2 Message/Conversation increment (Phase 5 batch
card P5MSG-01). This is a DELIBERATELY DISTINCT table from the existing
singular ``message`` table (created by 009_conversation_message, the Phase-2
AI *chat transcript*: ``role`` + text). ``messages`` (plural) is the
outbound/inbound *delivery* log keyed on conversation + account + agent +
channel, carrying the lifecycle status state machine, provider ids, and the
send/receive timestamps. The two tables are related by concept, not by row.

Columns (per P5MSG-01 card scope):
    id, conversation_id (FK -> conversation.id, NOT NULL, CASCADE),
    account_id (FK -> account.id, SET NULL), agent_id (FK -> agent.id,
    SET NULL), channel, direction (in/out), status
    (queued/sent/delivered/failed/read), content (JSONB),
    provider_message_id, sent_at, received_at, error,
    created_at, updated_at, is_deleted

Design notes:
  * ``conversation_id`` is a hard, NOT-NULL foreign key — writing a channel
    message that is not attached to a real conversation is rejected at the
    DB level (acceptance criterion: "消息写入 conversation 关联校验").
  * ``account_id`` / ``agent_id`` are nullable, ``ON DELETE SET NULL`` —
    message delivery history survives the deletion of the account/agent that
    produced it (do not cascade-delete historical records).
  * ``content`` is JSONB (structured payload), in contrast to the ``message``
    table's ``content`` which is plain Text — matching the P5MSG-01 card.
  * ``status`` / ``direction`` / ``channel`` are stored as plain String
    (no DB CHECK constraint) to match the existing platform convention
    (e.g. conversation.status); the value domain is enforced in the
    application layer (Pydantic) and in P5MSG-02's state machine.
  * This migration only creates the ``messages`` table. The ``/api/v1/channels``
    route skeleton has NO table yet — channel configuration CRUD (types,
    account binding, rate limits) is P5MSG-03's scope.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "022_messages_channel"
down_revision = "021_phase1_persona_trigger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        # hard FK -> conversation (message must attach to a real conversation)
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        # logical delivery identity (nullable; history survives deletion)
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.String(length=50), nullable=False,
                  server_default="web"),
        sa.Column("direction", sa.String(length=10), nullable=False,
                  server_default="out"),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="queued"),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        # provider-side id (the platform's own message id, e.g. wechat msg id)
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default="false"),
        # FKs
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Indexes (lean, purposeful — matches P5MSG-02's hot query patterns:
    # list-by-conversation with optional status filter, plus channel/time).
    op.create_index("idx_messages_conversation", "messages",
                    ["conversation_id"])
    op.create_index("idx_messages_conversation_status", "messages",
                    ["conversation_id", "status"])
    op.create_index("idx_messages_channel", "messages", ["channel"])
    op.create_index("idx_messages_created", "messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_messages_created", table_name="messages")
    op.drop_index("idx_messages_channel", table_name="messages")
    op.drop_index("idx_messages_conversation_status", table_name="messages")
    op.drop_index("idx_messages_conversation", table_name="messages")
    op.drop_table("messages")
