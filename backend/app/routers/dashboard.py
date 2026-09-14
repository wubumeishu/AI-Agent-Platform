"""Dashboard overview router (Phase 6 / P6AN-02).

    GET /api/v1/analytics/dashboard/overview

Query parameters:
    * ``time_range_start`` / ``time_range_end`` (ISO 8601, UTC or offset-aware)
      and/or ``days`` (default 30, clamped 1..365) — the aggregation window.
      An explicit range wins over ``days``; at least one window argument must
      produce start < end (400 otherwise).
    * ``agent_id`` — scope conversations/leads to the agent's customers and
      channel messages to the agent (the "Agent dimension filter").
    * ``channel`` — restrict conversation + channel-message counts to one
      channel value (``web`` / ``wechat`` / ``douyin`` / ``xiaohongshu`` / …).

Response caching: the computed payload is served from the dashboard response
cache (Redis when ``DASHBOARD_CACHE_URL`` / ``REDIS_URL`` is configured,
in-memory TTL fallback otherwise) for 5 minutes. The ``cached`` flag in the
response is stamped by the server at serve time.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.dashboard import DashboardOverviewResponse
from app.services.dashboard_cache import (
    build_cache_key,
    DEFAULT_TTL_SECONDS,
    get_dashboard_cache,
)
from app.services.dashboard_service import DashboardOverviewService

router = APIRouter(prefix="/api/v1/analytics/dashboard", tags=["Analytics Dashboard"])


def _parse_moment(value: str, field: str) -> datetime:
    """Parse an ISO-8601 timestamp (naive = UTC) into an aware datetime."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be an ISO 8601 timestamp (got {value!r})",
        ) from exc
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@router.get("/overview", response_model=DashboardOverviewResponse)
async def get_overview(
    time_range_start: Optional[str] = Query(
        None, description="Window start, ISO 8601 (naive = UTC). Exclusive upper-bound partner."
    ),
    time_range_end: Optional[str] = Query(
        None, description="Window end (exclusive), ISO 8601 (naive = UTC)"
    ),
    days: int = Query(
        30, ge=1, le=365, description="Window length in days when no explicit range is given"
    ),
    agent_id: Optional[UUID] = Query(
        None, description="Filter the Agent dimension to one agent"
    ),
    channel: Optional[str] = Query(
        None, max_length=50, description="Restrict conversation/message counts to one channel"
    ),
    db: AsyncSession = Depends(get_db),
):
    start = _parse_moment(time_range_start, "time_range_start") if time_range_start else None
    end = _parse_moment(time_range_end, "time_range_end") if time_range_end else None

    cache = get_dashboard_cache()
    key = build_cache_key(
        start.isoformat() if start else "",
        end.isoformat() if end else "",
        str(days),
        str(agent_id) if agent_id else None,
        channel,
    )
    cached_raw: Optional[str] = await cache.get(key)
    if cached_raw is not None:
        try:
            payload = DashboardOverviewResponse.model_validate_json(cached_raw)
        except Exception:  # noqa: BLE001 - corrupt cache entry: recompute
            payload = None
        if payload is not None:
            payload.cached = True
            payload.cache_ttl_seconds = DEFAULT_TTL_SECONDS
            return payload

    try:
        payload = await DashboardOverviewService(db).compute(
            start=start, end=end, days=days, agent_id=agent_id, channel=channel
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload.cached = False
    try:
        await cache.set(key, payload.model_dump_json())
    except Exception:  # noqa: BLE001 - caching is an optimization, never break reads
        pass
    return payload
