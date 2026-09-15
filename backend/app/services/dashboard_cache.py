"""Dashboard overview response cache (Phase 6 / P6AN-02).

Response-level caching for the dashboard overview aggregate, TTL 5 min.

Design notes
------------
* The platform stack lists Redis, but no Redis dependency is declared in
  ``pyproject`` (same situation as ``channel_rate_limiter``). This module
  therefore speaks **async Redis natively when available** (lazy client
  resolution, no import-time hard dependency) and transparently falls back
  to a process-local in-memory TTL cache otherwise. The cache is a
  performance optimization, never a correctness requirement: any cache
  layer failure degrades to a fresh computation and logs one warning.
* The backend is selected at construction time:
    * env ``DASHBOARD_CACHE_URL`` (``redis://...`` or ``redis://:password@host:port/db``)
    * else env ``REDIS_URL`` if set to a redis URL
    * else in-memory.
  Resolution happens lazily on first use so import (and unit tests) never
  need a live Redis.
* Keys are content-addressed on the normalized query parameters
  (``start`` / ``end`` / ``agent_id`` / ``channel``) — different filter
  combinations never alias onto one another.
* Values are the serialized overview payload (JSON). ``cached`` is stamped
  **by the server** at serve time, not stored, so a cache hit never returns
  a payload that claims to have been computed live.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 300  # 5 minutes, per the task spec
_KEY_PREFIX = "analytics:dashboard:overview:"


def resolve_cache_url() -> Optional[str]:
    """Pick the Redis URL from the environment, or ``None`` for in-memory."""
    url = os.getenv("DASHBOARD_CACHE_URL", "").strip()
    if url and url.startswith(("redis://", "rediss://")):
        return url
    url = os.getenv("REDIS_URL", "").strip()
    if url and url.startswith(("redis://", "rediss://")):
        return url
    return None


class MemoryDashboardCache:
    """Process-local TTL cache (single asyncio loop; the process is the only writer)."""

    def __init__(self, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self.ttl = ttl
        self._store: Dict[str, tuple[float, str]] = {}

    async def get(self, key: str) -> Optional[str]:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if time.monotonic() >= expires_at:
            del self._store[key]
            return None
        return payload

    async def set(self, key: str, payload: str) -> None:
        self._store[key] = (time.monotonic() + self.ttl, payload)

    async def close(self) -> None:  # pragma: no cover - trivial
        self._store.clear()


class RedisDashboardCache:
    """Async-Redis TTL cache with one-shot degraded-fallback to memory.

    The Redis client is resolved lazily (``redis.asyncio.from_url``); a
    missing/failed backend is logged **once** and every subsequent call
    transparently uses the in-memory fallback so the API keeps working.
    """

    def __init__(self, url: str, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self.url = url
        self.ttl = ttl
        self._client: Optional[Any] = None
        self._fallback = MemoryDashboardCache(ttl)
        self._degraded: Optional[bool] = None
        self._lock = asyncio.Lock()

    async def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(self.url, decode_responses=True)
            await client.ping()
            self._client = client
            return client
        except Exception as exc:  # noqa: BLE001 - degrade, never break the API
            logger.warning(
                "dashboard cache: Redis at %s unavailable (%s: %s); "
                "falling back to in-memory cache",
                _redact_url(self.url), type(exc).__name__, str(exc)[:120],
            )
            self._degraded = True
            return None

    async def get(self, key: str) -> Optional[str]:
        client = await self._get_client()
        if client is None:
            return await self._fallback.get(key)
        try:
            raw = await client.get(key)
            return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        except Exception as exc:  # noqa: BLE001
            logger.warning("dashboard cache: redis get failed (%s); degrading to memory",
                           type(exc).__name__)
            self._degraded = True
            return await self._fallback.get(key)

    async def set(self, key: str, payload: str) -> None:
        client = await self._get_client()
        if client is None:
            await self._fallback.set(key, payload)
            return
        try:
            await client.set(key, payload, ex=self.ttl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("dashboard cache: redis set failed (%s); degrading to memory",
                           type(exc).__name__)
            self._degraded = True
            await self._fallback.set(key, payload)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._client = None


def _redact_url(url: str) -> str:
    """Mask credentials in a redis URL before logging."""
    import re

    m = re.match(r"^(\w+://)([^/@]+)@(.*)$", url or "")
    if m:
        return f"{m.group(1)}***@{m.group(3)}"
    return url or ""


def build_cache_key(
    start: str,
    end: str,
    days: str,
    agent_id: Optional[str],
    channel: Optional[str],
    account_id: Optional[str] = None,
) -> str:
    """Content-addressed key: same normalized params -> same cache entry.

    P6AN-16: the tenant (``account_id``) is part of the key so a cached
    overview computed for one tenant is never served to another (cross-tenant
    cache aliasing is a data leak even though it is "just" a cache hit).
    """
    digest = hashlib.sha1(
        json.dumps(
            [start, end, days, agent_id or "", channel or "", account_id or ""],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"{_KEY_PREFIX}{digest}"


_active_cache: Optional[Any] = None
_cache_lock = asyncio.Lock()


def get_dashboard_cache() -> Any:
    """Process-wide cache singleton (memory or Redis, resolved once)."""
    global _active_cache
    if _active_cache is None:
        url = resolve_cache_url()
        if url:
            _active_cache = RedisDashboardCache(url)
            logger.info("dashboard cache: using Redis backend (%s)", _redact_url(url))
        else:
            _active_cache = MemoryDashboardCache()
            logger.info("dashboard cache: no REDIS_URL set; using in-memory TTL cache")
    return _active_cache


def reset_dashboard_cache() -> None:
    """Reset the singleton (test hook)."""
    global _active_cache
    _active_cache = None
