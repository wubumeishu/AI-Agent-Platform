"""Phase 0 CRM Foundation - Lifecycle, Lead, Customer, Tag models

Revision ID: 001_crm_lifecycle
Revises: 
Create Date: 2026-09-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_crm_lifecycle'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable UUID extension
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    
    # LifecycleStage table
    op.create_table(
        'lifecycle_stage',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('order', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index('idx_lifecycle_code', 'lifecycle_stage', ['code'], unique=True)
    
    # LifecycleStageLog table
    op.create_table(
        'lifecycle_stage_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('from_stage_code', sa.String(length=50), nullable=True),
        sa.Column('to_stage_code', sa.String(length=50), nullable=False),
        sa.Column('changed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='CASCADE'),
    )
    op.create_index('idx_lifecycle_log_customer', 'lifecycle_stage_log', ['customer_id'])
    
    # Lead table
    op.create_table(
        'lead',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('company', sa.String(length=200), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('email', sa.String(length=200), nullable=True),
        sa.Column('source', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, default='new'),
        sa.Column('lifecycle_stage_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['lifecycle_stage_id'], ['lifecycle_stage.id'], ondelete='SET NULL'),
    )
    op.create_index('idx_lead_status', 'lead', ['status'], postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_lead_source', 'lead', ['source'], postgresql_where=sa.text("is_deleted = false"))
    
    # Customer table
    op.create_table(
        'customer',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('company', sa.String(length=200), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('email', sa.String(length=200), nullable=True),
        sa.Column('wechat_id', sa.String(length=200), nullable=True),
        sa.Column('lifecycle_stage_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('assigned_agent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['lifecycle_stage_id'], ['lifecycle_stage.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['assigned_agent_id'], ['agent.id'], ondelete='SET NULL'),
    )
    op.create_index('idx_customer_lifecycle', 'customer', ['lifecycle_stage_id'], postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_customer_wechat', 'customer', ['wechat_id'], postgresql_where=sa.text("is_deleted = false AND wechat_id IS NOT NULL"))
    op.create_index('idx_customer_phone', 'customer', ['phone'], postgresql_where=sa.text("is_deleted = false AND phone IS NOT NULL"))
    op.create_index('idx_customer_email', 'customer', ['email'], postgresql_where=sa.text("is_deleted = false AND email IS NOT NULL"))
    
    # Tag table
    op.create_table(
        'tag',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('color', sa.String(length=20), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index('idx_tag_name', 'tag', ['name'], unique=True)
    
    # CustomerTag junction table
    op.create_table(
        'customer_tag',
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tag_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('customer_id', 'tag_id'),
    )
    op.create_index('idx_customer_tag_tag', 'customer_tag', ['tag_id'])
    
    # Insert default lifecycle stages
    op.execute("""
        INSERT INTO lifecycle_stage (id, code, name, description, order, created_at, is_deleted)
        VALUES 
        (uuid_generate_v4(), 'new', '潜在客户', '新接入的潜在客户', 1, NOW(), false),
        (uuid_generate_v4(), 'contacted', '已接触', '已建立初步联系', 2, NOW(), false),
        (uuid_generate_v4(), 'qualified', '已筛选', '已确认需求与预算', 3, NOW(), false),
        (uuid_generate_v4(), 'proposal', '方案中', '正在提供方案报价', 4, NOW(), false),
        (uuid_generate_v4(), 'negotiation', '谈判中', '进入商务谈判阶段', 5, NOW(), false),
        (uuid_generate_v4(), 'won', '成交', '已成功签约', 6, NOW(), false),
        (uuid_generate_v4(), 'lost', '流失', '项目流失', 7, NOW(), false)
    """)
    
    # Create update trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    # Create triggers for tables with updated_at
    for table in ['lead', 'customer', 'tag']:
        op.execute(f"""
            CREATE TRIGGER update_{table}_updated_at 
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    # Drop triggers
    for table in ['lead', 'customer', 'tag']:
        op.execute(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table}")
    
    # Drop function
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")
    
    # Drop tables in reverse order
    op.drop_table('customer_tag')
    op.drop_table('tag')
    op.drop_table('customer')
    op.drop_table('lead')
    op.drop_table('lifecycle_stage_log')
    op.drop_table('lifecycle_stage')
    
    # Drop extensions
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
