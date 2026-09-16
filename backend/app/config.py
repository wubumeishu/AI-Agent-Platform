"""Application configuration (runtime DSN resolution).

Central place that resolves the ``DATABASE_URL`` the service uses. An optional
``<backend>/.env`` file is loaded at import time via ``python-dotenv``;
**real environment variables always win** (``override=False``). The code-level
default is deliberately credential-free — a working deployment MUST supply a
credentialed DSN via the environment (env var, ``.env``, or launch script).

Credentials are never hard-coded in source.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    _HAS_DOTENV = True
except Exception:  # pragma: no cover - dotenv is a declared dep, but be safe
    _HAS_DOTENV = False

# <backend>/.env is the canonical local config file (gitignored).
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# Canonical, credential-free default. It will NOT authenticate against
# PostgreSQL on its own; it only applies when neither an env var nor a .env
# supplies DATABASE_URL.
DEFAULT_DATABASE_URL = "postgresql+asyncpg://localhost:5432/ai_agent_platform"

_LOADED: set[str] = set()


def load_env(env_file=None):
    """Load a dotenv file (default: ``<backend>/.env``) if it exists.

    Real environment variables always take precedence (``override=False``), so
    a deploy that sets ``DATABASE_URL`` in the environment wins over the file.
    Idempotent per-path (a path is loaded at most once per process).
    Returns the loaded path, or ``None`` if there was nothing to load.
    """
    path = Path(env_file) if env_file is not None else _ENV_FILE
    key = str(path)
    if key in _LOADED:
        return path if path.exists() else None
    if _HAS_DOTENV and path.exists():
        load_dotenv(path, override=False)
        _LOADED.add(key)
        return path
    if not path.exists():
        _LOADED.add(key)
    return None


def database_url() -> str:
    """Pure read of the resolved DSN (no side effects).

    Callers that want the ``.env`` applied call :func:`load_env` first — or rely
    on ``app.db.session``, which loads the env file at import time.
    """
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def db_required_on_startup() -> bool:
    """Whether a failed DB ping at boot should REFUSE to start the service.

    Off by default: a down/misconfigured DB is announced with a loud log warning
    at boot and is visible on ``/api/v1/health/db``, but the HTTP layer still
    comes up (so operators can inspect state, hit docs, and read logs). Set
    ``DB_REQUIRED_ON_STARTUP=1`` (or true/yes) to hard-fail boot instead.
    """
    return os.getenv("DB_REQUIRED_ON_STARTUP", "").strip().lower() in ("1", "true", "yes", "on")


def _truthy_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def scheduler_autostart() -> bool:
    """Whether the scheduler engine auto-starts (and re-arms persisted
    schedules) at app startup instead of waiting for an explicit
    ``POST /api/v1/schedulers/engine/start``.

    P1-2 (architecture review): a persisted cron/interval schedule used to
    stay *stopped* after a process restart (only a manual start re-armed it),
    contradicting the engine docstring's "restarts pick up persisted
    schedules" promise. Auto-start is **on by default** so the committed
    behaviour holds; set ``SCHEDULER_AUTOSTART=0`` to restore the old
    explicit-start semantics (e.g. when timed execution is intentionally not
    wanted in a given deployment).

    Independent of the DB reachability gate: a down DB still comes up (see
    :func:`db_required_on_startup`), and the engine's fire loop will simply
    log unreachable-DB errors per tick rather than crash boot.
    """
    return _truthy_env("SCHEDULER_AUTOSTART", "true")


def scheduler_default_queue_name() -> str:
    """Default queue a scheduler fire enqueues onto when the scheduler has no
    workflow-scoped queue (see :class:`QueueDispatcher`).

    Set ``SCHEDULER_DEFAULT_QUEUE`` to redirect all default fires to a specific
    queue name.
    """
    return os.getenv("SCHEDULER_DEFAULT_QUEUE", "workflow-scheduler")


def scheduler_worker_enabled() -> bool:
    """Whether the in-process scheduler task consumer runs (P1-R1 reliability).

    The scheduler engine only *enqueues* fired schedules as ``WorkflowTask``
    rows; without a consumer, default-install fires sit in the queue forever
    ("入队即丢弃"). Opt in with ``SCHEDULER_WORKER=1`` to run the closed
    loop fire -> claim -> execute inside the service process
    (``app.services.scheduler.consumer``). Off by default so deployments that
    run a dedicated external worker on the same queue are not double-executed.
    """
    return _truthy_env("SCHEDULER_WORKER", "false")


def scheduler_worker_poll_seconds() -> float:
    """Claim-poll interval (seconds) for the in-process consumer."""
    raw = os.getenv("SCHEDULER_WORKER_POLL_SECONDS", "1.0").strip()
    try:
        return max(0.1, float(raw))
    except ValueError:
        return 1.0


def scheduler_default_max_retries() -> int:
    """Default ``max_retries`` stamped onto scheduler-fired tasks (P1-R2).

    A crashed/stuck execution of a timed workflow is therefore *retryable*
    by default: the periodic sweep marks it ``timeout`` and the retry path
    re-queues it up to this many times instead of leaving an unrecoverable
    orphan. Set ``SCHEDULER_DEFAULT_MAX_RETRIES=0`` to disable auto-retry.
    """
    raw = os.getenv("SCHEDULER_DEFAULT_MAX_RETRIES", "2").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 2


def scheduler_default_timeout_seconds() -> int:
    """Default per-task execution timeout (seconds) for scheduler-fired tasks.

    Used together with the periodic auto-sweep so a stuck running task is
    observable (swept to ``timeout``) by default instead of rotting forever.
    Set ``SCHEDULER_DEFAULT_TASK_TIMEOUT=0`` to leave scheduler tasks
    untimed (then crash-recovery at restart is the only recovery path).
    """
    raw = os.getenv("SCHEDULER_DEFAULT_TASK_TIMEOUT", "600").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 600


def task_sweep_interval_seconds() -> float:
    """Periodic auto-sweep interval for ``sweep_timeouts`` + retry requeue
    (P1-R2). ``0`` disables the timer; recovery then stays manual
    (POST /workflow-tasks/sweep-timeouts) plus restart crash-recovery.
    """
    raw = os.getenv("WORKFLOW_TASK_SWEEP_INTERVAL", "30").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 30.0


def task_staleness_threshold_seconds() -> float:
    """Startup crash-recovery threshold (P1-R2): running tasks whose
    ``claimed_at`` is older than this (or whose claim is not attributable to a
    live worker of this process) are reset to ``pending`` at boot, so a
    process crash between claim and terminal commit never leaves an
    unrecoverable running orphan.
    """
    raw = os.getenv("WORKFLOW_TASK_STALENESS", "3600").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 3600.0


def task_crash_recovery_enabled() -> bool:
    """Whether startup resets stale running tasks to pending (P1-R2).

    On by default: without it a worker crash after ``claim_next`` leaves the
    task ``running`` forever (the engine has no other recovery path). Set
    ``WORKFLOW_TASK_CRASH_RECOVERY=0`` to keep the old manual-only semantics.
    """
    return _truthy_env("WORKFLOW_TASK_CRASH_RECOVERY", "true")


# ==========================================================================
# P6AN-09 ROI analysis — configurable cost-proxy rates
# ==========================================================================
# The ROI card computes *投入* (input) as a **cost proxy** over observable
# activity volumes (outbound messages / nurture executions / follow-up tasks /
# active agents / campaign leads) because no finance system is wired up yet
# (out of scope this wave). The per-unit rates are env-configurable so each
# deployment can supply its real operating-cost figures without a code change.
#
# **Defaults are all ``0``** — an honest "no cost basis configured" state.
# With every rate at 0 the total input is 0, so the ROI ratio/percent is
# reported as ``None`` (undefined, NOT 0%) rather than fabricating a false
# cost. Set the rates below to activate the cost proxy. Full caliber doc:
# ``backend/docs/P6AN-09-roi-analysis-api.md``.

def _cents_env(name: str, default: int = 0) -> int:
    """Read a non-negative integer cents rate from the environment (P6AN-09).

    Malformed values fall back to ``default`` (never a startup crash).
    Negative values are clamped to ``0`` — a cost rate must never be negative.
    """
    raw = os.getenv(name, str(default)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def roi_cost_rates() -> Dict[str, int]:
    """The full P6AN-09 cost-proxy rate table (cents per unit, per source).

    Keys are stable so the service / response / docs share one name space.
    Returns a plain dict so a test can hand a pure-assembler its own rates
    without touching the environment.
    """
    return {
        "cost_per_outbound_message_cents": _cents_env("ROI_COST_PER_OUTBOUND_MESSAGE_CENTS", 0),
        "cost_per_nurture_execution_cents": _cents_env("ROI_COST_PER_NURTURE_EXECUTION_CENTS", 0),
        "cost_per_followup_task_cents": _cents_env("ROI_COST_PER_FOLLOWUP_TASK_CENTS", 0),
        "cost_per_active_agent_cents": _cents_env("ROI_COST_PER_ACTIVE_AGENT_CENTS", 0),
        "cost_per_campaign_lead_cents": _cents_env("ROI_COST_PER_CAMPAIGN_LEAD_CENTS", 0),
    }


# ==========================================================================
# CORS whitelist (P2-4)
# ==========================================================================
# The app previously shipped ``CORSMiddleware(allow_origins=["*"],
# allow_credentials=True)`` — a wildcard origin combined with credentialed
# requests is a browser-rejected antipattern that, on top of the now-fixed
# unauthenticated analytics surface, widened the cross-origin leakage surface.
# CORS is now an explicit, env-driven origin *whitelist*: set
# ``CORS_ORIGINS`` to a comma-separated list of allowed origins for a
# deployment. When unset, a local/dev default (the Vite frontend) is used so
# the dev experience keeps working without anyone opening the config.

#: Dev-friendly default — the local Vite frontend ports. Not a wildcard: a
#: credentialed request will never be cross-origin from ``*`` anymore.
_DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def cors_origins() -> list:
    """The explicit CORS origin whitelist (P2-4).

    Reads ``CORS_ORIGINS`` (comma-separated, blank entries ignored) and falls
    back to the local dev defaults when unset/empty. Never returns ``["*"]``:
    a deployment that truly needs a broad surface should enumerate origins.
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        raw = _DEFAULT_CORS_ORIGINS
    return [o.strip() for o in raw.split(",") if o.strip()]


def cors_allow_credentials() -> bool:
    """Whether credentialed CORS requests are permitted.

    Credentials are allowed only when the origin list is an explicit
    whitelist (never a wildcard) — the combination that keeps a credentialed
    cross-origin request safe and browser-compatible.
    """
    return "*" not in cors_origins()

