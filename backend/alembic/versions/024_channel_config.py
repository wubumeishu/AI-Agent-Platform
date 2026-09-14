"""Channel delivery configuration schema (P5MSG-03).

Revision ID: 024_channel_config
Revises: 023_messages_receipt
Create Date: 2026-09-14

Introduces the ``channel_config`` table — the P5MSG-03 delivery *configuration*
layer for the channel adapter: channel type, account binding, per-channel rate
limit and retry strategy. Sits alongside P5MSG-01's ``messages`` delivery-record
table; one row here is the *config* a delivery (send/receive/poll) consults,
while ``messages`` rows are the actual delivery records produced.

Columns:
    id, channel, type (messaging/comment/web), platform_code,
    account_id (FK -> account.id, SET NULL, nullable),
    rate_limit_per_hour, retry_max_attempts, retry_backoff_seconds,
    enabled, created_at, updated_at, is_deleted

Design notes:
  * ``account_id`` is SET-NULL + nullable: a channel can be configured before
    an account is attached, and delivery config outlives account deletion.
  * ``platform_code`` is a soft String reference (not an FK to ``platform``):
    P5MSG-03 must not couple delivery config to the Phase-1 Platform registry
    with a hard FK.
  * The partial unique index (channel, account_id, platform_code) with
    ``WHERE account_id IS NOT NULL AND is_deleted = false`` guarantees at most
    one live config per (channel, account, platform) without forbidding
    multiple account-less (NULL-account) configs.
  * Idempotent DDL (column / index existence pre-checks) so the migration is
    safe against both the legacy stamped database and a fresh one, matching the
    019_linearize_heads / 023_messages_receipt precedent.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "024_channel_config"
down_revision: Union[str, None] = "023_messages_receipt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(bind)

    if not insp.has_table("channel_config"):
        op.create_table(
            "channel_config",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("channel", sa.String(length=50), nullable=False),
            sa.Column("type", sa.String(length=20), nullable=False,
                      server_default="messaging"),
            sa.Column("platform_code", sa.String(length=50), nullable=True),
            sa.Column("account_id", sa.Uuid(), nullable=True),
            sa.Column("rate_limit_per_hour", sa.Integer(), nullable=False,
                      server_default="60"),
            sa.Column("retry_max_attempts", sa.Integer(), nullable=False,
                      server_default="3"),
            sa.Column("retry_backoff_seconds", sa.Integer(), nullable=False,
                      server_default="5"),
            sa.Column("enabled", sa.Boolean(), nullable=False,
                      server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False,
                      server_default="false"),
            sa.ForeignKeyConstraint(["account_id"], ["account.id"],
                                    ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    # Idempotent indexes: only create the ones that do not yet exist.
    existing_indexes = {ix["name"] for ix in insp.get_indexes("channel_config")} \
        if insp.has_table("channel_config") else set()
    existing_indexed_cols = set()
    for ix in insp.get_indexes("channel_config"):
        existing_indexed_cols.add(tuple(ix["column_names"]))

    if "idx_channel_config_channel" not in existing_indexes:
        op.create_index("idx_channel_config_channel", "channel_config", ["channel"])
    if "idx_channel_config_account" not in existing_indexes:
        op.create_index("idx_channel_config_account", "channel_config", ["account_id"])
    # Unique (channel, account_id, platform_code) on live account-bound rows.
    if "uq_channel_config_channel_account_platform" not in existing_indexes:
        op.create_index(
            "uq_channel_config_channel_account_platform",
            "channel_config",
            ["channel", "account_id", "platform_code"],
            unique=True,
            postgresql_where=(
                "account_id IS NOT NULL AND is_deleted = false"
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(bind)
    if not insp.has_table("channel_config"):
        return
    for ix in ("uq_channel_config_channel_account_platform",
               "idx_channel_config_account", "idx_channel_config_channel"):
        existing = {i["name"] for i in insp.get_indexes("channel_config")}
        if ix in existing:
            op.drop_index(ix, table_name="channel_config")
    op.drop_table("channel_config")
