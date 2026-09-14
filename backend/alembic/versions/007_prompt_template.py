"""Prompt Template Tables

Revision ID: 007_prompt_template
Revises: 006_tag_system
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '007_prompt_template'
down_revision = '006_tag_system'
branch_labels = None
depends_on = None


def upgrade():
    # Prompt template table
    op.create_table(
        'prompt_template',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('template_type', sa.String(length=50), nullable=False, server_default='custom'),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('variables', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('is_baseline', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['parent_id'], ['prompt_template.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    
    # Indexes
    op.create_index('idx_template_parent_version', 'prompt_template', 
                    ['parent_id', 'version'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_template_type_category', 'prompt_template', 
                    ['template_type', 'category'],
                    postgresql_where=sa.text("is_deleted = false"))
    
    # Prompt template usage table
    op.create_table(
        'prompt_template_usage',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('template_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('rendered_content', sa.Text(), nullable=False),
        sa.Column('variables_used', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['prompt_template.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    
    # Indexes for usage tracking
    op.create_index('idx_usage_template_created', 'prompt_template_usage', 
                    ['template_id', 'created_at'])
    
    # Insert default templates
    op.execute("""
        INSERT INTO prompt_template (id, name, description, content, template_type, category, variables, version, is_baseline, created_at, updated_at)
        VALUES 
        (gen_random_uuid(), '系统提示词模板', '默认系统提示词，定义AI助手的基本行为和角色', 
         '你是一个专业的AI助手。你的任务是帮助用户解决问题、提供信息和完成任务。', 
         'system', 'system', '[{"name": "user_context"}, {"name": "task_description"}]', 1, true, NOW(), NOW()),
        (gen_random_uuid(), '开场白模板', '对话开始时的问候语模板',
         '你好，{{user_name}}！我是你的AI助手 {{assistant_name}}，很高兴为你服务！',
         'greeting', 'conversation', '[{"name": "user_name"}, {"name": "assistant_name"}]', 1, true, NOW(), NOW()),
        (gen_random_uuid(), '对话模板', '标准对话流程模板',
         '## 当前对话上下文\n{{context}}\n\n## 用户问题\n{{question}}\n\n## 助手回应',
         'conversation', 'dialogue', '[{"name": "context"}, {"name": "question"}]', 1, true, NOW(), NOW())
    """)


def downgrade():
    op.drop_table('prompt_template_usage')
    op.drop_table('prompt_template')
