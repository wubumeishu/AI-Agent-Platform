"""Per-channel rate limiter — P5MSG-03.

Process-local sliding-window limiter keyed by channel-config id. V1 keeps it
in-memory because the platform has no Redis client wired yet (the SOUL lists
Redis in the stack but no dependency is declared in ``pyproject``); a
Redis-backed limiter is the Phase-5/6 upgrade path and is the *only* thing
that would need to change here.

Semantics
---------
* ``allow(key, limit_per_hour, now=None)`` — record one event under *key* and
  return ``True`` when the event count within the trailing window (the last
  ``limit_per_hour``-second-equivalent slot) is within *limit_per_hour*.

V1 window is a simple *per-hour* counter that rolls over on the hour, which is
deterministic and trivially testable:

    allow(key, limit) -> True   when the hour's counter is < limit
                            False otherwise

The limiter never raises and never leaks key material into logs.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _hour_bucket(ts: datetime) -> str:
    """Truncate to the start of the UTC hour; the rolling window key."""
    return ts.strftime("%Y-%m-%dT%H")


class ChannelRateLimiter:
    """Hourly-per-channel counter. Thread-safe (a lock guards the dict)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> (hour_bucket, count)
        self._counts: Dict[str, Tuple[str, int]] = {}

    def allow(self, key: str, limit_per_hour: int, now: Optional[datetime] = None) -> bool:
        """Record one event and report whether it is within the limit.

        When *limit_per_hour* is ``<= 0`` the channel is disabled for delivery
        and the call always returns ``False``.
        """
        if limit_per_hour is None or limit_per_hour <= 0:
            return False
        now = now or datetime.now(timezone.utc)
        bucket = _hour_bucket(now)
        with self._lock:
            stored_bucket, count = self._counts.get(key, (bucket, 0))
            # Hour rolled over -> reset the counter for the new bucket.
            if stored_bucket != bucket:
                count = 0
            if count < limit_per_hour:
                self._counts[key] = (bucket, count + 1)
                return True
            # At/over the limit: do NOT increment (the limit is a hard cap,
            # and a denied event is not a "used" slot).
            logger.info(
                "rate_limit: key=%s denied at %d/h", key, limit_per_hour,
            )
            return False

    def used(self, key: str, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            bucket = _hour_bucket(now)
            stored_bucket, count = self._counts.get(key, (bucket, 0))
            return 0 if stored_bucket != bucket else count

    def reset(self) -> None:
        """Test helper: clear all counters."""
        with self._lock:
            self._counts.clear()


# Module-level default limiter (one per process). Tests that need isolation
# build their own ``ChannelRateLimiter()`` instance and inject it.
_default_limiter = ChannelRateLimiter()


def get_rate_limiter() -> ChannelRateLimiter:
    return _default_limiter
