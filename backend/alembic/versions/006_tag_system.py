"""Tag Schemas for CRM module

Revision ID: 006_tag_system
Revises: 005_private_domain
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '006_tag_system'
down_revision = '005_private_domain'
branch_labels = None
depends_on = None


def upgrade():
    # Tag table
    op.create_table(
        'tag',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('color', sa.String(length=20), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['parent_id'], ['tag.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_tag_name', 'tag', ['name'])
    op.create_index('idx_tag_parent', 'tag', ['parent_id'])
    op.create_index('idx_tag_deleted', 'tag', ['is_deleted'])
    
    # Tag-Customer association table
    op.create_table(
        'tag_customer',
        sa.Column('tag_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('tag_id', 'customer_id'),
    )
    op.create_index('idx_tc_customer', 'tag_customer', ['customer_id'])
    
    # Tag-Lead association table
    op.create_table(
        'tag_lead',
        sa.Column('tag_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lead_id'], ['lead.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('tag_id', 'lead_id'),
    )
    op.create_index('idx_tl_lead', 'tag_lead', ['lead_id'])


def downgrade():
    op.drop_table('tag_lead')
    op.drop_table('tag_customer')
    op.drop_table('tag')
