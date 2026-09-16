"""Pure scheduling + step-sequencing core for the NurturePlan execution engine.

ADR-010 (Data/Execution Split) deferred this runtime. This module is the
*pure, provider/DB-agnostic* core - it contains no SQL and no FastAPI, so it
is trivially unit-testable and reproducible. It answers three questions:

1. **Is a plan due now?** - by ``schedule_type`` (fixed / drip / triggered),
   given its ``schedule_config``.
2. **When should each step fire?** - cumulative ``delay_hours`` sequencing so
   the run honours inter-step delays.
3. **What happens on a failed step?** - deterministic backoff + retry +
   dead-letter decision.

The DB adapter (:mod:`nurture_execution_service`) translates rows into the
plain-descriptor shape this module consumes and persists the results back.
Timezone policy: all aware datetimes are UTC; naive inputs are normalised to
UTC (the private_domain models now use aware-UTC
``datetime.now(timezone.utc)`` per ADR-019; the workflow engine
uses aware UTC - both are aware UTC now).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.db.models.private_domain import PlanStatus

# ---------- constants ----------

# schedule_type vocabulary (NurturePlan.schedule_type).
SCHEDULE_FIXED = "fixed"
SCHEDULE_DRIP = "drip"
SCHEDULE_TRIGGERED = "triggered"
VALID_SCHEDULE_TYPES = (SCHEDULE_FIXED, SCHEDULE_DRIP, SCHEDULE_TRIGGERED)

# Retry / backoff defaults (overridable per plan via schedule_config).
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE_SECONDS = 60.0  # 1m, 2m, 4m, ...
DEFAULT_BACKOFF_CAP_SECONDS = 3600.0  # cap a single gap at 1h

# A plan is "armed" for triggered scheduling when an event handler has set
# schedule_config["armed_at"]; the scheduler fires it once, at that time.
_ARMED = "armed_at"


def to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalise a datetime to aware-UTC (None passes through)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------- 1. is a plan due? ----------

def _parse_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 string / datetime to aware-UTC, else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_utc(value)
    if isinstance(value, str):
        try:
            return to_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def is_plan_due(plan: Dict[str, Any], now: datetime) -> bool:
    """Return whether ``plan`` should fire in this scheduler pass.

    ``plan`` is the plain descriptor produced by the adapter: it carries
    ``status``, ``schedule_type``, ``schedule_config`` and (for triggered
    plans) an ``armed`` flag + ``trigger_conditions``.

    Rules:
    - Only ACTIVE plans fire; everything else (draft/paused/...) is skipped.
    - **fixed**   -> due when ``now >= run_at`` and (if repeating) the
      configured interval has elapsed since ``last_run_at``.
    - **drip**    -> due when the plan has *pending work*: at least one step
      is still to fire (adapter sets ``pending_steps`` > 0) and now >= the
      earliest pending step's scheduled time.
    - **triggered** -> due only when explicitly ``armed`` (event-driven), or
      when a trigger condition already matches and ``auto_arm`` is on.
    """
    now = to_utc(now)
    if plan.get("status") != PlanStatus.ACTIVE.value:
        return False

    s_type = plan.get("schedule_type") or SCHEDULE_FIXED
    config = plan.get("schedule_config") or {}

    if s_type == SCHEDULE_FIXED:
        return _fixed_due(config, now)

    if s_type == SCHEDULE_DRIP:
        pending = config.get("pending_steps")
        earliest = _parse_iso(config.get("earliest_pending_at"))
        if pending:
            # drip runs until its steps are exhausted; due if any remain and
            # the earliest one is now (or overdue).
            return earliest is not None and now >= earliest
        return False

    if s_type == SCHEDULE_TRIGGERED:
        # Fired exactly when the event handler has armed it.
        armed_at = _parse_iso(config.get(_ARMED))
        if armed_at is not None:
            return now >= armed_at
        # auto_arm: trigger conditions already evaluated true by a poller.
        if config.get("auto_armed"):
            return True
        return False

    # Unknown schedule type: do not fire (fail-safe).
    return False


def _fixed_due(config: Dict[str, Any], now: datetime) -> bool:
    run_at = _parse_iso(config.get("run_at"))
    if run_at is not None and now < run_at:
        return False
    interval_h = config.get("interval_hours")
    if interval_h:
        last = _parse_iso(config.get("last_run_at"))
        if last is None:
            # first run: due when run_at has passed (or no run_at -> due now)
            return run_at is None or now >= run_at
        if run_at is not None and last < run_at:
            # never fired past its anchor yet
            return now >= run_at
        return (now - last) >= timedelta(hours=float(interval_h))
    # non-repeating fixed: due once, when now >= run_at (or no anchor)
    return run_at is None or now >= run_at


# ---------- 2. step sequencing (honour delay_hours) ----------

@dataclass
class ScheduledStep:
    """A step with its computed absolute fire time for one run."""

    step_id: Optional[str]
    step_order: int
    content_id: Optional[str]
    trigger_type: str
    delay_hours: int
    config: Dict[str, Any]
    scheduled_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_order": self.step_order,
            "content_id": self.content_id,
            "trigger_type": self.trigger_type,
            "delay_hours": self.delay_hours,
            "scheduled_at": self.scheduled_at.isoformat(),
        }


def sequence_steps(
    steps: List[Dict[str, Any]],
    run_started_at: datetime,
) -> List[ScheduledStep]:
    """Compute each step's absolute fire time for a single run.

    ``steps`` are ordered by ``step_order``. A step's fire time is the
    *previous* step's fire time + this step's ``delay_hours`` - i.e. delays
    are cumulative along the sequence (a 0-delay step fires back-to-back;
    a step that needs AI generation gets the gap its delay_hours declare).
    Steps with a non-time trigger type still get a scheduled slot so the run
    stays deterministic; an event trigger is satisfied when its own step is
    reached within the window.
    """
    run_started_at = to_utc(run_started_at) or datetime.now(timezone.utc)
    out: List[ScheduledStep] = []
    cursor = run_started_at
    ordered = sorted(
        steps,
        key=lambda s: (int(s.get("step_order") or 0), str(s.get("step_id") or "")),
    )
    for i, s in enumerate(ordered):
        delay_h = int(s.get("delay_hours") or 0)
        if delay_h < 0:
            delay_h = 0
        # The first step may carry its own offset from run start; subsequent
        # steps offset from the previous step's fire time.
        if i == 0:
            fire_at = cursor + timedelta(hours=delay_h)
        else:
            fire_at = cursor + timedelta(hours=delay_h)
        out.append(
            ScheduledStep(
                step_id=str(s.get("step_id")) if s.get("step_id") else None,
                step_order=int(s.get("step_order") or i),
                content_id=str(s.get("content_id")) if s.get("content_id") else None,
                trigger_type=str(s.get("trigger_type") or "time_based"),
                delay_hours=delay_h,
                config=dict(s.get("config") or {}),
                scheduled_at=fire_at,
            )
        )
        cursor = fire_at
    return out


def due_steps(scheduled: List[ScheduledStep], now: datetime) -> List[ScheduledStep]:
    """The steps that are due to fire at or before ``now`` (fire order)."""
    now = to_utc(now)
    return [s for s in scheduled if s.scheduled_at <= now]


# ---------- 3. retry / backoff / dead-letter ----------

def backoff_seconds(
    attempt: int,
    base: float = DEFAULT_BACKOFF_BASE_SECONDS,
    cap: float = DEFAULT_BACKOFF_CAP_SECONDS,
) -> float:
    """Exponential backoff delay after the ``attempt``-th failure.

    attempt is 1-based: after 1 failure wait base, after 2 wait base*2, ...
    capped at ``cap`` seconds. Deterministic (no jitter) so tests are stable.
    """
    if attempt < 1:
        attempt = 1
    return min(cap, base * (2 ** (attempt - 1)))


def should_retry(
    attempt: int,
    max_attempts: int,
) -> bool:
    """True if a failed attempt is eligible for another try."""
    return attempt < max_attempts


def step_terminal_status(
    attempt: int,
    max_attempts: int,
) -> str:
    """Decide the status to persist for a *failed* attempt.

    - ``"failed"`` when retries remain (the scheduler will re-queue it).
    - ``"dead_letter"`` when the attempt budget is exhausted (terminal;
      operator-inspectable, no automatic re-queue).
    """
    return "failed" if should_retry(attempt, max_attempts) else "dead_letter"


def is_recoverable(exc: BaseException) -> bool:
    """Heuristic: which errors are worth retrying.

    Transient errors (timeouts, provider hiccups, DB busy) retry; deterministic
    programming errors do not (they will keep failing and just burn attempts).
    """
    # Known-deterministic error classes: retrying a bad request / type bug /
    # constraint violation never succeeds. Dead-letter these immediately.
    non_transient_types = (
        TypeError,
        ValueError,
        KeyError,
        LookupError,
        AttributeError,
        NameError,
        NotImplementedError,
    )
    if isinstance(exc, non_transient_types) and not isinstance(exc, (EOFError, OSError)):
        return False
    name = type(exc).__name__.lower()
    transient_markers = (
        "timeout",
        "timedout",
        "connection",
        "connreset",
        "temporarily",
        "unavailable",
        "busy",
        "ratelimit",
        "429",
        "503",
        "502",
    )
    msg = str(exc).lower()
    for marker in transient_markers:
        if marker in name or marker in msg:
            return True
    # Unknown exception types: be conservative and allow ONE retry, then stop.
    return isinstance(exc, Exception)


# ---------- segment sync (TD-9, cheap driver) ----------

# Segment types that auto-sync members (manual is member-driven, not synced).
SYNC_SEGMENT_TYPES = ("automatic", "dynamic")
DEFAULT_SEGMENT_SYNC_INTERVAL_HOURS = 6.0


def segment_needs_sync(
    segment: Dict[str, Any],
    now: datetime,
    interval_hours: float = DEFAULT_SEGMENT_SYNC_INTERVAL_HOURS,
) -> bool:
    """A segment is due for a member-sync when it is automatic/dynamic AND its
    ``last_synced_at`` is older than the interval (or never synced)."""
    now = to_utc(now)
    if segment.get("segment_type") not in SYNC_SEGMENT_TYPES:
        return False
    last = _parse_iso(segment.get("last_synced_at"))
    if last is None:
        return True
    return (now - to_utc(last)) >= timedelta(hours=interval_hours)


def normalize_descriptor(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a raw ORM-ish row into the plain descriptor the engine consumes.

    Accepts both the ORM attribute values and the JSON schedule_config; keeps
    everything JSON-safe (UUIDs -> str, datetimes -> iso) so the pure core and
    the adapter never leak ORM identity into each other.
    """
    cfg = raw.get("schedule_config") or {}
    out: Dict[str, Any] = {
        "id": str(raw["id"]) if raw.get("id") else None,
        "status": raw.get("status"),
        "schedule_type": raw.get("schedule_type") or SCHEDULE_FIXED,
        "schedule_config": dict(cfg),
    }
    if raw.get("account_id") is not None:
        out["account_id"] = str(raw["account_id"])
    if raw.get("target_segment_id") is not None:
        out["target_segment_id"] = str(raw["target_segment_id"])
    for key in ("run_at", "last_run_at", _ARMED, "earliest_pending_at"):
        v = cfg.get(key)
        if isinstance(v, datetime):
            out["schedule_config"][key] = to_utc(v).isoformat()
    if raw.get("trigger_conditions"):
        out["trigger_conditions"] = raw.get("trigger_conditions")
    return out
