"""Next-fire computation for WorkflowScheduler entities (t_wf_003).

Pure functions - no DB, no I/O - so accuracy is trivially unit-testable:

- cron:     evaluated on wall-clock components in the scheduler's timezone
            (via zoneinfo), results converted back to UTC for storage.
- interval: rolling semantics - next fire = reference + N seconds, where
            reference = max(now, last_run) so an engine miss does NOT trigger
            a backlog catch-up run (single-node V1 behaviour).

All stored timestamps are timezone-aware UTC. The <1s accuracy requirement
is met structurally: cron fires land exactly on minute (or second, for
6-field) boundaries; interval fires land exactly on reference + N seconds.
The engine tick granularity is what bounds *firing* error, not these
functions.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.db.models.workflow_runtime import WorkflowScheduler, SCHEDULE_TYPES
from app.services.scheduler.cron_parser import (
    CronParseError,
    compute_next_cron_time,
    parse_cron,
)

__all__ = ["ScheduleConfigError", "compute_next_fire"]


class ScheduleConfigError(ValueError):
    """Scheduler entity configuration is invalid for next-fire computation."""


def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize a stored/naive datetime to aware-UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _scheduler_timezone(sched: WorkflowScheduler) -> ZoneInfo:
    tz_name = getattr(sched, "timezone", None) or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception as exc:  # ZoneInfoNotFoundError etc.
        raise ScheduleConfigError(f"unknown timezone {tz_name!r}: {exc}") from exc


def compute_next_fire(
    sched: WorkflowScheduler,
    after: datetime,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    """Compute the next fire time (aware UTC) for a scheduler entity.

    Args:
        sched: scheduler row (schedule_type + cron_expression / interval_seconds).
        after: reference moment. cron mode = strictly-after window start;
               interval mode = the ``now`` reference (when ``now`` is omitted).
        now:   explicit reference time for interval mode (for testability).

    Returns:
        aware-UTC datetime, or None when no fire exists within the horizon
        (e.g. impossible cron such as "0 0 31 2 *").

    Raises:
        ScheduleConfigError: bad schedule_type, missing/invalid cron
        expression, or non-positive interval.
    """
    utc_after = _to_utc(after)
    if utc_after is None:
        raise ScheduleConfigError("after must not be None")

    if sched.schedule_type == "cron":
        if not sched.cron_expression:
            raise ScheduleConfigError(
                f"scheduler {getattr(sched, 'id', '?')} has schedule_type=cron "
                "but no cron_expression"
            )
        try:
            spec = parse_cron(sched.cron_expression)
        except CronParseError as exc:
            raise ScheduleConfigError(f"invalid cron expression: {exc}") from exc
        local_after = utc_after.astimezone(_scheduler_timezone(sched))
        local_next = compute_next_cron_time(spec, local_after)
        if local_next is None:
            return None
        return local_next.astimezone(timezone.utc)

    if sched.schedule_type == "interval":
        if sched.interval_seconds is None or sched.interval_seconds <= 0:
            raise ScheduleConfigError(
                f"scheduler {getattr(sched, 'id', '?')} has schedule_type=interval "
                "but interval_seconds missing or <= 0"
            )
        utc_now = _to_utc(now) or _to_utc(after) or datetime.now(timezone.utc)
        last_run = _to_utc(getattr(sched, "last_run_at", None))
        base = max(utc_now, last_run) if last_run is not None else utc_now
        return base + timedelta(seconds=sched.interval_seconds)

    raise ScheduleConfigError(
        f"unsupported schedule_type {sched.schedule_type!r} "
        f"(expected one of {SCHEDULE_TYPES})"
    )
