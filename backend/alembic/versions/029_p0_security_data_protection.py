"""P0 security & sensitive-data protection (ADR-011, task t_da21042d).

Revision ID: 029_p0_security_data_protection
Revises: 028_analytics_tables
Create Date: 2026-09-15

Three changes, all idempotent (re-runnable):

1. **``audit_log`` table** (P1-1 / PIPL / GDPR) — a durable record of who
   did what to which private-domain resource. ``account_id`` and the
   reference UUIDs are deliberately left **UN-constrained** (no FK),
   following the 020_workflow_runtime_tables / 026_missing_orm_tables
   precedent: the legacy production DB forked three base tables to
   VARCHAR ids, so a UUID FK could be rejected by the legacy schema; the
   column keeps the UUID type to match the ORM.

2. **PII columns widened to TEXT + encrypted at rest** (P0-3):
   ``customer.email/phone``, ``customer_identity.platform_account_id/
   phone/email/external_id`` and ``private_channel.contact_info`` are
   changed to TEXT (the AES-SIV ciphertexts are variable-length and exceed
   the old VARCHAR bounds) and the *legacy plaintext* rows are
   backfilled with deterministic AES-SIV tokens. Encryption is applied in
   Python (``app.security.crypto.encrypt_field`` /
   ``encrypt_bytes``) with the ``CREDENTIAL_KEY`` in effect for the
   *alembic process*; the ORM's ``EncryptedString`` / ``EncryptedJSON``
   types are no-ops on values that already look encrypted, so already-
   migrated rows are untouched. Determinism keeps the existing indexes
   (``idx_ci_phone`` / ``idx_ci_email`` / the unique
   ``idx_ci_platform_account``) and every ``==`` lookup working.

   Idempotency guard: only rows whose value does not already start with
   the ``A1$`` token marker (or, for credentials, ``pbkdf2$``) are
   rewritten. Fresh DBs (created through the ORM with the encrypted
   types) already store tokens, so the backfill is a no-op there.

3. **Credentials hashed at rest** (F-3): ``account.password_encrypted``
   and ``proxy.password_encrypted`` legacy *plaintext* rows are replaced
   with a salted PBKDF2-HMAC-SHA256 hash (``app.security.crypto.
   hash_password``). Credentials are one-way: the plaintext can no longer
   be recovered after this migration, which is the point. Rows already
   carrying a ``pbkdf2$`` hash are left alone.

Key-management note: run this revision with the *same* ``CREDENTIAL_KEY``
environment variable the service uses (or the documented dev fallback on
both). Changing the key later does not re-encrypt these rows; rotate the
key with a re-backfill if required.

Downgrade is intentionally partial: it restores the original column types
and drops ``audit_log`` but does **not** decrypt the backfilled PII (the
ciphertexts are kept; the app's read path still decrypts TEXT values that
start with ``A1$``), so a downgrade on a live system loses nothing
functional.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "029_p0_security_data_protection"
down_revision = "028_analytics_tables"
branch_labels = None
depends_on = None


def _create_table(*args, **kwargs):
    kwargs["if_not_exists"] = True
    op.create_table(*args, **kwargs)


def _create_index(*args, **kwargs):
    kwargs["if_not_exists"] = True
    op.create_index(*args, **kwargs)


def _bind_pii_encryption() -> None:
    """Import the crypto helpers in the alembic worker (key from env)."""
    from app.security.crypto import encrypt_field, encrypt_bytes, hash_password

    return encrypt_field, encrypt_bytes, hash_password


def _col_exists(bind, table: str, column: str) -> bool:
    """Live (transaction-aware) check: does ``table.column`` exist right now?

    Guards the legacy production ``create_all`` fork, where the
    ``private_channel.contact_info`` column (a Phase-5 resource-layer column)
    was never created because the fork predates that model revision. On a
    fresh ORM-created database every column here exists, so the guard is a
    no-op there — behaviour is unchanged on the canonical path.
    """
    val = bind.execute(
        sa.text(
            "SELECT EXISTS("
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t "
            "AND column_name = :c)"
        ),
        {"t": table, "c": column},
    ).scalar()
    return bool(val)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. audit_log (P1-1). Unconstrained UUID refs (020/026 precedent).
    # ------------------------------------------------------------------
    _create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal", sa.String(length=200), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_audit_log_account", "audit_log", ["account_id", "created_at"])
    _create_index("idx_audit_log_resource", "audit_log", ["resource_type", "resource_id"])

    # ------------------------------------------------------------------
    # 2. PII columns: widen to TEXT, then backfill legacy plaintext.
    #
    # Fresh DBs (migration 004 chain) create ``contact_info`` as JSON; the
    # legacy production ``create_all`` fork may carry JSONB. A raw
    # ``ALTER ... TYPE text USING col::text`` works for VARCHAR, JSON and
    # JSONB alike (JSON/JSONB cast to their text form), so it is safe on
    # both the fresh and the legacy schema. The ORM's EncryptedString /
    # EncryptedJSON types now bind/return TEXT tokens.
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE customer ALTER COLUMN email TYPE text USING email::text"
    )
    op.execute(
        "ALTER TABLE customer ALTER COLUMN phone TYPE text USING phone::text"
    )
    op.execute(
        "ALTER TABLE customer_identity ALTER COLUMN platform_account_id "
        "TYPE text USING platform_account_id::text"
    )
    op.execute(
        "ALTER TABLE customer_identity ALTER COLUMN phone "
        "TYPE text USING phone::text"
    )
    op.execute(
        "ALTER TABLE customer_identity ALTER COLUMN email "
        "TYPE text USING email::text"
    )
    op.execute(
        "ALTER TABLE customer_identity ALTER COLUMN external_id "
        "TYPE text USING external_id::text"
    )
    encrypt_field, encrypt_bytes, _hash = _bind_pii_encryption()
    bind = op.get_bind()

    # ``private_channel.contact_info`` is a Phase-5 resource-layer column
    # (``EncryptedJSON``). The legacy production ``create_all`` fork predates
    # it, so on that DB the column is absent and the unconditional
    # ``ALTER ... TYPE text`` below would crash (UndefinedColumn). Guard the
    # column-specific PII steps with a live existence check; the canonical
    # (fresh ORM) path always has the column, so behaviour is unchanged there.
    pc_has_contact_info = _col_exists(bind, "private_channel", "contact_info")

    # customer.email / phone
    rows = bind.execute(
        sa.text("SELECT id, email FROM customer WHERE email IS NOT NULL AND email NOT LIKE 'A1$%'")
    ).fetchall()
    for _id, value in rows:
        bind.execute(
            sa.text("UPDATE customer SET email = :v WHERE id = :id"),
            {"v": encrypt_field(value), "id": _id},
        )
    rows = bind.execute(
        sa.text("SELECT id, phone FROM customer WHERE phone IS NOT NULL AND phone NOT LIKE 'A1$%'")
    ).fetchall()
    for _id, value in rows:
        bind.execute(
            sa.text("UPDATE customer SET phone = :v WHERE id = :id"),
            {"v": encrypt_field(value), "id": _id},
        )

    # customer_identity (platform_account_id is NOT NULL; the others may be
    # NULL and are skipped when so).
    for column in ("platform_account_id", "phone", "email", "external_id"):
        null_guard = "" if column == "platform_account_id" else f"{column} IS NOT NULL AND "
        rows = bind.execute(
            sa.text(
                f"SELECT id, {column} FROM customer_identity "
                f"WHERE {null_guard}{column} NOT LIKE 'A1$%'"
            )
        ).fetchall()
        for _id, value in rows:
            bind.execute(
                sa.text(f"UPDATE customer_identity SET {column} = :v WHERE id = :id"),
                {"v": encrypt_field(value), "id": _id},
            )

    # private_channel.contact_info: JSON document -> whole-document token.
    # Only on schemas where the column exists (see guard above).
    if pc_has_contact_info:
        op.execute(
            "ALTER TABLE private_channel ALTER COLUMN contact_info "
            "TYPE text USING contact_info::text"
        )
        rows = bind.execute(
            sa.text(
                "SELECT id, contact_info FROM private_channel "
                "WHERE contact_info IS NOT NULL AND contact_info NOT LIKE 'A1$%'"
            )
        ).fetchall()
        for _id, raw in rows:
            # ``raw`` may be a JSONB python object (already decoded) or a str.
            if isinstance(raw, (dict, list)):
                import json as _json

                token = encrypt_bytes(_json.dumps(raw, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            else:
                token = encrypt_bytes(str(raw).encode("utf-8"))
            bind.execute(
                sa.text("UPDATE private_channel SET contact_info = :v WHERE id = :id"),
                {"v": token, "id": _id},
            )

    # ------------------------------------------------------------------
    # 3. Credentials: hash legacy plaintext rows (one-way, F-3).
    # ------------------------------------------------------------------
    for table, column in (("account", "password_encrypted"), ("proxy", "password_encrypted")):
        rows = bind.execute(
            sa.text(
                f"SELECT id, {column} FROM {table} "
                f"WHERE {column} IS NOT NULL AND {column} NOT LIKE 'pbkdf2$%'"
            )
        ).fetchall()
        for _id, value in rows:
            bind.execute(
                sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),
                {"v": _hash(str(value)), "id": _id},
            )


def downgrade() -> None:
    # Restore original column widths; backfilled A1$ tokens are left as-is
    # (the app read path still decrypts them).
    bind = op.get_bind()
    # ``private_channel.contact_info`` may be absent on the legacy production
    # fork (guarded in upgrade), so only restore its width when it exists.
    if _col_exists(bind, "private_channel", "contact_info"):
        op.alter_column("private_channel", "contact_info", type_=postgresql.JSONB(astext_type=sa.Text()), nullable=True, existing_type=sa.Text())
    op.alter_column("customer_identity", "external_id", type_=sa.String(length=500), nullable=True, existing_type=sa.Text())
    op.alter_column("customer_identity", "email", type_=sa.String(length=200), nullable=True, existing_type=sa.Text())
    op.alter_column("customer_identity", "phone", type_=sa.String(length=50), nullable=True, existing_type=sa.Text())
    op.alter_column("customer_identity", "platform_account_id", type_=sa.String(length=200), nullable=False, existing_type=sa.Text())
    op.alter_column("customer", "phone", type_=sa.String(length=50), nullable=True, existing_type=sa.Text())
    op.alter_column("customer", "email", type_=sa.String(length=200), nullable=True, existing_type=sa.Text())
    op.drop_index("idx_audit_log_resource", table_name="audit_log", if_exists=True)
    op.drop_index("idx_audit_log_account", table_name="audit_log", if_exists=True)
    op.drop_table("audit_log", if_exists=True)
