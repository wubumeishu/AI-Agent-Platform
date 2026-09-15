"""Private-Domain Conversion analytics endpoint (Phase 6 / P6AN-06).

Single read-only endpoint::

    GET /api/v1/analytics/private-domain/conversion

    ?agent_id=<uuid>&account_id=<uuid>&since=<iso8601>&until=<iso8601>

Computes the private-domain customer funnel (reach -> interact -> convert),
the LTV proxy, and the NurturePlan / FollowUpTask completion rates that
P6AN-09 (ROI) consumes.

The router self-carries its full ``/api/v1/analytics/private-domain`` prefix
and is therefore mounted BARE in ``main.py`` (same convention as the P6AN-01
analytics router and the AI-tier routers — mounting it under an outer
``/api/v1`` would double the prefix, the same class of defect as the P1-2 CRM
bug). It rides on the P6AN-01 analytics surface but is a separate module so
the CRUD definitions layer and this computation layer stay decoupled.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.private_domain_conversion import PDCResponse
from app.security.analytics_access import (
    resolve_account_param,
    require_analytics_read,
)
from app.security.jwt_auth import (
    AccountOwnershipError,
    PrivateDomainPrincipal,
)
from app.services.private_domain_conversion import PrivateDomainConversionService

router = APIRouter(
    prefix="/api/v1/analytics/private-domain",
    tags=["Analytics - Private Domain Conversion"],
)


def _parse_window_bound(name: str, value: Optional[str]) -> Optional[datetime]:
    """Parse an optional ISO-8601 window bound into an aware/naive datetime.

    A malformed value is a clean 422 (not a mid-DB-call 500). A trailing
    ``Z`` is normalised to ``+00:00`` for ``fromisoformat``. Naive values are
    treated as UTC downstream by the service's window resolution.
    """
    if value is None or value.strip() == "":
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid ISO-8601 timestamp {value!r} for the time window "
                f"(expected e.g. 2026-08-01T00:00:00Z)."
            ),
        )


@router.get("/conversion", response_model=PDCResponse)
async def get_private_domain_conversion(
    agent_id: Optional[UUID] = Query(
        None,
        description="Scope the customer funnel + LTV + follow-up to customers "
                    "bound to this agent (agent_customer_binding). Omit for all.",
    ),
    account_id: Optional[UUID] = Query(
        None,
        description="Scope account-owned sources (messages / deals / follow-ups "
                    "/ nurture executions) to one account. Omit for all. "
                    "P6AN-16: for a tenant this is forced to the caller's own "
                    "account (the token's account_id); a different id is a 403.",
    ),
    since: Optional[str] = Query(
        None,
        description="UTC window start, inclusive (ISO-8601, e.g. 2026-08-01T00:00:00Z). "
                    "If omitted, the window defaults to the last 30 days.",
    ),
    until: Optional[str] = Query(
        None,
        description="UTC window end, exclusive (ISO-8601). If omitted, the window "
                    "defaults to the last 30 days.",
    ),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = Depends(require_analytics_read),
):
    """Compute the private-domain conversion funnel + LTV proxy + completion rates.

    Read-only: aggregates Phase-5 private-domain source tables (messages,
    conversation, deal_item, nurture_step_execution, follow_up_task). No write,
    no new table — the data口径 is documented in
    ``docs/P6AN-06-private-domain-conversion-api.md``.

    P6AN-16: scoped to the caller's tenant. The ``account_id`` is authoritative
    from the token; a tenant that passes another account's id gets a 403
    (cross-tenant read attempt), and a plain tenant operator is restricted to
    its own account's data.
    """
    since_dt = _parse_window_bound("since", since)
    until_dt = _parse_window_bound("until", until)

    # P6AN-16: resolve the authoritative account scope from the token. A tenant
    # may only scope to its own account; a cross-tenant param raises
    # AccountOwnershipError (403). Map it locally so standalone / test apps
    # (without main.py's global handler) also return a 403, never a 500.
    try:
        tenant_account = resolve_account_param(account_id, principal)
    except AccountOwnershipError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": 403, "message": str(exc), "data": None},
        ) from exc

    svc = PrivateDomainConversionService(db)
    # P6AN-16: the service scopes account-owned source rows to ``tenant_account``
    # and, when an agent_id is supplied alongside a tenant, restricts the agent
    # dimension to the tenant's own agents (no cross-tenant agent data).
    return await svc.get_conversion(
        agent_id=agent_id,
        account_id=tenant_account,
        since=since_dt,
        until=until_dt,
    )
