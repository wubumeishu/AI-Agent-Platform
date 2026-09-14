"""Linearize the Alembic history into a single head (merge, no DDL).

Revision ID: 019_linearize_heads
Revises: 002_add_platform, 006_agent_customer_binding, 006_content_usage,
         008_intent, 018_content_generation
Create Date: 2026-09-14

The workflow phase left several unmerged branch heads (each Phase 4 / earlier
card shipped an independent migration rather than chaining off the running
head). As of this revision the graph carries FIVE competing heads:

    - 002_add_platform        (stub-root chain: 001_initial -> 002_add_platform)
    - 006_agent_customer_binding (branch off 005_private_domain)
    - 006_content_usage       (branch off 005_private_domain)
    - 008_intent              (branch off 007_prompt_template)
    - 018_content_generation (already merges 016_scheduler_due_index +
                              016_workflow_task + 017_nurture_plan_item_is_deleted)

`alembic heads` therefore reported multiple heads and `alembic upgrade head`
failed with "Multiple head revisions are present".

This revision is a pure MERGE commit: it adds NO schema changes, it only
re-unifies every open branch into a single linear point so that the subsequent
020_workflow_runtime_tables can hang off a unique head. It is safe to run
(stamp or upgrade) on a live database because it executes no DDL.

Note: this merge does NOT attempt to repair the historical duplicate-table
creates (e.g. `platform` / `agent` created by both 002_account_resource_layer
and 002_add_platform). Those duplicate branches are only ever reached on a
FRESH database; production is a legacy out-of-band `create_all` database that
is stamped onto this head and only forward-receives 020.
"""
from alembic import op  # noqa: F401

# revision identifiers, used by Alembic.
revision = "019_linearize_heads"
# Merge revision: tie all five current heads into one.
down_revision = (
    "002_add_platform",
    "006_agent_customer_binding",
    "006_content_usage",
    "008_intent",
    "018_content_generation",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Pure merge: no schema changes. Any DDL that makes prod usable lives in
    # 020_workflow_runtime_tables.
    pass


def downgrade() -> None:
    # A merge has no DDL to undo; refusing keeps the graph honest.
    raise RuntimeError(
        "019_linearize_heads is a merge revision with no DDL; there is "
        "nothing to downgrade. To leave this node, drop it and re-run "
        "`alembic upgrade`/`stamp` on the branches instead."
    )
