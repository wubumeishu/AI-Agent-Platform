"""Agent Performance analytics router (Phase 6 / P6AN-07).

Dedicated router for the agent-efficiency surface so the P6AN-07 diff stays
additive and out of the way of the moving P6AN-01/04 ``analytics.py``
(hotspot) file. All endpoints live under the card's required base path::

    GET /api/v1/analytics/agents/performance        leaderboard (sort + range + filters)
    GET /api/v1/analytics/agents/performance/metrics {agent_id}  single-agent KPI block

Metric caliber is documented in ``docs/ANALYTICS-AGENT-PERFORMANCE.md``; the
aggregations themselves live in :class:`AgentPerformanceService` (set-based
grouped SQL over the existing agent / conversation / message / lead tables).

Error semantics:
- 404 ``AgentNotFoundError`` — the referenced agent does not exist / is soft-deleted.
- 422 ``InvalidRangeError`` — unknown ``range`` / ``sort`` / ``order`` value, or an
  unparseable explicit ``since`` / ``until``.
- An agent with no data is **not** an error: it returns a zeroed metric block.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.agent_performance import (
    AgentPerformanceLeaderboardResponse,
    AgentPerformanceResponse,
    LEADERBOARD_ORDERS,
    LEADERBOARD_SORT_KEYS,
)
from app.security.analytics_access import require_analytics_read
from app.security.jwt_auth import PrivateDomainPrincipal
from app.services.agent_performance_service import (
    AgentNotFoundError,
    AgentPerformanceService,
    InvalidRangeError,
    VALID_RANGES,
)

router = APIRouter(prefix="/api/v1/analytics/agents", tags=["Analytics Agents"])


def _range_values() -> list[str]:
    return list(VALID_RANGES)


@router.get(
    "/performance",
    response_model=AgentPerformanceLeaderboardResponse,
    summary="P6AN-07: agent leaderboard (ranked by a configurable key + time range)",
)
async def agent_performance_leaderboard(
    range: str = Query("30d", description="Time window preset: one of "
                       + ", ".join(_range_values())
                       + ". 'all' = no window (full history)."),
    since: Optional[str] = Query(
        None,
        description="Optional ISO-8601 start bound that overrides the range's start "
                    "(aware or naive-UTC). Must be <= until when both are given.",
    ),
    until: Optional[str] = Query(
        None,
        description="Optional ISO-8601 end bound that overrides the range's end.",
    ),
    sort: str = Query("conversations", description="Sort key: one of "
                     + ", ".join(LEADERBOARD_SORT_KEYS)
                     + ". 'activity' = conversations + messages."),
    order: str = Query("desc", description="Sort direction: 'asc' or 'desc'."),
    status: Optional[str] = Query(None, max_length=20,
                                  description="Filter to agents with this status "
                                             "(active / inactive / paused)."),
    name: Optional[str] = Query(None, max_length=100,
                                description="Fuzzy match on agent name."),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = Depends(require_analytics_read),
):
    """Ranked agent leaderboard.

    Every live agent matching the filters is returned (zeroed when it has no
    data), ordered by ``sort`` (direction ``order``) with a deterministic
    name/created_at tie-break, then paged. Rates substitute 0.0 when null so
    ordering never crashes.

    P6AN-16: the leaderboard is scoped to the caller's tenant — a tenant sees
    only its own agents' KPIs; a platform-wide actor (elevated role) sees the
    whole platform.
    """
    svc = AgentPerformanceService(db)
    try:
        since_dt, until_dt = _parse_bounds(since, until)
        return await svc.leaderboard(
            range_=range,
            since=since_dt,
            until=until_dt,
            sort_key=sort,
            order=order,
            status=status,
            name=name,
            page=page,
            page_size=page_size,
            account_id=principal.account_id,
        )
    except InvalidRangeError as e:
        raise HTTPException(status_code=422, detail=e.detail) from e


@router.get(
    "/performance/metrics/{agent_id}",
    response_model=AgentPerformanceResponse,
    summary="P6AN-07: single agent KPI block",
)
async def agent_performance_single(
    agent_id: UUID,
    range: str = Query("30d", description="Time window preset: one of "
                       + ", ".join(_range_values())
                       + ". 'all' = no window (full history)."),
    since: Optional[str] = Query(None, description="Optional ISO-8601 start bound override."),
    until: Optional[str] = Query(None, description="Optional ISO-8601 end bound override."),
    db: AsyncSession = Depends(get_db),
    principal: PrivateDomainPrincipal = Depends(require_analytics_read),
):
    """One agent's KPI block. 404 if the agent does not exist; zeroed block if
    it has no data (never an error).

    P6AN-16: the agent must belong to the caller's tenant — an out-of-tenant
    agent id is a 404 (AgentNotFoundError), never a cross-tenant leak.
    """
    svc = AgentPerformanceService(db)
    try:
        since_dt, until_dt = _parse_bounds(since, until)
        return await svc.single(
            agent_id, range_=range, since=since_dt, until=until_dt,
            account_id=principal.account_id,
        )
    except AgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidRangeError as e:
        raise HTTPException(status_code=422, detail=e.detail) from e


def _parse_bounds(since: Optional[str], until: Optional[str]) -> tuple:
    """Parse optional ISO-8601 bounds.

    A well-formed bound becomes a ``datetime`` (naive is fine — the service
    normalizes it to aware-UTC). An empty string is treated as "not provided".
    A malformed value raises :class:`InvalidRangeError`, which the router maps
    to HTTP 422 (it must never leak through as a 500).
    """
    from datetime import datetime

    def _p(name: str, v: Optional[str]) -> Optional[datetime]:
        if v is None or v == "":
            return None
        try:
            return datetime.fromisoformat(v)
        except ValueError as exc:
            raise InvalidRangeError(
                f"Invalid {name} {v!r}: expected an ISO-8601 timestamp."
            ) from exc

    return _p("since", since), _p("until", until)
