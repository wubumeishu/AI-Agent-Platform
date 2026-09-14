"""add_agent_customer_binding

Revision ID: 006_agent_customer_binding
Revises: 005_private_domain
Create Date: 2026-09-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '006_agent_customer_binding'
down_revision: Union[str, None] = '005_private_domain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create agent table if not exists (may have been created in 002)
    op.create_table(
        'agent',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_agent_status', 'agent', ['status'], postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_agent_name', 'agent', ['name'], postgresql_where=sa.text("is_deleted = false"))
    
    # Create agent_customer_binding table
    op.create_table(
        'agent_customer_binding',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('assigned_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['agent_id'], ['agent.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_agent_customer_agent', 'agent_customer_binding', ['agent_id'], postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_agent_customer_customer', 'agent_customer_binding', ['customer_id'], postgresql_where=sa.text("is_deleted = false"))
    op.create_index('idx_agent_customer_unique', 'agent_customer_binding', ['agent_id', 'customer_id'], unique=True, postgresql_where=sa.text("is_deleted = false"))
    
    # Create update trigger for agent_customer_binding
    op.execute("""
        CREATE TRIGGER update_agent_customer_binding_updated_at 
        BEFORE UPDATE ON agent_customer_binding
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS update_agent_customer_binding_updated_at ON agent_customer_binding")
    
    # Drop tables
    op.drop_table('agent_customer_binding')
    op.drop_table('agent')
