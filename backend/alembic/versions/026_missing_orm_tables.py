"""Reconcile the legacy production DB with the current ORM table set.

Revision ID: 026_missing_orm_tables
Revises: 025_nurture_step_execution
Create Date: 2026-09-14

The production database ``ai_agent_platform`` was advanced out-of-band to
``024_channel_config`` (legacy ``create_all`` + ``alembic stamp``). Its ORM
table set has therefore diverged from the migration chain: the 12 tables
below are defined by the current ORM (``app.db.models``) and are created by
earlier revisions in the *fresh-DB* path, but were never physically created
on the production DB:

    intents, intent_action_logs          (from 008_intent)
    memory, memory_fragment,
    conversation_summary, context_window (from 011_memory_system)
    decision_log                         (from 013_decision_engine)
    prompt_template, prompt_template_usage (from 007_prompt_template)
    nurture_plan_item (+ is_deleted from 017), segment_member (005_private_domain)
    content_generation                   (from 018_content_generation)

Any Memory / Context-Window / Decision / Prompt-Template / Intent /
Content-Generation / Nurture-step service on the default database would
500 with ``relation does not exist``.

This revision recreates exactly those 12 tables (DDL transcribed verbatim
from 007/008/011/013/018, with the 017 ``nurture_plan_item.is_deleted``
column folded in) using ``IF NOT EXISTS`` so it is:

  * safe on the legacy production DB (already-present tables are untouched),
  * a no-op on a fresh database already advanced through 007..025, and
  * re-runnable.

The 3 default prompt-template seed rows from 007 are re-applied
idempotently (``ON CONFLICT (name) DO NOTHING``) so production reaches true
head parity without clobbering existing rows.

FK handling for the legacy-DB fork
----------------------------------
The production DB is legacy (out-of-band ``create_all`` + ``stamp``). Three of
its base tables still carry the *old* string primary keys even though the
current ORM has moved to UUID:

    nurture_plan.id      -> varchar
    content_item.id      -> varchar
    customer_segment.id  -> varchar

A ``UUID`` foreign key into a ``varchar`` parent column is rejected by
PostgreSQL (``data types ... are uuid and character varying``), so this
revision deliberately leaves those reference columns **UN-constrained** —
exactly the 020_workflow_runtime_tables precedent ("column reference UUIDs
deliberately left UN-constrained, so the migration stays independently
applicable and does not impose new FK constraints that could reject existing
rows"). The columns themselves keep their UUID type, matching the ORM.

Every other foreign key in this revision targets a table whose production
``id`` is already ``uuid`` (``customer``, ``conversation``, ``persona``, and
``nurture_plan_item`` created earlier in this same revision), so those
constraints are retained.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "026_missing_orm_tables"
down_revision = "025_nurture_step_execution"
branch_labels = None
depends_on = None


def _create_table(*args, **kwargs):
    """op.create_table with idempotency forced on."""
    kwargs["if_not_exists"] = True
    op.create_table(*args, **kwargs)


def _create_index(*args, **kwargs):
    kwargs["if_not_exists"] = True
    op.create_index(*args, **kwargs)


def upgrade() -> None:
    # ---- prompt_template (from 007_prompt_template) ----
    _create_table(
        "prompt_template",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("template_type", sa.String(length=50), nullable=False, server_default="custom"),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("variables", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["parent_id"], ["prompt_template.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    _create_index(
        "idx_template_parent_version", "prompt_template",
        ["parent_id", "version"],
        postgresql_where=sa.text("is_deleted = false"),
    )
    _create_index(
        "idx_template_type_category", "prompt_template",
        ["template_type", "category"],
        postgresql_where=sa.text("is_deleted = false"),
    )
    _create_table(
        "prompt_template_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rendered_content", sa.Text(), nullable=False),
        sa.Column("variables_used", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["prompt_template.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index(
        "idx_usage_template_created", "prompt_template_usage",
        ["template_id", "created_at"],
    )
    # Idempotent default-template seed (from 007). ON CONFLICT (name) keeps
    # re-runs and already-seeded DBs a no-op; the unique(name) index is in place.
    op.execute(
        """
        INSERT INTO prompt_template
            (id, name, description, content, template_type, category,
             variables, version, is_baseline, created_at, updated_at)
        VALUES
            (gen_random_uuid(), '系统提示词模板', '默认系统提示词，定义AI助手的基本行为和角色',
             '你是一个专业的AI助手。你的任务是帮助用户解决问题、提供信息和完成任务。',
             'system', 'system', '[{"name": "user_context"}, {"name": "task_description"}]',
             1, true, NOW(), NOW()),
            (gen_random_uuid(), '开场白模板', '对话开始时的问候语模板',
             '你好，{{user_name}}！我是你的AI助手 {{assistant_name}}，很高兴为你服务！',
             'greeting', 'conversation', '[{"name": "user_name"}, {"name": "assistant_name"}]',
             1, true, NOW(), NOW()),
            (gen_random_uuid(), '对话模板', '标准对话流程模板',
             '## 当前对话上下文\\n{{context}}\\n\\n## 用户问题\\n{{question}}\\n\\n## 助手回应',
             'conversation', 'dialogue', '[{"name": "context"}, {"name": "question"}]',
             1, true, NOW(), NOW())
        ON CONFLICT (name) DO NOTHING
        """
    )

    # ---- intents / intent_action_logs (from 008_intent) ----
    _create_table(
        "intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("intent_type", sa.String(length=100), nullable=False),
        sa.Column("intent_name", sa.String(length=200), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column("extracted_entities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("matched_action", sa.String(length=200), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("ix_intents_intent_type", "intents", ["intent_type"], unique=False)
    _create_index("ix_intents_conversation_id", "intents", ["conversation_id"], unique=False)
    _create_table(
        "intent_action_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("intent_id", sa.Uuid(), nullable=True),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("action_target", sa.String(length=500), nullable=True),
        sa.Column("action_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("executed", sa.Boolean(), nullable=True),
        sa.Column("execution_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["intent_id"], ["intents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("ix_intent_action_logs_intent_id", "intent_action_logs", ["intent_id"], unique=False)

    # ---- memory / memory_fragment / conversation_summary / context_window (011) ----
    _create_table(
        "memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_type", sa.String(length=50), nullable=False, server_default="preference"),
        sa.Column("category", sa.String(length=50), nullable=False, server_default="general"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="conversation"),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_memory_customer", "memory", ["customer_id"])
    _create_index("idx_memory_type", "memory", ["memory_type"])
    _create_index("idx_memory_category", "memory", ["category"])
    _create_index("idx_memory_created", "memory", ["created_at"])
    _create_index("idx_memory_tags", "memory", ["tags"], postgresql_using="gin")
    _create_table(
        "memory_fragment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fragment_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memory.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_fragment_memory", "memory_fragment", ["memory_id"])
    _create_table(
        "conversation_summary",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary_type", sa.String(length=50), nullable=False, server_default="brief"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("key_points", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("sentiment", sa.String(length=20), nullable=True),
        sa.Column("action_items", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_summary_conversation", "conversation_summary", ["conversation_id"])
    _create_index("idx_summary_created", "conversation_summary", ["created_at"])
    _create_table(
        "context_window",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="4000"),
        sa.Column("compressed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_compressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["summary_id"], ["conversation_summary.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id"),
    )
    _create_index("idx_context_window_conversation", "context_window", ["conversation_id"])

    # ---- decision_log (from 013_decision_engine) ----
    _create_table(
        "decision_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("persona_id", sa.Uuid(), nullable=True),
        sa.Column("intent_type", sa.String(length=100), nullable=False),
        sa.Column("intent_confidence", sa.Float(), nullable=True),
        sa.Column("strategy", sa.String(length=20), nullable=False),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("quality_passed", sa.Boolean(), nullable=True),
        sa.Column("explanation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processing_time_ms", sa.Float(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["persona_id"], ["persona.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_decision_log_conversation", "decision_log", ["conversation_id"], unique=False)
    _create_index("idx_decision_log_strategy", "decision_log", ["strategy"], unique=False)
    _create_index("idx_decision_log_created", "decision_log", ["created_at"], unique=False)

    # ---- nurture_plan_item (005 + 017 is_deleted), segment_member (005) ----
    _create_table(
        "nurture_plan_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("delay_hours", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trigger_type", sa.String(length=50), nullable=False, server_default="time_based"),
        sa.Column("config", postgresql.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Legacy prod: nurture_plan.id and content_item.id are varchar, so a
        # UUID FK would type-mismatch. Keep the UUID columns, drop the
        # constraints (020 precedent). See revision docstring.
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_nurture_plan_item_plan", "nurture_plan_item", ["plan_id"])
    _create_index("idx_nurture_plan_item_order", "nurture_plan_item", ["plan_id", "step_order"])
    _create_table(
        "segment_member",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("added_by", sa.String(length=100), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        # Legacy prod fork: customer_segment.id is varchar, so its UUID FK is
        # deliberately UN-constrained (020 precedent). customer.id is uuid and
        # is kept. See revision docstring.
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_segment_member_segment", "segment_member", ["segment_id"])
    _create_index("idx_segment_member_customer", "segment_member", ["customer_id"])
    _create_index("idx_segment_member_unique", "segment_member", ["segment_id", "customer_id"], unique=True)

    # ---- content_generation (from 018_content_generation; needs nurture_plan_item) ----
    _create_table(
        "content_generation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("strategy", sa.String(length=20), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("segment_id", sa.Uuid(), nullable=True),
        sa.Column("stage_code", sa.String(length=50), nullable=True),
        sa.Column("content_id", sa.Uuid(), nullable=True),
        sa.Column("nurture_plan_id", sa.Uuid(), nullable=True),
        sa.Column("plan_step_id", sa.Uuid(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("quality_passed", sa.Boolean(), nullable=True),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processing_time_ms", sa.Float(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Legacy prod fork: customer_segment / content_item / nurture_plan have
        # varchar ids, so their UUID FKs are deliberately UN-constrained (020
        # precedent). plan_step_id -> nurture_plan_item (uuid, created above in
        # this revision) is kept. See revision docstring.
        sa.ForeignKeyConstraint(["plan_step_id"], ["nurture_plan_item.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_content_generation_account", "content_generation", ["account_id"], unique=False)
    _create_index("idx_content_generation_source", "content_generation", ["source"], unique=False)
    _create_index("idx_content_generation_strategy", "content_generation", ["strategy"], unique=False)
    _create_index("idx_content_generation_content", "content_generation", ["content_id"], unique=False)
    _create_index("idx_content_generation_plan", "content_generation", ["nurture_plan_id"], unique=False)
    _create_index("idx_content_generation_created", "content_generation", ["created_at"], unique=False)


def downgrade() -> None:
    # Drop in reverse dependency order; if_exists keeps re-runs safe.
    op.drop_index("idx_content_generation_created", table_name="content_generation", if_exists=True)
    op.drop_index("idx_content_generation_plan", table_name="content_generation", if_exists=True)
    op.drop_index("idx_content_generation_content", table_name="content_generation", if_exists=True)
    op.drop_index("idx_content_generation_strategy", table_name="content_generation", if_exists=True)
    op.drop_index("idx_content_generation_source", table_name="content_generation", if_exists=True)
    op.drop_index("idx_content_generation_account", table_name="content_generation", if_exists=True)
    op.drop_table("content_generation", if_exists=True)

    op.drop_index("idx_segment_member_unique", table_name="segment_member", if_exists=True)
    op.drop_index("idx_segment_member_customer", table_name="segment_member", if_exists=True)
    op.drop_index("idx_segment_member_segment", table_name="segment_member", if_exists=True)
    op.drop_table("segment_member", if_exists=True)

    op.drop_index("idx_nurture_plan_item_order", table_name="nurture_plan_item", if_exists=True)
    op.drop_index("idx_nurture_plan_item_plan", table_name="nurture_plan_item", if_exists=True)
    op.drop_table("nurture_plan_item", if_exists=True)

    op.drop_index("idx_decision_log_created", table_name="decision_log", if_exists=True)
    op.drop_index("idx_decision_log_strategy", table_name="decision_log", if_exists=True)
    op.drop_index("idx_decision_log_conversation", table_name="decision_log", if_exists=True)
    op.drop_table("decision_log", if_exists=True)

    op.drop_index("idx_context_window_conversation", table_name="context_window", if_exists=True)
    op.drop_table("context_window", if_exists=True)
    op.drop_index("idx_summary_created", table_name="conversation_summary", if_exists=True)
    op.drop_index("idx_summary_conversation", table_name="conversation_summary", if_exists=True)
    op.drop_table("conversation_summary", if_exists=True)
    op.drop_index("idx_fragment_memory", table_name="memory_fragment", if_exists=True)
    op.drop_table("memory_fragment", if_exists=True)
    op.drop_index("idx_memory_tags", table_name="memory", if_exists=True)
    op.drop_index("idx_memory_created", table_name="memory", if_exists=True)
    op.drop_index("idx_memory_category", table_name="memory", if_exists=True)
    op.drop_index("idx_memory_type", table_name="memory", if_exists=True)
    op.drop_index("idx_memory_customer", table_name="memory", if_exists=True)
    op.drop_table("memory", if_exists=True)

    op.drop_index("ix_intent_action_logs_intent_id", table_name="intent_action_logs", if_exists=True)
    op.drop_table("intent_action_logs", if_exists=True)
    op.drop_index("ix_intents_conversation_id", table_name="intents", if_exists=True)
    op.drop_index("ix_intents_intent_type", table_name="intents", if_exists=True)
    op.drop_table("intents", if_exists=True)

    op.drop_index("idx_usage_template_created", table_name="prompt_template_usage", if_exists=True)
    op.drop_table("prompt_template_usage", if_exists=True)
    op.drop_index("idx_template_type_category", table_name="prompt_template", if_exists=True)
    op.drop_index("idx_template_parent_version", table_name="prompt_template", if_exists=True)
    op.drop_table("prompt_template", if_exists=True)
