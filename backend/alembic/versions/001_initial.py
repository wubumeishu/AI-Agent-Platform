"""Stub: repair broken revision chain.

The real '001_initial' migration (which created the legacy CRM tables)
is missing from alembic/versions, but 002_add_platform references it as
down_revision. This QA stub satisfies the chain so `alembic upgrade head`
can run. In production, the real 001_initial migration must be restored
or the chain re-baselined.

Revision ID: 001_initial
Revises:
Create Date: 2026-09-14

"""
from typing import Sequence, Union

from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')


def downgrade() -> None:
    pass
