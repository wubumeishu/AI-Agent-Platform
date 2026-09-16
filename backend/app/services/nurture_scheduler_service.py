"""DB adapter + platform wiring for the NurturePlan execution engine.

Layers (mirrors the repo's pure-core + thin-adapter rule):

- :mod:`nurture_schedule` / :mod:`nurture_step_executor`  -> pure, no DB.
- THIS module                                    -> the platform adapter:
  * ``DBContentProvider`` resolves step content against Postgres - reusing an
    existing library item or running the Phase 5 AI generator.
  * ``NurtureScheduler`` picks up *due* plans (fixed / drip / triggered)
    without a manual trigger, runs their due steps through the engine,
    persists per-step execution rows, and drives retry / dead-letter.
  * ``sync_due_segments`` drives automatic/dynamic segment member sync
    (TD-9) - member_count + last_synced_at.

The scheduler works WITHOUT a DB when the pure core is under test; against a
real ``AsyncSession`` it performs the full pipeline. Time handling reuses the
pure-core helpers so behaviour is identical in both modes.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.private_domain import (
    NurturePlan,
    NurturePlanItem,
    CustomerSegment,
    PlanStatus,
)
from app.db.models.nurture_execution import NurtureStepExecution
from app.services.nurture_schedule import (
    ScheduledStep,
    is_plan_due,
    normalize_descriptor,
    sequence_steps,
    to_utc,
    segment_needs_sync,
    SYNC_SEGMENT_TYPES,
)
from app.services.nurture_step_executor import (
    ContentResolution,
    ContentProvider,
    RunResult,
    StepExecutionEngine,
    StepExecutionResult,
)

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    """Coerce UUIDs/datetimes to JSON-safe values for JSONB metadata."""
    if isinstance(value, dict):
        return {
            (str(k) if isinstance(k, uuid.UUID) else k): _json_safe(v)
            for k, v in value.items()
        }
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


# =====================================================================
# DB-backed content provider (bridge to the Phase 5 AI generator)
# =====================================================================

class DBContentProvider:
    """Resolves a step's content against Postgres.

    - ``reuse``: load the existing ContentItem the step's ``content_id`` points
      at (a missing/deleted item is a delivery failure -> retryable).
    - ``generate``: run the Phase 5 :class:`ContentGenerationService` to
      produce AI content, persist it to the library, and link it back.

    The generator is lazily imported so the module has no hard dependency on
    the Phase 5 service at import time (keeps the engine testable in isolation).
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        llm_provider: Optional[Any] = None,
    ) -> None:
        self.db = db
        self._llm_provider = llm_provider

    # ---------- reuse ----------

    async def reuse(
        self, plan: Dict[str, Any], step: ScheduledStep
    ) -> ContentResolution:
        from app.db.models.private_domain import ContentItem

        if not step.content_id:
            raise ValueError("reuse requested but step has no content_id")
        item = await self.db.get(ContentItem, uuid.UUID(step.content_id))
        if item is None:
            raise LookupError(
                f"content item {step.content_id} not found (deleted?)"
            )
        # Bump usage bookkeeping best-effort (never breaks delivery).
        try:
            from datetime import datetime as _dt
            item.usage_count = int(getattr(item, "usage_count", 0) or 0) + 1
            item.last_used_at = to_utc(_dt.now(timezone.utc))
            await self.db.flush()
        except Exception:  # noqa: BLE001
            logger.debug("usage bump failed; ignoring", exc_info=True)
        return ContentResolution(
            content_item_id=str(item.id),
            content_type=item.content_type,
            strategy="reuse",
            metadata={"reused_title": item.title},
        )

    # ---------- AI generation ----------

    async def generate(
        self, plan: Dict[str, Any], step: ScheduledStep
    ) -> ContentResolution:
        from app.schemas.content_generation import ContentGenerationRequest
        from app.services.content_generation_service import ContentGenerationService

        cfg = step.config or {}
        gen_service = ContentGenerationService(
            self.db, llm_provider=self._llm_provider
        )
        request = ContentGenerationRequest(
            account_id=uuid.UUID(str(plan.get("account_id")) or str(plan["id"])),
            content_type=cfg.get("content_type", "text"),
            objective=cfg.get("objective", "nurture"),
            channel=cfg.get("channel"),
            segment_name=cfg.get("segment_name"),
            tone=cfg.get("tone"),
            length=cfg.get("length", "medium"),
            language=cfg.get("language", "zh"),
            include_cta=cfg.get("include_cta", True),
            save_to_library=True,  # a delivered step must persist to the library
            category=cfg.get("category"),
        )
        result = await gen_service.generate_content(request)
        # The service persisted the audit row + library item when save_to_library.
        return ContentResolution(
            content_item_id=(
                str(result.content_item_id) if result.content_item_id else None
            ),
            content_type=result.content_type,
            strategy=result.strategy,
            quality_score=result.quality.score,
            quality_passed=result.quality.passed,
            metadata={
                "generation_id": (
                    str(result.generation_id) if result.generation_id else None
                ),
                "fallback_used": result.fallback_used,
                "fallback_reason": result.fallback_reason,
            },
        )


