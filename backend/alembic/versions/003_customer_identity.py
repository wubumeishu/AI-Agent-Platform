"""customer_identity table

Revision ID: 003_customer_identity
Revises: 002_account_resource_layer
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003_customer_identity'
down_revision = '002_account_resource_layer'
branch_labels = None
depends_on = None


def upgrade():
    # Create customer_identity table
    op.create_table(
        'customer_identity',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('platform', sa.String(length=50), nullable=False),
        sa.Column('platform_account_id', sa.String(length=200), nullable=False),
        sa.Column('platform_username', sa.String(length=100), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('email', sa.String(length=200), nullable=True),
        sa.Column('external_id', sa.String(length=500), nullable=True),
        sa.Column('match_score', sa.Float(), nullable=True),
        sa.Column('confidence', sa.String(length=20), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('source_id', sa.String(length=500), nullable=True),
        sa.Column('extra_data', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('idx_ci_platform_account', 'customer_identity', ['platform', 'platform_account_id'], unique=True)
    op.create_index('idx_ci_phone', 'customer_identity', ['phone'])
    op.create_index('idx_ci_email', 'customer_identity', ['email'])
    op.create_index('idx_ci_external_id', 'customer_identity', ['external_id'])
    op.create_index('idx_ci_customer', 'customer_identity', ['customer_id'])


def downgrade():
    op.drop_table('customer_identity')
