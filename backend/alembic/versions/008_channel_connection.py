"""Add connection status and statistics columns to private_channel

Revision ID: 008_channel_connection
Revises: 007_prompt_template
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008_channel_connection'
down_revision = '007_prompt_template'
branch_labels = None
depends_on = None


def upgrade():
    # Add connection status columns
    op.add_column('private_channel', sa.Column('connection_status', sa.String(length=20), nullable=True))
    op.add_column('private_channel', sa.Column('last_connection', sa.DateTime(timezone=True), nullable=True))
    
    # Add statistics columns
    op.add_column('private_channel', sa.Column('contact_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('private_channel', sa.Column('message_count', sa.Integer(), nullable=False, server_default='0'))
    
    # Create index for connection status
    op.create_index('idx_private_channel_connection', 'private_channel', ['connection_status'],
                    postgresql_where=sa.text("is_deleted = false"))


def downgrade():
    op.drop_index('idx_private_channel_connection', table_name='private_channel')
    op.drop_column('private_channel', 'message_count')
    op.drop_column('private_channel', 'contact_count')
    op.drop_column('private_channel', 'last_connection')
    op.drop_column('private_channel', 'connection_status')