# =====================================================================
# Scheduler worker - pick up due plans, run their due steps
# =====================================================================

class NurtureScheduler:
    """In-process worker that drives the NurturePlan execution engine.

    ``run_pass`` is one scheduler tick: find active plans that are due *now*
    (no manual trigger required), sequence their steps, execute the ones that
    are due, persist execution rows, and remember where to resume on retry.

    The class is transport-agnostic: the app's tick loop (or a cron entry)
    simply calls ``run_pass()`` on an interval.
    """

    def __init__(
        self,
        session_factory,
        *,
        content_provider: Optional[ContentProvider] = None,
        engine: Optional[StepExecutionEngine] = None,
        max_attempts: int = 3,
        llm_provider: Optional[Any] = None,
    ) -> None:
        self.session_factory = session_factory
        # An explicitly-injected provider (tests / caller-managed) is used as-is
        # for every pass. When none is injected, run_pass builds a fresh
        # DBContentProvider bound to the pass's OWN session so that content
        # delivery + execution rows + segment sync share one transaction
        # (single-session invariant).
        self._injected_provider = content_provider
        self._llm_provider = llm_provider
        self.max_attempts = max_attempts
        # An explicit engine override (tests) short-circuits per-pass binding.
        self._engine_override = engine

    def _engine_for_pass(self, db: AsyncSession) -> StepExecutionEngine:
        """Resolve the StepExecutionEngine for one scheduler pass.

        - explicit ``engine=`` override  -> returned verbatim;
        - injected ``content_provider``   -> a pass engine bound to it;
        - otherwise                        -> a pass engine bound to a
          :class:`DBContentProvider` on *this* session (with the optional
          Phase-5 LLM provider, for AI generation where a step requires it).
        """
        if self._engine_override is not None:
            return self._engine_override
        if self._injected_provider is not None:
            return StepExecutionEngine(
                self._injected_provider, max_attempts=self.max_attempts
            )
        provider = DBContentProvider(db, llm_provider=self._llm_provider)
        return StepExecutionEngine(provider, max_attempts=self.max_attempts)

    # ------------------------------------------------------------------
    # plan / step loading (adapter side)
    # ------------------------------------------------------------------

    @staticmethod
    async def _load_plan_descriptor(db: AsyncSession, plan: NurturePlan) -> Dict[str, Any]:
        """Build the plain descriptor the pure core consumes."""
        # Count steps that still need to fire so drip/due detection is accurate.
        step_rows = (
            await db.execute(
                select(NurturePlanItem).where(
                    NurturePlanItem.plan_id == plan.id,
                    NurturePlanItem.is_deleted == False,  # noqa: E712
                ).order_by(NurturePlanItem.step_order.asc())
            )
        ).scalars().all()

        executed_ok_orders: set = set()
        # Which steps already succeeded in a prior run of this plan (resume).
        succ = (
            await db.execute(
                select(NurtureStepExecution.step_order).where(
                    NurtureStepExecution.plan_id == plan.id,
                    NurtureStepExecution.status == "success",
                )
            )
        ).scalars().all()
        executed_ok_orders = set(succ)

        pending = [
            s for s in step_rows if s.step_order not in executed_ok_orders
        ]
        config = dict(plan.schedule_config or {})
        config["pending_steps"] = len(pending)
        if pending:
            earliest = sequence_steps(
                [
                    {
                        "step_id": str(s.id),
                        "step_order": s.step_order,
                        "content_id": str(s.content_id) if s.content_id else None,
                        "trigger_type": s.trigger_type,
                        "delay_hours": s.delay_hours,
                        "config": s.config or {},
                    }
                    for s in pending
                ],
                run_started_at=to_utc(plan.updated_at) or datetime.now(timezone.utc),
            )
            if earliest:
                config["earliest_pending_at"] = earliest[0].scheduled_at.isoformat()

        desc = normalize_descriptor(
            {
                "id": plan.id,
                "account_id": plan.account_id,
                "status": plan.status,
                "schedule_type": plan.schedule_type,
                "schedule_config": config,
                "trigger_conditions": plan.trigger_conditions or [],
            }
        )
        desc["target_segment_id"] = str(plan.target_segment_id) if plan.target_segment_id else None
        desc["steps"] = [
            {
                "step_id": str(s.id),
                "step_order": s.step_order,
                "content_id": str(s.content_id) if s.content_id else None,
                "trigger_type": s.trigger_type,
                "delay_hours": s.delay_hours,
                "config": s.config or {},
            }
            for s in step_rows
        ]
        desc["run_id"] = str(plan.id)
        return desc

    @staticmethod
    async def _prior_attempts(db: AsyncSession, plan_id) -> Dict[int, int]:
        """step_order -> number of previous failed attempts (resume bookkeeping)."""
        rows = (
            await db.execute(
                select(NurtureStepExecution.step_order, NurtureStepExecution.retry_count).where(
                    NurtureStepExecution.plan_id == plan_id,
                    NurtureStepExecution.status.in_(["failed", "dead_letter"]),
                )
            )
        ).all()
        out: Dict[int, int] = {}
        for order, rc in rows:
            out[int(order)] = int(rc or 0)
        return out

    # ------------------------------------------------------------------
    # public: one scheduler pass
    # ------------------------------------------------------------------

    async def run_pass(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Run one due-detection + execution pass. Returns a summary dict.

        - scans active (non-deleted) nurture plans,
        - keeps the ones due at ``now`` (fixed/drip/triggered),
        - for each, runs its due steps through the engine,
        - persists a ``NurtureStepExecution`` row per executed step,
        - drives segment sync when a plan targeted a segment.

        Safe to call with no due plans (returns zero counts, no commits).
        """
        now = to_utc(now) or datetime.now(timezone.utc)
        summary: Dict[str, Any] = {
            "now": now.isoformat(),
            "plans_scanned": 0,
            "plans_due": 0,
            "steps_executed": 0,
            "steps_succeeded": 0,
            "steps_failed": 0,
            "dead_lettered": 0,
            "will_retry": 0,
            "segments_synced": 0,
            "plan_results": [],
        }

        db = self.session_factory()
        try:
            plans = (
                (
                    await db.execute(
                        select(NurturePlan).where(
                            NurturePlan.status == PlanStatus.ACTIVE.value,
                            NurturePlan.is_deleted == False,  # noqa: E712
                        )
                    )
                )
                .scalars()
                .all()
            )
            summary["plans_scanned"] = len(plans)

            for plan in plans:
                desc = await self._load_plan_descriptor(db, plan)
                if not is_plan_due(desc, now):
                    continue
                summary["plans_due"] += 1
                pr = await self._run_plan(db, desc, now, summary)
                summary["plan_results"].append(pr)
            await db.commit()
        except Exception:
            logger.exception("nurture scheduler pass raised; rolling back")
            try:
                await db.rollback()
            except Exception:
                logger.exception("nurture scheduler rollback raised")
            raise
        finally:
            await db.close()

        return summary

    # ------------------------------------------------------------------

    async def _run_plan(
        self,
        db: AsyncSession,
        desc: Dict[str, Any],
        now: datetime,
        summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        steps = desc.get("steps") or []
        if not steps:
            # Nothing to deliver: close the run out as done (drip exhaustion).
            return {"plan_id": str(desc["id"]), "executed": 0, "all_done": True}

        run_id = str(uuid.uuid4())
        scheduled = sequence_steps(steps, run_started_at=now)
        attempt_for = await self._prior_attempts(db, desc.get("id") or desc.get("plan_id"))
        # Map step_order keyed by int; the engine's attempt_for uses step_order.
        engine = self._engine_for_pass(db)
        engine_result = await engine.execute_run(
            desc, scheduled, now, run_id=run_id, attempt_for=attempt_for
        )
        await self._persist_results(db, desc, run_id, engine_result)

        summary["steps_executed"] += engine_result.executed
        summary["steps_succeeded"] += engine_result.succeeded
        summary["steps_failed"] += engine_result.failed
        summary["dead_lettered"] += engine_result.dead_lettered
        summary["will_retry"] += engine_result.will_retry

        # Segment sync driver (TD-9) when this plan targeted a segment.
        seg = await self._maybe_sync_segment(db, desc)
        if seg:
            summary["segments_synced"] += 1

        return {
            "plan_id": str(desc.get("id")),
            "run_id": run_id,
            "executed": engine_result.executed,
            "succeeded": engine_result.succeeded,
            "failed": engine_result.failed,
            "dead_lettered": engine_result.dead_lettered,
            "will_retry": engine_result.will_retry,
            "all_done": engine_result.all_done,
            "segment_synced": bool(seg),
        }

    async def _persist_results(
        self,
        db: AsyncSession,
        desc: Dict[str, Any],
        run_id: str,
        result: RunResult,
    ) -> None:
        for outcome in result.results:
            row = outcome.to_execution_row()
            finished = to_utc(datetime.now(timezone.utc))
            rec = NurtureStepExecution(
                plan_id=uuid.UUID(str(desc.get("id"))),
                account_id=(
                    uuid.UUID(str(desc["account_id"])) if desc.get("account_id") else None
                ),
                step_id=(uuid.UUID(outcome.step_id) if outcome.step_id else None),
                step_order=outcome.step_order,
                run_id=uuid.UUID(run_id),
                attempt=outcome.attempt,
                status=outcome.status,
                content_item_id=(
                    uuid.UUID(outcome.content_item_id)
                    if outcome.content_item_id
                    else None
                ),
                content_type=outcome.content_type,
                content_strategy=outcome.content_strategy,
                scheduled_at=outcome.scheduled_at,
                executed_at=finished,
                finished_at=finished,
                duration_ms=0.0,
                retry_count=outcome.retry_count,
                error_code=outcome.error_code,
                error_message=outcome.error_message,
                metadata_=_json_safe(outcome.metadata or {}),
            )
            db.add(rec)
        await db.flush()

    async def _maybe_sync_segment(
        self, db: AsyncSession, desc: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Drive an automatic/dynamic segment sync (TD-9) if this plan targeted one."""
        seg_id = desc.get("target_segment_id")
        if not seg_id:
            return None
        seg = await db.get(CustomerSegment, uuid.UUID(str(seg_id)))
        if seg is None or getattr(seg, "is_deleted", False):
            return None
        seg_descriptor = {
            "segment_type": seg.segment_type,
            "last_synced_at": seg.last_synced_at,
        }
        if not segment_needs_sync(seg_descriptor, datetime.now(timezone.utc)):
            return None
        try:
            from app.services.segment_rule_engine import sync_segment_members

            stats = await sync_segment_members(db, seg.id)
            return stats
        except Exception:
            logger.warning(
                "segment sync for plan %s failed; plan run unaffected",
                desc.get("id"),
                exc_info=True,
            )
            return None


# =====================================================================
# in-app tick loop (opt-in; mirrors the Phase 4 scheduler engine)
# =====================================================================

class NurtureSchedulerLoop:
    """Repeatedly runs ``NurtureScheduler.run_pass`` on an interval.

    Explicit start/stop semantics (V1 single-node): the app must call
    ``start()``/``stop()`` - the loop does not auto-run on import.
    """

    def __init__(
        self,
        scheduler: NurtureScheduler,
        *,
        tick_seconds: float = 30.0,
    ) -> None:
        self.scheduler = scheduler
        self.tick_seconds = tick_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_pass_at: Optional[datetime] = None
        self.passes_total = 0
        self.passes_failed = 0

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "tick_seconds": self.tick_seconds,
            "last_pass_at": self.last_pass_at.isoformat() if self.last_pass_at else None,
            "passes_total": self.passes_total,
            "passes_failed": self.passes_failed,
        }

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="nurture-scheduler-loop")
        logger.info("NurtureSchedulerLoop started (tick=%.1fs)", self.tick_seconds)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        task, self._task = self._task, None
        if task is not None:
            await task
        logger.info("NurtureSchedulerLoop stopped")

    async def close(self) -> None:
        await self.stop()

    async def _run(self) -> None:
        while self._running:
            try:
                summary = await self.scheduler.run_pass()
                self.passes_total += 1
                self.last_pass_at = datetime.now(timezone.utc)
                if summary.get("plans_due"):
                    logger.info(
                        "nurture pass: %s due, %s steps executed",
                        summary["plans_due"],
                        summary["steps_executed"],
                    )
            except Exception:
                self.passes_failed += 1
                logger.exception("nurture scheduler pass failed; loop continues")
            await asyncio.sleep(self.tick_seconds)


