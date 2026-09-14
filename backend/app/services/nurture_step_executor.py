"""Step Execution Engine (pure core) for the NurturePlan runtime.

Given a *run* (one pass of a due plan at a point in time) this engine:

1. selects the steps that are due (via :mod:`nurture_schedule`),
2. resolves each step's content - **reuse** an existing library item or
   **generate** AI content through an injected :class:`ContentProvider`,
3. records a per-step :class:`StepExecutionResult` (status, content provenance,
   timing, retry decision) the adapter persists to ``NurtureStepExecution``.

The engine holds no DB session and no FastAPI. Content delivery (calling the
Phase 5 AI provider, the channel-delivery hook) is *injected* so the whole
sequence - including AI generation where a step requires it - is unit-testable
and reproducible, per the "separate AI logic from platform logic" rule.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from app.services.nurture_schedule import (
    ScheduledStep,
    backoff_seconds,
    due_steps,
    is_recoverable,
    step_terminal_status,
    to_utc,
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_BACKOFF_CAP_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
)

logger = logging.getLogger(__name__)


# ---------- content provider abstraction ----------

class ContentProvider(Protocol):
    """Delivers a step's content. Injected so the engine is platform-agnostic.

    - ``reuse(step)``    -> resolve an existing content_id.
    - ``generate(step)`` -> run the AI generation pipeline (Phase 5) and return
      the produced content descriptor.

    Both return a :class:`ContentResolution`; a failed delivery raises
    (the engine catches it and routes to retry / dead-letter).
    """

    async def reuse(self, plan: Dict[str, Any], step: ScheduledStep) -> "ContentResolution":
        ...

    async def generate(self, plan: Dict[str, Any], step: ScheduledStep) -> "ContentResolution":
        ...


@dataclass
class ContentResolution:
    """What a step delivered (or will deliver) for this attempt."""

    content_item_id: Optional[str] = None
    content_type: Optional[str] = None
    strategy: str = "reuse"  # reuse | llm | template
    quality_score: Optional[float] = None
    quality_passed: Optional[bool] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------- result record ----------

@dataclass
class StepExecutionResult:
    """Outcome of executing one due step in one attempt."""

    step_id: Optional[str]
    step_order: int
    scheduled_at: datetime
    status: str  # success | failed | dead_letter | skipped
    attempt: int
    content_item_id: Optional[str] = None
    content_type: Optional[str] = None
    content_strategy: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    next_retry_in_s: Optional[float] = None
    will_retry: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_execution_row(self) -> Dict[str, Any]:
        """JSON/ORM-safe fields the adapter writes to NurtureStepExecution."""
        return {
            "step_id": self.step_id,
            "step_order": self.step_order,
            "attempt": self.attempt,
            "status": self.status,
            "content_item_id": self.content_item_id,
            "content_type": self.content_type,
            "content_strategy": self.content_strategy,
            "retry_count": self.retry_count,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "scheduled_at": to_utc(self.scheduled_at),
            "metadata_": self.metadata,
        }


@dataclass
class RunResult:
    """Aggregate result of executing one run of one plan."""

    plan_id: str
    run_id: str
    executed: int = 0
    succeeded: int = 0
    failed: int = 0
    dead_lettered: int = 0
    skipped: int = 0
    will_retry: int = 0
    all_done: bool = False  # every step reached a terminal success/dead_letter
    results: List[StepExecutionResult] = field(default_factory=list)


def _pick_provider_method(
    provider: ContentProvider, step: ScheduledStep
) -> Any:
    """A step with a concrete content_id reuses; one without it generates."""
    return provider.reuse if step.content_id else provider.generate


class StepExecutionEngine:
    """Runs the due steps of a single plan run, honoring content + retries."""

    def __init__(
        self,
        content_provider: ContentProvider,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base_s: float = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_cap_s: float = DEFAULT_BACKOFF_CAP_SECONDS,
    ) -> None:
        self.provider = content_provider
        self.max_attempts = max_attempts
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s

    # ------------------------------------------------------------------

    async def execute_run(
        self,
        plan: Dict[str, Any],
        scheduled: List[ScheduledStep],
        now: datetime,
        *,
        run_id: str,
        attempt_for: Optional[Dict[int, int]] = None,
    ) -> RunResult:
        """Execute every step that is due ``now`` for this run.

        ``attempt_for`` maps step_order -> number of *previous failed attempts*
        so a re-queued run resumes at the right attempt (retry bookkeeping).
        """
        now = to_utc(now) or datetime.now(timezone.utc)
        attempt_for = attempt_for or {}
        due = due_steps(scheduled, now)

        result = RunResult(plan_id=str(plan.get("id")), run_id=str(run_id))
        terminal_orders = set()

        for step in due:
            prior_failed = int(attempt_for.get(step.step_order, 0))
            attempt = prior_failed + 1
            outcome = await self._execute_step(plan, step, run_id, attempt)
            result.results.append(outcome)
            self._tally(outcome, result)
            if outcome.status in ("success", "dead_letter"):
                terminal_orders.add(step.step_order)

        # all_done when every scheduled step is due AND has a terminal outcome
        result.all_done = len(due) == len(scheduled) and all(
            s.step_order in terminal_orders for s in due
        ) and len(scheduled) == len(due)
        return result

    # ------------------------------------------------------------------

    async def _execute_step(
        self,
        plan: Dict[str, Any],
        step: ScheduledStep,
        run_id: str,
        attempt: int,
    ) -> StepExecutionResult:
        base = StepExecutionResult(
            step_id=step.step_id,
            step_order=step.step_order,
            scheduled_at=step.scheduled_at,
            status="running",
            attempt=attempt,
        )
        method = _pick_provider_method(self.provider, step)
        try:
            resolution: ContentResolution = await method(plan, step)
        except Exception as exc:  # noqa: BLE001 - engine must not leak step errors
            # Decide retry vs dead-letter for this failed attempt.
            recoverable = is_recoverable(exc)
            will_retry = recoverable and attempt < self.max_attempts
            if will_retry:
                status = "failed"
            else:
                # deterministic error OR budget exhausted -> dead letter
                status = "dead_letter"
                if not recoverable:
                    base.metadata["dead_reason"] = "non_recoverable_error"
            base.status = status
            base.error_code = f"E_{type(exc).__name__}"[:100]
            base.error_message = f"{type(exc).__name__}: {exc}"[:5000]
            base.retry_count = attempt
            if status == "failed":
                base.next_retry_in_s = backoff_seconds(
                    attempt, self.backoff_base_s, self.backoff_cap_s
                )
                base.will_retry = True
            base.metadata["recoverable"] = recoverable
            base.metadata["run_id"] = run_id
            logger.warning(
                "nurture step %s (order=%s) attempt %s -> %s: %s",
                step.step_id, step.step_order, attempt, status, base.error_message,
            )
            return base

        # success path - capture content provenance
        base.status = "success"
        base.content_item_id = resolution.content_item_id
        base.content_type = resolution.content_type
        base.content_strategy = resolution.strategy
        base.metadata.update(resolution.metadata or {})
        base.metadata["run_id"] = run_id
        return base

    @staticmethod
    def _tally(outcome: StepExecutionResult, result: RunResult) -> None:
        result.executed += 1
        if outcome.status == "success":
            result.succeeded += 1
        elif outcome.status in ("failed", "dead_letter"):
            result.failed += 1
        elif outcome.status == "skipped":
            result.skipped += 1
        if outcome.status == "dead_letter":
            result.dead_lettered += 1
        if outcome.will_retry:
            result.will_retry += 1
