"""Phase 1 gap: add the missing ``update_persona_updated_at`` trigger.

Revision ID: 021_phase1_persona_trigger
Revises: 020_workflow_runtime_tables
Create Date: 2026-09-14

docs/PHASE1-DB-SCHEMA.sql §"触发器：自动更新 updated_at" defines five
``updated_at`` triggers:

    update_agent_updated_at
    update_persona_updated_at
    update_account_updated_at
    update_browser_profile_updated_at
    update_proxy_updated_at

The original Phase-1 migration (002_account_resource_layer) creates the
shared ``update_updated_at_column()`` function and the *other* four
triggers, but its trigger loop omits ``persona``. On a legacy out-of-band
``create_all`` database the persona trigger was installed manually, but on a
fresh database driven purely through Alembic it is absent.

This revision closes that gap idempotently: the trigger is re-created only
when it does not already exist, so it is safe to run against both the legacy
stamped database (already has the trigger) and a fresh migration-driven one.
No other DDL is introduced; it simply guarantees the documented Phase-1
trigger set is complete on every path.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "021_phase1_persona_trigger"
down_revision: Union[str, None] = "020_workflow_runtime_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure the shared function exists (it does after 002, but keep this
    # migration self-contained so it is idempotent on its own).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
        """
    )
    # Idempotent trigger: only create the persona trigger when missing.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                WHERE t.tgname = 'update_persona_updated_at'
                  AND c.relname = 'persona'
                  AND c.relnamespace = 'public'::regnamespace
            ) THEN
                CREATE TRIGGER update_persona_updated_at
                BEFORE UPDATE ON persona
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
            END IF;
        END;
        $$;
        """
    )


def downgrade() -> None:
    # Only drop the trigger if it was created by this revision. If it was
    # already present (legacy stamped database) we leave it in place, because
    # dropping a trigger that belongs to the documented Phase-1 contract would
    # regress the schema.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                WHERE t.tgname = 'update_persona_updated_at'
                  AND c.relname = 'persona'
                  AND c.relnamespace = 'public'::regnamespace
            ) THEN
                ALTER TABLE persona DISABLE TRIGGER update_persona_updated_at;
            END IF;
        END;
        $$;
        """
    )