# =====================================================================
# segment sync driver (public, TD-9)
# =====================================================================

async def sync_due_segments(
    db: AsyncSession, interval_hours: float = 6.0
) -> List[Dict[str, Any]]:
    """Sync every automatic/dynamic segment that is due (drives member_count /
    last_synced_at). Returns per-segment sync stats."""
    from app.services.segment_rule_engine import sync_segment_members

    segments = (
        (
            await db.execute(
                select(CustomerSegment).where(
                    CustomerSegment.segment_type.in_(SYNC_SEGMENT_TYPES),
                    CustomerSegment.is_deleted == False,  # noqa: E712
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)
    due = [
        s
        for s in segments
        if segment_needs_sync(
            {"segment_type": s.segment_type, "last_synced_at": s.last_synced_at},
            now,
            interval_hours,
        )
    ]
    results: List[Dict[str, Any]] = []
    for seg in due:
        try:
            results.append(await sync_segment_members(db, seg.id))
        except Exception:
            logger.warning(
                "segment %s sync failed", seg.id, exc_info=True
            )
    if results:
        await db.commit()
    return results


# =====================================================================
# execution log queries (the "execution log API" - read side)
# =====================================================================

def _execution_row_to_dict(rec: NurtureStepExecution) -> Dict[str, Any]:
    """Serialize a NurtureStepExecution row to a JSON-safe API payload."""
    return {
        "id": str(rec.id) if rec.id else None,
        "plan_id": str(rec.plan_id),
        "account_id": str(rec.account_id) if rec.account_id else None,
        "step_id": str(rec.step_id) if rec.step_id else None,
        "step_order": rec.step_order,
        "run_id": str(rec.run_id) if rec.run_id else None,
        "attempt": rec.attempt,
        "status": rec.status,
        "content_item_id": str(rec.content_item_id) if rec.content_item_id else None,
        "content_type": rec.content_type,
        "content_strategy": rec.content_strategy,
        "scheduled_at": to_utc(rec.scheduled_at).isoformat() if rec.scheduled_at else None,
        "executed_at": to_utc(rec.executed_at).isoformat() if rec.executed_at else None,
        "finished_at": to_utc(rec.finished_at).isoformat() if rec.finished_at else None,
        "duration_ms": rec.duration_ms,
        "retry_count": rec.retry_count,
        "error_code": rec.error_code,
        "error_message": rec.error_message,
        "created_at": to_utc(rec.created_at).isoformat() if rec.created_at else None,
    }


async def list_plan_executions(
    db: AsyncSession,
    plan_id: "uuid.UUID",
    *,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Execution history for one plan (newest first), optionally filtered by status."""
    base_filter = NurtureStepExecution.plan_id == plan_id
    q = select(NurtureStepExecution).where(
        base_filter,
        NurtureStepExecution.is_deleted == False,  # noqa: E712
    )
    if status:
        q = q.where(NurtureStepExecution.status == status)
    total = (
        (await db.execute(select(func.count()).select_from(NurtureStepExecution).where(base_filter)))
        .scalar()
        or 0
    )
    rows = (
        await db.execute(
            q.order_by(NurtureStepExecution.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return {
        "plan_id": str(plan_id),
        "items": [_execution_row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def list_dead_letters(
    db: AsyncSession,
    *,
    account_id: Optional["uuid.UUID"] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Dead-lettered steps (terminal, retries-exhausted / non-recoverable) - the
    operator queue. Filter by account when given; newest first."""
    base_filter = NurtureStepExecution.status == "dead_letter"
    q = select(NurtureStepExecution).where(
        base_filter,
        NurtureStepExecution.is_deleted == False,  # noqa: E712
    )
    if account_id:
        q = q.where(NurtureStepExecution.account_id == account_id)
    total = (
        (await db.execute(select(func.count()).select_from(NurtureStepExecution).where(base_filter)))
        .scalar()
        or 0
    )
    rows = (
        await db.execute(q.order_by(NurtureStepExecution.created_at.desc()).limit(limit))
    ).scalars().all()
    return {
        "items": [_execution_row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
    }


async def get_plan_execution_progress(
    db: AsyncSession, plan_id: "uuid.UUID"
) -> Dict[str, Any]:
    """Per-plan execution progress: counts by status + last activity.

    This is the "current progress query" the architecture review asked for
    (review §2.3) - what has run, what is pending, what is stuck.
    """
    base_filter = (
        (NurtureStepExecution.plan_id == plan_id),
        (NurtureStepExecution.is_deleted == False),  # noqa: E712
    )
    rows = (
        await db.execute(
            select(NurtureStepExecution.status, func.count())
            .where(*base_filter)
            .group_by(NurtureStepExecution.status)
        )
    ).all()
    by_status: Dict[str, int] = {s: 0 for s in ("pending", "running", "success", "failed", "dead_letter", "skipped")}
    for status, n in rows:
        by_status[status] = int(n or 0)
    total = sum(by_status.values())
    last = (
        (await db.execute(
            select(NurtureStepExecution.created_at)
            .where(*base_filter)
            .order_by(NurtureStepExecution.created_at.desc())
            .limit(1)
        ))
        .scalar()
    )
    return {
        "plan_id": str(plan_id),
        "total_attempts": total,
        "by_status": by_status,
        "completed": by_status["success"],
        "failed": by_status["failed"],
        "dead_lettered": by_status["dead_letter"],
        "in_flight": by_status["running"] + by_status["pending"],
        "last_activity_at": to_utc(last).isoformat() if last else None,
    }
