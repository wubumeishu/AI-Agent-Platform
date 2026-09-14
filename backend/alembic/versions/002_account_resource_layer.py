"""Phase 1 Resource Layer - Account, Platform, Browser, Proxy models

Revision ID: 002_account_resource_layer
Revises: 001_crm_lifecycle
Create Date: 2026-09-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_account_resource_layer'
down_revision: Union[str, None] = '001_crm_lifecycle'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable UUID extension
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    
    # Platform table
    op.create_table(
        'platform',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('adapter_class', sa.String(length=200), nullable=True),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index('idx_platform_code', 'platform', ['code'], unique=True, postgresql_where=sa.text("is_deleted = false"))
    
    # Agent table
    op.create_table(
        'agent',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_agent_status', 'agent', ['status'], postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_agent_name', 'agent', ['name'], postgresql_where=sa.text("is_deleted = false"))
    
    # Persona table
    op.create_table(
        'persona',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('personality', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['parent_id'], ['persona.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_persona_version', 'persona', ['parent_id', 'version'], postgresql_where=sa.text("is_deleted = false"))
    
    # Account table
    op.create_table(
        'account',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('platform_id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('username', sa.String(length=200), nullable=True),
        sa.Column('password_encrypted', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_account_platform', 'account', ['platform_id'], postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_account_status', 'account', ['status'], postgresql_where=sa.text("is_deleted = false"))
    
    # Browser Profile table
    op.create_table(
        'browser_profile',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('profile_id', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('connection_status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_browser_profile_provider', 'browser_profile', ['provider'], postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_browser_profile_profile_id', 'browser_profile', ['profile_id'], postgresql_where=sa.text("is_deleted = false"))
    
    # Proxy table
    op.create_table(
        'proxy',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('type', sa.String(length=10), nullable=False),
        sa.Column('host', sa.String(length=200), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=True),
        sa.Column('password_encrypted', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('last_tested', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_proxy_status', 'proxy', ['status'], postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_proxy_type', 'proxy', ['type'], postgresql_where=sa.text("is_deleted = false"))
    
    # Agent-Persona binding table
    op.create_table(
        'agent_persona_binding',
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('persona_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False),
        sa.Column('bound_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_id'], ['agent.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['persona_id'], ['persona.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('account_id', 'agent_id', 'persona_id'),
    )
    op.create_index('idx_agent_persona_account', 'agent_persona_binding', ['account_id', 'agent_id', 'persona_id'])
    
    # Account-Browser binding table
    op.create_table(
        'account_browser_binding',
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('profile_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bound_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['profile_id'], ['browser_profile.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('account_id', 'profile_id'),
    )
    op.create_index('idx_account_browser_account', 'account_browser_binding', ['account_id', 'profile_id'])
    
    # Account-Proxy binding table
    op.create_table(
        'account_proxy_binding',
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('proxy_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bound_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['proxy_id'], ['proxy.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('account_id', 'proxy_id'),
    )
    op.create_index('idx_account_proxy_account', 'account_proxy_binding', ['account_id', 'proxy_id'])
    
    # Insert default platforms
    op.execute("""
        INSERT INTO platform (id, code, name, capabilities, adapter_class, status, created_at, is_deleted)
        VALUES 
        (uuid_generate_v4(), 'wechat', '微信', '["messaging","friend_management","moment","group"]', 'platforms.wechat.WeChatAdapter', 'active', NOW(), false),
        (uuid_generate_v4(), 'douyin', '抖音', '["messaging","comment_reply"]', 'platforms.douyin.DouyinAdapter', 'active', NOW(), false),
        (uuid_generate_v4(), 'xiaohongshu', '小红书', '["messaging","comment_reply"]', 'platforms.xiaohongshu.XiaoHongShuAdapter', 'active', NOW(), false)
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
    for table in ['agent', 'account', 'browser_profile', 'proxy']:
        op.execute(f"""
            CREATE TRIGGER update_{table}_updated_at 
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    # Drop triggers
    for table in ['agent', 'account', 'browser_profile', 'proxy']:
        op.execute(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table}")
    
    # Drop function
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")
    
    # Drop tables in reverse order
    op.drop_table('account_proxy_binding')
    op.drop_table('account_browser_binding')
    op.drop_table('agent_persona_binding')
    op.drop_table('proxy')
    op.drop_table('browser_profile')
    op.drop_table('account')
    op.drop_table('persona')
    op.drop_table('agent')
    op.drop_table('platform')
    
    # Drop extensions
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
