"""private_channel table

Revision ID: 004_private_channel
Revises: 003_customer_identity
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_private_channel'
down_revision = '003_customer_identity'
branch_labels = None
depends_on = None


def upgrade():
    # Create private_channel table
    op.create_table(
        'private_channel',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('platform_id', sa.String(length=50), nullable=False),
        sa.Column('channel_type', sa.String(length=50), nullable=False, server_default='wechat'),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('contact_info', postgresql.JSON(), nullable=True),
        sa.Column('avatar_url', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('tags', postgresql.JSON(), nullable=True),
        sa.Column('extra_config', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    
    # Create indexes
    op.create_index('idx_private_channel_account', 'private_channel', ['account_id'], 
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_private_channel_type', 'private_channel', ['channel_type'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_private_channel_status', 'private_channel', ['status'],
                    postgresql_where=sa.text("is_deleted = false"))
    
    # Create update trigger
    op.execute("""
        CREATE TRIGGER update_private_channel_updated_at 
        BEFORE UPDATE ON private_channel
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS update_private_channel_updated_at ON private_channel")
    op.drop_table('private_channel')
