"""private_domain tables - NurturePlan, ContentItem, FollowUpTask, CustomerSegment, DealPipeline

Revision ID: 005_private_domain
Revises: 004_private_channel
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005_private_domain'
down_revision = '004_private_channel'
branch_labels = None
depends_on = None


def upgrade():
    # NurturePlan table
    op.create_table(
        'nurture_plan',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('channel_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('schedule_type', sa.String(length=50), nullable=False, server_default='fixed'),
        sa.Column('schedule_config', postgresql.JSON(), nullable=True),
        sa.Column('sequence_steps', postgresql.JSON(), nullable=True),
        sa.Column('target_segment_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('trigger_conditions', postgresql.JSON(), nullable=True),
        sa.Column('performance_metrics', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['channel_id'], ['private_channel.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_segment_id'], ['customer_segment.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_nurture_plan_channel', 'nurture_plan', ['channel_id'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_nurture_plan_status', 'nurture_plan', ['status'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_nurture_plan_account', 'nurture_plan', ['account_id'],
                    postgresql_where=sa.text("is_deleted = false"))
    
    # NurturePlanItem table
    op.create_table(
        'nurture_plan_item',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('step_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('content_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('delay_hours', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('trigger_type', sa.String(length=50), nullable=False, server_default='time_based'),
        sa.Column('config', postgresql.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['nurture_plan.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['content_id'], ['content_item.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_nurture_plan_item_plan', 'nurture_plan_item', ['plan_id'])
    op.create_index('idx_nurture_plan_item_order', 'nurture_plan_item', ['plan_id', 'step_order'])
    
    # ContentItem table
    op.create_table(
        'content_item',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('channel_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('content_type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('media_urls', postgresql.JSON(), nullable=True),
        sa.Column('tags', postgresql.JSON(), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('preview_data', postgresql.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['channel_id'], ['private_channel.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_content_item_account', 'content_item', ['account_id'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_content_item_channel', 'content_item', ['channel_id'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_content_item_type', 'content_item', ['content_type'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_content_item_status', 'content_item', ['status'],
                    postgresql_where=sa.text("is_deleted = false"))
    
    # FollowUpTask table
    op.create_table(
        'follow_up_task',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('task_type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reminder_config', postgresql.JSON(), nullable=True),
        sa.Column('result', postgresql.JSON(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('assigned_to', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id']),
        sa.ForeignKeyConstraint(['lead_id'], ['lead.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_follow_up_task_account', 'follow_up_task', ['account_id'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_follow_up_task_customer', 'follow_up_task', ['customer_id'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_follow_up_task_status', 'follow_up_task', ['status'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_follow_up_task_due', 'follow_up_task', ['due_date'],
                    postgresql_where=sa.text("is_deleted = false"))
    
    # CustomerSegment table
    op.create_table(
        'customer_segment',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('segment_type', sa.String(length=50), nullable=False, server_default='manual'),
        sa.Column('filter_config', postgresql.JSON(), nullable=True),
        sa.Column('member_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_customer_segment_account', 'customer_segment', ['account_id'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_customer_segment_type', 'customer_segment', ['segment_type'])
    
    # SegmentMember table
    op.create_table(
        'segment_member',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('segment_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('added_by', sa.String(length=100), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['segment_id'], ['customer_segment.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_segment_member_segment', 'segment_member', ['segment_id'])
    op.create_index('idx_segment_member_customer', 'segment_member', ['customer_id'])
    op.create_index('idx_segment_member_unique', 'segment_member', ['segment_id', 'customer_id'], unique=True)
    
    # DealPipeline table
    op.create_table(
        'deal_pipeline',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('pipeline_type', sa.String(length=50), nullable=False, server_default='sales'),
        sa.Column('stages', postgresql.JSON(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_deal_pipeline_account', 'deal_pipeline', ['account_id'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_deal_pipeline_default', 'deal_pipeline', ['is_default'],
                    postgresql_where=sa.text("is_deleted = false"))
    
    # DealStage table
    op.create_table(
        'deal_stage',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('pipeline_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('probability', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('config', postgresql.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['pipeline_id'], ['deal_pipeline.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_deal_stage_pipeline', 'deal_stage', ['pipeline_id'])
    op.create_index('idx_deal_stage_order', 'deal_stage', ['pipeline_id', 'order'])
    
    # DealItem table
    op.create_table(
        'deal_item',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('pipeline_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stage_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('value', sa.Integer(), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='CNY'),
        sa.Column('expected_close_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='open'),
        sa.Column('winner_reason', sa.String(length=200), nullable=True),
        sa.Column('loser_reason', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['pipeline_id'], ['deal_pipeline.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['stage_id'], ['deal_stage.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id']),
        sa.ForeignKeyConstraint(['lead_id'], ['lead.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_deal_item_pipeline', 'deal_item', ['pipeline_id'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_deal_item_stage', 'deal_item', ['stage_id'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_deal_item_customer', 'deal_item', ['customer_id'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_deal_item_status', 'deal_item', ['status'],
                    postgresql_where=sa.text("is_deleted = false"))
    
    # Create triggers for tables with updated_at
    for table in ['nurture_plan', 'content_item', 'follow_up_task', 
                  'customer_segment', 'deal_pipeline', 'deal_stage', 'deal_item']:
        op.execute(f"""
            CREATE TRIGGER update_{table}_updated_at 
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade():
    # Drop triggers
    for table in ['nurture_plan', 'content_item', 'follow_up_task', 
                  'customer_segment', 'deal_pipeline', 'deal_stage', 'deal_item']:
        op.execute(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table}")
    
    # Drop tables in reverse order
    op.drop_table('deal_item')
    op.drop_table('deal_stage')
    op.drop_table('deal_pipeline')
    op.drop_table('segment_member')
    op.drop_table('customer_segment')
    op.drop_table('follow_up_task')
    op.drop_table('content_item')
    op.drop_table('nurture_plan_item')
    op.drop_table('nurture_plan')
