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
