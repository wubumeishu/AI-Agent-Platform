"""Add usage tracking fields to content_item table

Revision ID: 006_content_usage
Revises: 005_private_domain
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_content_usage'
down_revision = '005_private_domain'
branch_labels = None
depends_on = None


def upgrade():
    # Add usage tracking columns
    op.add_column('content_item', sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('content_item', sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True))
    
    # Add indexes for search and filtering
    op.create_index('idx_content_item_category', 'content_item', ['category'],
                    postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_content_item_usage', 'content_item', ['usage_count'],
                    postgresql_where=sa.text("is_deleted = false"))
    
    # Add full-text search index
    op.create_index('idx_content_item_search', 'content_item', 
                    sa.text("gin(to_tsvector('english', coalesce(title, '') || ' ' || coalesce(summary, '')))"),
                    postgresql_using='gin')


def downgrade():
    # Drop indexes
    op.drop_index('idx_content_item_search', table_name='content_item')
    op.drop_index('idx_content_item_usage', table_name='content_item')
    op.drop_index('idx_content_item_category', table_name='content_item')
    
    # Drop columns
    op.drop_column('content_item', 'last_used_at')
    op.drop_column('content_item', 'usage_count')
