"""Lead conversation-source dedup index (Phase 3 CRM / t_crm_007).

Revision ID: 022_lead_conversation_dedup_index
Revises: 021_phase1_persona_trigger
Create Date: 2026-09-14

The CRM + Conversation integration (t_crm_007) creates a Lead from a
high-intent conversation and detects *duplicate* Leads for the same
customer (auto path) and the same conversation (both paths). Those checks
run on the ``lead`` table filtered by:

    source_type = 'conversation' AND is_deleted = false
    -- (+ customer_id for the customer-level dedup, + source_id for the
       per-conversation dedup)

This revision adds a **non-unique partial index** that turns those scans
into index lookups:

    idx_lead_conversation_source
        ON lead (customer_id, source_id)
        WHERE source_type = 'conversation' AND is_deleted = false

Design notes
------------
- **Non-unique, on purpose.** The duplicate-lead guarantee is enforced in
  the application layer (``create_lead_from_conversation`` + the
  ConversationLeadBridge auto path + ``check_duplicate_lead_for_customer``),
  not by the database. A hard UNIQUE constraint would be *over-restrictive
  and blocking*: an operator may intentionally create a second
  conversation-source Lead for the same customer via the manual
  ``from-conversation`` trigger (human override of auto-dedup), and the
  ``auto-generate`` batch backfill creates one Lead per high-intent
  conversation. A DB UNIQUE(customer_id) would turn those legitimate
  writes into IntegrityErrors — violating the "no blocking runtime errors"
  acceptance criterion. So the database guarantees *only performance*
  (a fast dedup scan); the *semantics* of dedup stay a deliberate business
  rule in the service, where they are observable, testable and overridable.
- **Idempotent / safe on legacy DBs.** Follows the 016/020 precedent:
  ``if_not_exists=True`` so the index is created only when absent. The
  ``lead`` table itself already exists on every current path (created by
  the CRM entity migration), so this revision is a pure index addition.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "022_lead_conversation_dedup_index"
down_revision: Union[str, None] = "021_phase1_persona_trigger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_lead_conversation_source",
        "lead",
        ["customer_id", "source_id"],
        unique=False,
        postgresql_where=sa.text(
            "source_type = 'conversation' AND is_deleted = false"
        ),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_lead_conversation_source",
        table_name="lead",
        if_exists=True,
    )
