"""Sensitive-operation audit logging (P1-1, PIPL / GDPR).

Writes an :class:`AuditLog` row for each sensitive create / update / delete on
the private-domain surface. The audit row stores *which* resource and *who*
did it (principal + account), never the PII value itself — that would defeat
the protection. PII that *does* need to be referenced (e.g. a customer id) is
stored as an opaque id, not the value.

The helper :func:`record_audit` is best-effort: an audit-write failure must
never take down the business operation that triggered it, so exceptions are
logged and swallowed (but loudly), and the write participates in the caller's
session (no separate commit) so it rolls back together with the operation.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Sensitive operation kinds.
OP_CREATE = "create"
OP_UPDATE = "update"
OP_DELETE = "delete"
OP_READ = "read"
OP_TRANSITION = "transition"


async def record_audit(
    db: AsyncSession,
    *,
    account_id: UUID,
    principal: str,
    resource_type: str,
    operation: str,
    resource_id: Optional[UUID] = None,
    action: Optional[str] = None,
    detail: Optional[dict] = None,
) -> Optional[Any]:
    """Record a sensitive private-domain operation to the audit log.

    ``detail`` is a small dict of non-PII context only (ids, old/new status).
    Never pass raw PII / secrets into ``detail`` — see
    :func:`app.security.masking.sanitize_log_data` for scrubbing when needed.
    """
    from app.db.models.audit_log import AuditLog

    try:
        log = AuditLog(
            account_id=account_id,
            principal=principal,
            resource_type=resource_type,
            operation=operation,
            resource_id=resource_id,
            action=action,
            detail=detail or {},
        )
        db.add(log)
        await db.flush()  # persist within the caller's transaction (rolls back with it)
        return log
    except Exception as exc:  # noqa: BLE001 - audit must not break the op
        logger.error(
            "audit-log write failed (op=%s resource=%s.%s): %s",
            operation,
            resource_type,
            resource_id,
            exc,
        )
        return None


__all__ = [
    "record_audit",
    "OP_CREATE",
    "OP_UPDATE",
    "OP_DELETE",
    "OP_READ",
    "OP_TRANSITION",
]
