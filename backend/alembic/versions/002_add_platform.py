"""
Database Migration: Add Platform table
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers
revision = '002_add_platform'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade():
    # Create platform table
    op.create_table(
        'platform',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('capabilities', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('adapter_class', sa.String(200), nullable=True),
        sa.Column('config', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=False),
    )
    
    # Create indexes
    op.create_index('idx_platform_code', 'platform', ['code'], postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_platform_status', 'platform', ['status'], postgresql_where=sa.text("is_deleted = false"))
    
    # Add updated_at trigger function if not exists
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    # Create trigger for platform table
    op.execute("""
        CREATE TRIGGER update_platform_updated_at 
        BEFORE UPDATE ON platform 
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)
    
    # Insert default platforms
    op.execute("""
        INSERT INTO platform (code, name, capabilities, adapter_class, config, status)
        VALUES 
            ('wechat', '微信', '["messaging","friend_management","moment","group"]', 'platforms.wechat.WeChatAdapter', '{}', 'active'),
            ('douyin', '抖音', '["messaging","comment_reply"]', 'platforms.douyin.DouyinAdapter', '{}', 'active'),
            ('xiaohongshu', '小红书', '["messaging","comment_reply"]', 'platforms.xiaohongshu.XiaoHongShuAdapter', '{}', 'active')
        ON CONFLICT (code) DO NOTHING;
    """)


def downgrade():
    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS update_platform_updated_at ON platform")
    
    # Drop table
    op.drop_table('platform')
