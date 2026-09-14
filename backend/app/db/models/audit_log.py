"""Audit log model for sensitive private-domain operations (P1-1, PIPL/GDPR).

The :class:`AuditLog` table records *who* did *what* to *which* resource, so a
sensitive create / update / delete is attributable. It intentionally stores
only opaque identifiers (account, principal, resource id, old/new status) —
never raw PII or credentials, so the audit trail itself cannot become a new
leak. Writes are best-effort and ride the caller's transaction (see
:func:`app.security.audit.record_audit`), so a failed business op rolls back its
audit row with it.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    String,
    Text,
    Boolean,
    DateTime,
    JSON,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from .base import Base


class AuditLog(Base):
    """A single sensitive private-domain operation record."""

    __tablename__ = "audit_log"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    #: Owning account the operation targeted (tenant boundary).
    account_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    #: Authenticated identity that performed the operation (token ``sub``).
    principal = Column(String(200), nullable=False)
    #: Resource kind, e.g. "private_channel", "nurture_plan", "customer_segment".
    resource_type = Column(String(50), nullable=False)
    #: Operation kind: create | update | delete | read | transition.
    operation = Column(String(20), nullable=False)
    #: The resource acted upon (opaque id, not the PII value).
    resource_id = Column(PGUUID(as_uuid=True), nullable=True)
    #: A short action label, e.g. a status transition "open->won".
    action = Column(String(100), nullable=True)
    #: Non-PII context only (ids, old/new status). PII/secrets are never stored.
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_audit_log_account", "account_id", "created_at"),
        Index("idx_audit_log_resource", "resource_type", "resource_id"),
    )

    def __repr__(self):
        return (
            f"<AuditLog(account={self.account_id}, {self.operation} "
            f"{self.resource_type} {self.resource_id})>"
        )
