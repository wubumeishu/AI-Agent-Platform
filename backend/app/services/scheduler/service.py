"""Scheduler Service (t_wf_003) - CRUD + next-run computation + execution tracking.

Business layer for the ``WorkflowScheduler`` entity introduced by t_wf_001.
Depends on:
    - WorkflowScheduler (app.db.models.workflow_runtime)
    - ExecutionLog      (app.db.models.workflow)  - execution state tracking
    - cron_parser / schedule_calc (pure, unit-testable)

Kept DB-session-injected (like ExecutionLogService) so it is mockable in
unit tests without a live Postgres.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow import ExecutionLog, TRIGGER_TYPES
from app.db.models.workflow_runtime import (
    WorkflowScheduler,
    SCHEDULE_TYPES,
)
from app.schemas.scheduler import (
    SchedulerCreate,
    SchedulerUpdate,
    SchedulerResponse,
    SchedulerListResponse,
    SchedulerTriggerRequest,
    SchedulerTriggerResponse,
)
from app.services.scheduler.schedule_calc import (
    ScheduleConfigError,
    compute_next_fire,
)
from app.services.scheduler.cron_parser import parse_cron
from app.services.scheduler.engine import get_scheduler_engine

logger = logging.getLogger(__name__)


def _json_safe(value):
    """Coerce a dict to JSON-serializable form for JSONB storage.

    Raw UUID/datetime values must become strings (Postgres JSONB via the
    default serializer rejects them). None / non-dict pass through.
    """
    if not isinstance(value, dict):
        return value
    out = {}
    for k, v in value.items():
        if isinstance(v, UUID):
            out[str(k)] = str(v)
        elif isinstance(v, datetime):
            out[str(k)] = v.isoformat()
        else:
            out[str(k)] = v
    return out


class SchedulerConfigError(ValueError):
    """Public-facing invalid scheduler configuration (4xx in the API)."""


class SchedulerNotFound(LookupError):
    """Scheduler id does not exist or is deleted."""


class SchedulerService:
    """CRUD + schedule computation + execution state tracking."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========== CRUD ==========

    async def create(self, data: SchedulerCreate) -> SchedulerResponse:
        """Create a scheduler; cron expressions are validated up front."""
        self._validate_config(
            data.schedule_type, data.cron_expression, data.interval_seconds
        )
        now = datetime.now(timezone.utc)
        sched = WorkflowScheduler(
            name=data.name,
            workflow_id=data.workflow_id,
            trigger_id=data.trigger_id,
            schedule_type=data.schedule_type,
            cron_expression=data.cron_expression,
            interval_seconds=data.interval_seconds,
            timezone=data.timezone,
            enabled=data.enabled,
            last_run_at=data.last_run_at,
            created_at=now,
            updated_at=now,
        )
        # Pre-compute next_run_at so the engine and UI have a consistent view.
        try:
            sched.next_run_at = self._compute_next(sched, now)
        except ScheduleConfigError as exc:
            raise SchedulerConfigError(str(exc)) from exc
        self.db.add(sched)
        await self.db.commit()
        await self.db.refresh(sched)
        # P1-3: keep the running engine's in-memory heap in sync with the new
        # row so the schedule takes effect without a restart (DB and memory
        # must not diverge — two sources of truth).
        self._sync_engine_after_create_or_update(sched)
        logger.info(
            "Created scheduler %s (type=%s, enabled=%s, next=%s)",
            sched.id, sched.schedule_type, sched.enabled, sched.next_run_at,
        )
        return self._to_response(sched)

    async def get(self, scheduler_id: UUID) -> Optional[SchedulerResponse]:
        row = await self._get_row(scheduler_id)
        return self._to_response(row) if row else None

    async def list(
        self,
        schedule_type: Optional[str] = None,
        enabled: Optional[bool] = None,
        workflow_id: Optional[UUID] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[SchedulerResponse], int]:
        """List schedulers with filtering + pagination (newest first)."""
        query = select(WorkflowScheduler).where(
            WorkflowScheduler.is_deleted == False  # noqa: E712
        )
        if schedule_type:
            query = query.where(WorkflowScheduler.schedule_type == schedule_type)
        if enabled is not None:
            query = query.where(WorkflowScheduler.enabled == enabled)
        if workflow_id:
            query = query.where(WorkflowScheduler.workflow_id == workflow_id)

        total = (
            await self.db.execute(
                select(func.count()).select_from(query.subquery())
            )
        ).scalar_one()

        rows = (
            await self.db.execute(
                query.order_by(WorkflowScheduler.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return [self._to_response(r) for r in rows], total

    async def update(
        self, scheduler_id: UUID, data: SchedulerUpdate
    ) -> Optional[SchedulerResponse]:
        """Partial update; any schedule-defining field change recomputes next_run_at."""
        row = await self._get_row(scheduler_id)
        if row is None:
            return None

        changed_schedule = False
        if data.name is not None:
            row.name = data.name
        if data.workflow_id is not None:
            row.workflow_id = data.workflow_id
        if data.trigger_id is not None:
            row.trigger_id = data.trigger_id
        if data.schedule_type is not None:
            row.schedule_type = data.schedule_type
            changed_schedule = True
        if data.cron_expression is not None:
            row.cron_expression = data.cron_expression
            changed_schedule = True
        if data.interval_seconds is not None:
            row.interval_seconds = data.interval_seconds
            changed_schedule = True
        if data.timezone is not None:
            row.timezone = data.timezone
            changed_schedule = True
        if data.enabled is not None:
            row.enabled = data.enabled
        if data.last_run_at is not None:
            row.last_run_at = data.last_run_at

        if changed_schedule or data.enabled is not None:
            self._validate_config(
                row.schedule_type, row.cron_expression, row.interval_seconds
            )
            now = datetime.now(timezone.utc)
            try:
                row.next_run_at = (
                    self._compute_next(row, now) if row.enabled else None
                )
            except ScheduleConfigError as exc:
                # Keep the row but surface the problem via 4xx at the router.
                raise SchedulerConfigError(str(exc)) from exc
        row.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(row)
        # P1-3: a schedule/enabled change must re-arm (or drop) the running
        # engine's in-memory heap so the new next_run_at takes effect live.
        self._sync_engine_after_create_or_update(row)
        logger.info("Updated scheduler %s", scheduler_id)
        return self._to_response(row)

    async def delete(self, scheduler_id: UUID) -> bool:
        """Soft delete. Returns False when the id was unknown/already deleted."""
        row = await self._get_row(scheduler_id)
        if row is None:
            return False
        row.is_deleted = True
        row.enabled = False
        row.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        # P1-3: drop any pending fires for the removed schedule from the
        # running engine's heap so a soft-deleted row cannot still fire.
        self._disarm_engine(scheduler_id)
        logger.info("Soft-deleted scheduler %s", scheduler_id)
        return True

    # ---------- P1-3: engine re-arm (DB <-> memory consistency) ----------

    def _sync_engine_after_create_or_update(self, row: WorkflowScheduler) -> None:
        """Re-arm the running engine's heap for ``row`` (no-op when not armed).

        The engine only fires from its in-memory min-heap, but this service
        recomputes/persists ``next_run_at`` on create/update. Without a push
        the two diverge: a live engine keeps firing the *old* time (or never
        picks up a brand-new schedule) until a restart. We therefore:
          * disarm any stale pending fires for the scheduler, then
          * re-arm from the freshly computed ``next_run_at`` when enabled.
        Best-effort: an engine hiccup must never break the persisted CRUD
        operation, so failures are logged, not raised.
        """
        try:
            engine = get_scheduler_engine()
            # Clear any now-stale entries before re-arming from the new value.
            engine.disarm(row.id)
            if row.enabled and row.next_run_at is not None:
                engine.arm(row.id, row.next_run_at)
        except Exception:  # pragma: no cover - defensive, never break CRUD
            logger.exception(
                "Failed to sync engine heap for scheduler %s (P1-3)", row.id
            )

    def _disarm_engine(self, scheduler_id: UUID) -> None:
        """Remove pending fires for a deleted/disabled schedule (P1-3)."""
        try:
            get_scheduler_engine().disarm(scheduler_id)
        except Exception:  # pragma: no cover - defensive, never break CRUD
            logger.exception(
                "Failed to disarm engine heap for scheduler %s (P1-3)",
                scheduler_id,
            )

    # ========== State tracking ==========

    async def record_execution(
        self,
        scheduler_id: UUID,
        status: str = "success",
        input_params: Optional[dict] = None,
        output_result: Optional[dict] = None,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> Optional[ExecutionLog]:
        """Append an ExecutionLog row (execution_type='scheduler') for a fire.

        On success also advances the scheduler's last_run_at / next_run_at so
        the schedule state stays observable and consistent.
        """
        row = await self._get_row(scheduler_id)
        if row is None:
            return None
        trigger_type = "cron" if row.schedule_type == "cron" else "scheduled"
        log = ExecutionLog(
            execution_type="scheduler",
            trigger_type=trigger_type,
            status=status,
            workflow_id=row.workflow_id,
            input_params=_json_safe(input_params) or {"scheduler_id": str(row.id)},
            output_result=_json_safe(output_result),
            error_message=error_message,
            error_code=error_code,
            started_at=row.last_run_at,
            finished_at=datetime.now(timezone.utc),
            metadata_={"scheduler": str(row.id), "name": row.name},
        )
        self.db.add(log)

        if status in ("success", "failed"):
            row.last_run_at = datetime.now(timezone.utc)
            try:
                row.next_run_at = self._compute_next(row, row.last_run_at)
            except ScheduleConfigError:
                row.next_run_at = None
        row.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(log)
        logger.info(
            "Recorded scheduler execution %s -> %s", scheduler_id, status
        )
        return log

    # ========== Internal helpers ==========

    async def _get_row(self, scheduler_id: UUID) -> Optional[WorkflowScheduler]:
        result = await self.db.execute(
            select(WorkflowScheduler).where(
                WorkflowScheduler.id == scheduler_id,
                WorkflowScheduler.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    def _validate_config(
        self,
        schedule_type: Optional[str],
        cron_expression: Optional[str],
        interval_seconds: Optional[int],
    ) -> None:
        """Fail fast on impossible configs; raises SchedulerConfigError."""
        if schedule_type not in SCHEDULE_TYPES:
            raise SchedulerConfigError(
                f"schedule_type must be one of {SCHEDULE_TYPES}, got {schedule_type!r}"
            )
        if schedule_type == "cron":
            if not cron_expression:
                raise SchedulerConfigError(
                    "cron_expression is required when schedule_type=cron"
                )
            try:
                parse_cron(cron_expression)
            except ValueError as exc:
                raise SchedulerConfigError(f"invalid cron expression: {exc}") from exc
        elif schedule_type == "interval":
            if interval_seconds is None or interval_seconds <= 0:
                raise SchedulerConfigError(
                    "interval_seconds must be a positive integer when "
                    "schedule_type=interval"
                )

    def _compute_next(
        self, row: WorkflowScheduler, now: datetime
    ) -> Optional[datetime]:
        """Next fire strictly after ``now`` (interval uses rolling window)."""
        if row.schedule_type == "interval":
            return compute_next_fire(row, now, now=now)
        return compute_next_fire(row, now)

    @staticmethod
    def _to_response(row: WorkflowScheduler) -> SchedulerResponse:
        return SchedulerResponse(
            id=row.id,
            name=row.name,
            workflow_id=row.workflow_id,
            trigger_id=row.trigger_id,
            schedule_type=row.schedule_type,
            cron_expression=row.cron_expression,
            interval_seconds=row.interval_seconds,
            timezone=row.timezone,
            enabled=row.enabled,
            last_run_at=row.last_run_at,
            next_run_at=row.next_run_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
