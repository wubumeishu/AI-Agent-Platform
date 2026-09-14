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
                    "/ nurture executions) to one account. Omit for all.",
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
):
    """Compute the private-domain conversion funnel + LTV proxy + completion rates.

    Read-only: aggregates Phase-5 private-domain source tables (messages,
    conversation, deal_item, nurture_step_execution, follow_up_task). No write,
    no new table — the data口径 is documented in
    ``docs/P6AN-06-private-domain-conversion-api.md``.
    """
    since_dt = _parse_window_bound("since", since)
    until_dt = _parse_window_bound("until", until)

    svc = PrivateDomainConversionService(db)
    return await svc.get_conversion(
        agent_id=agent_id,
        account_id=account_id,
        since=since_dt,
        until=until_dt,
    )
