"""Execution Log Service - record, query, and clean up workflow executions.

This service is the observability layer for the queue + worker execution
engine (t_wf_004). It:

- records each execution with full input/output + error capture
- supports execution-history querying with filtering + pagination
- enforces a retention cleanup policy ("keep the most recent N records")

It depends only on the DB session (AsyncSession), mirroring the existing
Memory/Decision services so it is independently unit-testable with mocks.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow import ExecutionLog, Workflow, WorkflowTrigger, WorkflowCondition, WorkflowAction
from app.schemas.workflow import (
    ExecutionLogCreate,
    ExecutionLogUpdate,
    ExecutionLogResponse,
    ExecutionHistoryRequest,
    ExecutionLogCleanupRequest,
    ExecutionLogCleanupResponse,
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    TriggerCreate,
    TriggerUpdate,
    TriggerResponse,
    ConditionCreate,
    ConditionUpdate,
    ConditionResponse,
    ActionCreate,
    ActionUpdate,
    ActionResponse,
    WorkflowDetailResponse,
    build_workflow_detail,
)

logger = logging.getLogger(__name__)


class ExecutionLogService:
    """Service for recording and querying workflow execution logs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========== Recording ==========

    async def create_log(self, data: ExecutionLogCreate) -> ExecutionLogResponse:
        """Record a new execution log (typically at execution start)."""
        # Auto-fill start time if not provided.
        started_at = data.started_at or datetime.now(timezone.utc)
        log = ExecutionLog(
            execution_type=data.execution_type,
            trigger_type=data.trigger_type,
            status=data.status,
            workflow_id=data.workflow_id,
            queue_id=data.queue_id,
            worker_id=data.worker_id,
            task_id=data.task_id,
            input_params=data.input_params or {},
            output_result=data.output_result,
            error_message=data.error_message,
            error_code=data.error_code,
            retry_count=data.retry_count or 0,
            started_at=started_at,
            finished_at=data.finished_at,
            duration_ms=data.duration_ms,
            metadata_=data.metadata or {},
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        logger.info(
            "Created execution log %s (type=%s, status=%s, task=%s)",
            log.id, log.execution_type, log.status, log.task_id,
        )
        return ExecutionLogResponse.from_model(log)

    async def get_log(self, log_id: UUID) -> Optional[ExecutionLogResponse]:
        """Fetch a single execution log by ID, or None."""
        result = await self.db.execute(
            select(ExecutionLog).where(
                ExecutionLog.id == log_id,
                ExecutionLog.is_deleted == False,  # noqa: E712
            )
        )
        log = result.scalar_one_or_none()
        if log is None:
            return None
        return ExecutionLogResponse.from_model(log)

    async def update_log(
        self, log_id: UUID, data: ExecutionLogUpdate
    ) -> Optional[ExecutionLogResponse]:
        """Update an execution log (progress, terminal state, error).

        When the status moves to a terminal state and no ``finished_at`` was
        supplied, it is auto-stamped from the now().
        """
        result = await self.db.execute(
            select(ExecutionLog).where(
                ExecutionLog.id == log_id,
                ExecutionLog.is_deleted == False,  # noqa: E712
            )
        )
        log = result.scalar_one_or_none()
        if log is None:
            return None

        if data.status is not None:
            log.status = data.status
        if data.output_result is not None:
            log.output_result = data.output_result
        if data.error_message is not None:
            log.error_message = data.error_message
        if data.error_code is not None:
            log.error_code = data.error_code
        if data.retry_count is not None:
            log.retry_count = data.retry_count
        if data.started_at is not None:
            log.started_at = data.started_at
        if data.finished_at is not None:
            log.finished_at = data.finished_at
        if data.duration_ms is not None:
            log.duration_ms = data.duration_ms
        if data.metadata is not None:
            log.metadata_ = data.metadata

        # Auto-stamp finish time on terminal transition when caller omitted it.
        terminal = {"success", "failed", "cancelled", "timeout"}
        if data.status in terminal and log.finished_at is None:
            log.finished_at = datetime.now(timezone.utc)

        # Normalise to timezone-aware UTC so the duration math below never
        # mixes naive and aware datetimes (a create-time caller may pass a
        # naive started_at via the API; t_a986f957 regression: PUT /
        # execution-logs/{id} 500ed on naive finished_at - aware started_at).
        if log.started_at is not None and log.started_at.tzinfo is None:
            log.started_at = log.started_at.replace(tzinfo=timezone.utc)
        if log.finished_at is not None and log.finished_at.tzinfo is None:
            log.finished_at = log.finished_at.replace(tzinfo=timezone.utc)

        # Auto-compute duration if both bounds are known and it was not set.
        if log.duration_ms is None and log.started_at is not None and log.finished_at is not None:
            log.duration_ms = (
                log.finished_at - log.started_at
            ).total_seconds() * 1000.0

        log.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(log)
        logger.info(
            "Updated execution log %s -> status=%s", log.id, log.status,
        )
        return ExecutionLogResponse.from_model(log)

    # ========== Execution history / querying ==========

    async def list_logs(
        self,
        execution_type: Optional[str] = None,
        trigger_type: Optional[str] = None,
        status: Optional[str] = None,
        workflow_id: Optional[UUID] = None,
        queue_id: Optional[UUID] = None,
        worker_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        started_after: Optional[datetime] = None,
        started_before: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[ExecutionLogResponse], int]:
        """List execution logs with filtering + pagination (newest first)."""
        query = select(ExecutionLog).where(ExecutionLog.is_deleted == False)  # noqa: E712

        if execution_type:
            query = query.where(ExecutionLog.execution_type == execution_type)
        if trigger_type:
            query = query.where(ExecutionLog.trigger_type == trigger_type)
        if status:
            query = query.where(ExecutionLog.status == status)
        if workflow_id:
            query = query.where(ExecutionLog.workflow_id == workflow_id)
        if queue_id:
            query = query.where(ExecutionLog.queue_id == queue_id)
        if worker_id:
            query = query.where(ExecutionLog.worker_id == worker_id)
        if task_id:
            query = query.where(ExecutionLog.task_id == task_id)
        if started_after:
            query = query.where(ExecutionLog.started_at >= started_after)
        if started_before:
            query = query.where(ExecutionLog.started_at <= started_before)

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        query = (
            query.order_by(ExecutionLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(query)
        logs = result.scalars().all()
        return [ExecutionLogResponse.from_model(l) for l in logs], total

    async def get_history(self, request: ExecutionHistoryRequest) -> Tuple[List[ExecutionLogResponse], int]:
        """Execution-history query (wrapper over list_logs using a request body)."""
        return await self.list_logs(
            execution_type=request.execution_type,
            trigger_type=request.trigger_type,
            status=request.status,
            workflow_id=request.workflow_id,
            queue_id=request.queue_id,
            worker_id=request.worker_id,
            task_id=request.task_id,
            started_after=request.started_after,
            started_before=request.started_before,
            page=request.page,
            page_size=request.page_size,
        )

    async def get_failed_executions(
        self, limit: int = 100
    ) -> List[ExecutionLogResponse]:
        """Recent failed/timeout executions (for troubleshooting)."""
        query = (
            select(ExecutionLog)
            .where(
                ExecutionLog.is_deleted == False,  # noqa: E712
                ExecutionLog.status.in_(["failed", "timeout"]),
            )
            .order_by(ExecutionLog.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        logs = result.scalars().all()
        return [ExecutionLogResponse.from_model(l) for l in logs]

    # ========== Cleanup policy (retention) ==========

    async def clean_logs(self, data: ExecutionLogCleanupRequest) -> ExecutionLogCleanupResponse:
        """Keep only the most recent ``retain`` non-deleted logs.

        Older records are soft-deleted so audit tooling can recover them if
        the flag is ever set back. Returns how many were cleaned.
        """
        retain = data.retain

        # Count total non-deleted logs.
        total = (
            await self.db.execute(
                select(func.count()).select_from(ExecutionLog).where(
                    ExecutionLog.is_deleted == False  # noqa: E712
                )
            )
        ).scalar_one()

        if total <= retain:
            logger.info(
                "Execution-log cleanup: %d records <= retain=%d, nothing to clean",
                total, retain,
            )
            return ExecutionLogCleanupResponse(cleaned=0, remaining=total, retain=retain)

        # Find the boundary id: the NEWEST of the oldest (total - retain) rows.
        # The oldest rows are those with the lowest created_at. We select the
        # id that sits exactly at the cutoff (created_at of the row ranked
        # (total - retain) from the oldest).
        #
        # To keep this robust with only indexed columns, we mark soft-delete
        # on every row whose created_at is strictly older than the Nth newest.
        # We fetch that cutoff timestamp.
        result = await self.db.execute(
            select(ExecutionLog.created_at)
            .where(ExecutionLog.is_deleted == False)  # noqa: E712
            .order_by(ExecutionLog.created_at.asc())
            .offset(total - retain)
            .limit(1)
        )
        cutoff_row = result.first()
        if not cutoff_row:
            return ExecutionLogCleanupResponse(cleaned=0, remaining=total, retain=retain)
        cutoff_ts = cutoff_row[0]

        # Soft-delete everything strictly older than the cutoff.
        update_result = await self.db.execute(
            update(ExecutionLog)
            .where(
                ExecutionLog.is_deleted == False,  # noqa: E712
                ExecutionLog.created_at < cutoff_ts,
            )
            .values(is_deleted=True, updated_at=datetime.now(timezone.utc))
        )
        cleaned = update_result.rowcount or 0
        await self.db.commit()

        remaining = total - cleaned
        logger.info(
            "Execution-log cleanup: soft-deleted %d, retained %d (retain=%d)",
            cleaned, remaining, retain,
        )
        return ExecutionLogCleanupResponse(cleaned=cleaned, remaining=remaining, retain=retain)

    # ========== Health ==========

    def health(self) -> dict:
        """Self-report for observability / integration tests."""
        return {"service": "execution-log-service", "db_enabled": self.db is not None}


class WorkflowNotFoundError(Exception):
    """A workflow / trigger / condition / action was not found (or is deleted)."""

    def __init__(self, entity: str, entity_id: Optional[UUID] = None):
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} not found: {entity_id}")


class WorkflowService:
    """CRUD + hierarchy management for the workflow configuration model.

    Hierarchy:  Workflow 1--N Trigger 1--N Condition 1--N Action

    Rules:
      - every lookup excludes soft-deleted rows
      - deleting a parent soft-deletes its children too
        (child rows also carry FK ON DELETE CASCADE for hard deletes)
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- internal lookups ----------

    async def _get_workflow(self, workflow_id: UUID) -> Optional[Workflow]:
        result = await self.db.execute(
            select(Workflow).where(
                Workflow.id == workflow_id, Workflow.is_deleted == False  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def _get_trigger(self, trigger_id: UUID) -> Optional[WorkflowTrigger]:
        result = await self.db.execute(
            select(WorkflowTrigger).where(
                WorkflowTrigger.id == trigger_id,
                WorkflowTrigger.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def _get_condition(self, condition_id: UUID) -> Optional[WorkflowCondition]:
        result = await self.db.execute(
            select(WorkflowCondition).where(
                WorkflowCondition.id == condition_id,
                WorkflowCondition.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def _get_action(self, action_id: UUID) -> Optional[WorkflowAction]:
        result = await self.db.execute(
            select(WorkflowAction).where(
                WorkflowAction.id == action_id,
                WorkflowAction.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    # ========== Workflow CRUD ==========

    async def create_workflow(self, data: WorkflowCreate) -> WorkflowResponse:
        now = datetime.now(timezone.utc)
        workflow = Workflow(
            id=uuid4(),
            name=data.name,
            description=data.description,
            workflow_type=data.workflow_type,
            status=data.status,
            config=data.config or {},
            execution_policy=data.execution_policy or {},
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.db.add(workflow)
        await self.db.commit()
        await self.db.refresh(workflow)
        logger.info("Created workflow %s (%s, status=%s)", workflow.id, workflow.name, workflow.status)
        return WorkflowResponse.model_validate(workflow)

    async def get_workflow(self, workflow_id: UUID) -> Optional[WorkflowResponse]:
        workflow = await self._get_workflow(workflow_id)
        if workflow is None:
            return None
        return WorkflowResponse.model_validate(workflow)

    async def list_workflows(
        self,
        status: Optional[str] = None,
        workflow_type: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[WorkflowResponse], int]:
        query = select(Workflow).where(Workflow.is_deleted == False)  # noqa: E712
        if status:
            query = query.where(Workflow.status == status)
        if workflow_type:
            query = query.where(Workflow.workflow_type == workflow_type)
        if search:
            query = query.where(Workflow.name.ilike(f"%{search}%"))

        total = (
            await self.db.execute(select(func.count()).select_from(query.subquery()))
        ).scalar_one()
        query = (
            query.order_by(Workflow.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(query)
        items = [WorkflowResponse.model_validate(w) for w in result.scalars().all()]
        return items, total

    async def update_workflow(
        self, workflow_id: UUID, data: WorkflowUpdate
    ) -> Optional[WorkflowResponse]:
        workflow = await self._get_workflow(workflow_id)
        if workflow is None:
            return None

        for field_name in ("name", "description", "workflow_type", "status"):
            value = getattr(data, field_name)
            if value is not None:
                setattr(workflow, field_name, value)
        if data.config is not None:
            workflow.config = data.config
        if data.execution_policy is not None:
            workflow.execution_policy = data.execution_policy
        # Bump version on any content change (no versioning engine in this slice).
        workflow.version += 1
        workflow.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(workflow)
        logger.info("Updated workflow %s (version=%d)", workflow.id, workflow.version)
        return WorkflowResponse.model_validate(workflow)

    async def delete_workflow(self, workflow_id: UUID) -> bool:
        """Soft-delete a workflow and its entire trigger/condition/action tree."""
        workflow = await self._get_workflow(workflow_id)
        if workflow is None:
            return False

        now = datetime.now(timezone.utc)
        trigger_ids = [
            r for r in
            (await self.db.execute(
                select(WorkflowTrigger.id).where(
                    WorkflowTrigger.workflow_id == workflow_id,
                    WorkflowTrigger.is_deleted == False,  # noqa: E712
                )
            )).scalars().all()
        ]
        condition_ids: List[UUID] = []
        if trigger_ids:
            condition_ids = [
                r for r in
                (await self.db.execute(
                    select(WorkflowCondition.id).where(
                        WorkflowCondition.trigger_id.in_(trigger_ids),
                        WorkflowCondition.is_deleted == False,  # noqa: E712
                    )
                )).scalars().all()
            ]

        await self.db.execute(
            update(WorkflowTrigger)
            .where(WorkflowTrigger.workflow_id == workflow_id,
                   WorkflowTrigger.is_deleted == False)  # noqa: E712
            .values(is_deleted=True, updated_at=now)
        )
        if condition_ids:
            await self.db.execute(
                update(WorkflowCondition)
                .where(WorkflowCondition.id.in_(condition_ids))
                .values(is_deleted=True, updated_at=now)
            )
            await self.db.execute(
                update(WorkflowAction)
                .where(WorkflowAction.condition_id.in_(condition_ids))
                .values(is_deleted=True, updated_at=now)
            )
        workflow.is_deleted = True
        workflow.updated_at = now
        await self.db.commit()
        logger.info("Deleted workflow %s (+%d triggers, +%d conditions)", workflow.id, len(trigger_ids), len(condition_ids))
        return True

    # ========== Trigger CRUD ==========

    async def create_trigger(self, workflow_id: UUID, data: TriggerCreate) -> Optional[TriggerResponse]:
        workflow = await self._get_workflow(workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError("Workflow", workflow_id)
        trigger = WorkflowTrigger(
            id=uuid4(),
            workflow_id=workflow_id,
            name=data.name,
            trigger_type=data.trigger_type,
            spec=data.spec or {},
            enabled=data.enabled,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.db.add(trigger)
        await self.db.commit()
        await self.db.refresh(trigger)
        logger.info("Created trigger %s on workflow %s", trigger.id, workflow_id)
        return TriggerResponse.model_validate(trigger)

    async def list_triggers(self, workflow_id: UUID) -> List[TriggerResponse]:
        workflow = await self._get_workflow(workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError("Workflow", workflow_id)
        result = await self.db.execute(
            select(WorkflowTrigger)
            .where(
                WorkflowTrigger.workflow_id == workflow_id,
                WorkflowTrigger.is_deleted == False,  # noqa: E712
            )
            .order_by(WorkflowTrigger.created_at)
        )
        return [TriggerResponse.model_validate(t) for t in result.scalars().all()]

    async def update_trigger(
        self, trigger_id: UUID, data: TriggerUpdate
    ) -> Optional[TriggerResponse]:
        trigger = await self._get_trigger(trigger_id)
        if trigger is None:
            return None
        if data.name is not None:
            trigger.name = data.name
        if data.enabled is not None:
            trigger.enabled = data.enabled
        if data.trigger_type is not None:
            trigger.trigger_type = data.trigger_type
        if data.spec is not None:
            trigger.spec = data.spec
        trigger.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(trigger)
        logger.info("Updated trigger %s", trigger.id)
        return TriggerResponse.model_validate(trigger)

    async def delete_trigger(self, trigger_id: UUID) -> bool:
        """Soft-delete a trigger and its condition/action subtree."""
        trigger = await self._get_trigger(trigger_id)
        if trigger is None:
            return False
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(WorkflowCondition)
            .where(WorkflowCondition.trigger_id == trigger_id,
                   WorkflowCondition.is_deleted == False)  # noqa: E712
            .values(is_deleted=True, updated_at=now)
        )
        cond_ids = [
            r for r in
            (await self.db.execute(
                select(WorkflowCondition.id).where(
                    WorkflowCondition.trigger_id == trigger_id,
                    WorkflowCondition.is_deleted == False,  # noqa: E712
                )
            )).scalars().all()
        ]
        if cond_ids:
            await self.db.execute(
                update(WorkflowAction)
                .where(WorkflowAction.condition_id.in_(cond_ids))
                .values(is_deleted=True, updated_at=now)
            )
        trigger.is_deleted = True
        trigger.updated_at = now
        await self.db.commit()
        logger.info("Deleted trigger %s", trigger_id)
        return True

    # ========== Condition CRUD ==========

    async def create_condition(self, trigger_id: UUID, data: ConditionCreate) -> Optional[ConditionResponse]:
        trigger = await self._get_trigger(trigger_id)
        if trigger is None:
            raise WorkflowNotFoundError("WorkflowTrigger", trigger_id)
        condition = WorkflowCondition(
            id=uuid4(),
            trigger_id=trigger_id,
            name=data.name,
            expression=data.expression or {},
            logic=data.logic,
            priority=data.priority,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.db.add(condition)
        await self.db.commit()
        await self.db.refresh(condition)
        logger.info("Created condition %s on trigger %s", condition.id, trigger_id)
        return ConditionResponse.model_validate(condition)

    async def list_conditions(self, trigger_id: UUID) -> List[ConditionResponse]:
        trigger = await self._get_trigger(trigger_id)
        if trigger is None:
            raise WorkflowNotFoundError("WorkflowTrigger", trigger_id)
        result = await self.db.execute(
            select(WorkflowCondition)
            .where(
                WorkflowCondition.trigger_id == trigger_id,
                WorkflowCondition.is_deleted == False,  # noqa: E712
            )
            .order_by(WorkflowCondition.priority, WorkflowCondition.created_at)
        )
        return [ConditionResponse.model_validate(c) for c in result.scalars().all()]

    async def update_condition(
        self, condition_id: UUID, data: ConditionUpdate
    ) -> Optional[ConditionResponse]:
        condition = await self._get_condition(condition_id)
        if condition is None:
            return None
        if data.name is not None:
            condition.name = data.name
        if data.expression is not None:
            condition.expression = data.expression
        if data.logic is not None:
            condition.logic = data.logic
        if data.priority is not None:
            condition.priority = data.priority
        condition.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(condition)
        logger.info("Updated condition %s", condition.id)
        return ConditionResponse.model_validate(condition)

    async def delete_condition(self, condition_id: UUID) -> bool:
        """Soft-delete a condition and its actions."""
        condition = await self._get_condition(condition_id)
        if condition is None:
            return False
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(WorkflowAction)
            .where(WorkflowAction.condition_id == condition_id,
                   WorkflowAction.is_deleted == False)  # noqa: E712
            .values(is_deleted=True, updated_at=now)
        )
        condition.is_deleted = True
        condition.updated_at = now
        await self.db.commit()
        logger.info("Deleted condition %s", condition_id)
        return True

    # ========== Action CRUD ==========

    async def create_action(self, condition_id: UUID, data: ActionCreate) -> Optional[ActionResponse]:
        condition = await self._get_condition(condition_id)
        if condition is None:
            raise WorkflowNotFoundError("WorkflowCondition", condition_id)
        action = WorkflowAction(
            id=uuid4(),
            condition_id=condition_id,
            name=data.name,
            action_type=data.action_type,
            params=data.params or {},
            priority=data.priority,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.db.add(action)
        await self.db.commit()
        await self.db.refresh(action)
        logger.info("Created action %s on condition %s", action.id, condition_id)
        return ActionResponse.model_validate(action)

    async def list_actions(self, condition_id: UUID) -> List[ActionResponse]:
        condition = await self._get_condition(condition_id)
        if condition is None:
            raise WorkflowNotFoundError("WorkflowCondition", condition_id)
        result = await self.db.execute(
            select(WorkflowAction)
            .where(
                WorkflowAction.condition_id == condition_id,
                WorkflowAction.is_deleted == False,  # noqa: E712
            )
            .order_by(WorkflowAction.priority, WorkflowAction.created_at)
        )
        return [ActionResponse.model_validate(a) for a in result.scalars().all()]

    async def update_action(
        self, action_id: UUID, data: ActionUpdate
    ) -> Optional[ActionResponse]:
        action = await self._get_action(action_id)
        if action is None:
            return None
        if data.name is not None:
            action.name = data.name
        if data.action_type is not None:
            action.action_type = data.action_type
        if data.params is not None:
            action.params = data.params
        if data.priority is not None:
            action.priority = data.priority
        action.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(action)
        logger.info("Updated action %s", action.id)
        return ActionResponse.model_validate(action)

    async def delete_action(self, action_id: UUID) -> bool:
        action = await self._get_action(action_id)
        if action is None:
            return False
        action.is_deleted = True
        action.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        logger.info("Deleted action %s", action_id)
        return True

    # ========== Detail view ==========

    async def get_workflow_detail(self, workflow_id: UUID) -> Optional[WorkflowDetailResponse]:
        """Full nested tree: workflow -> triggers -> conditions -> actions."""
        workflow = await self._get_workflow(workflow_id)
        if workflow is None:
            return None

        triggers_result = await self.db.execute(
            select(WorkflowTrigger)
            .where(
                WorkflowTrigger.workflow_id == workflow_id,
                WorkflowTrigger.is_deleted == False,  # noqa: E712
            )
            .order_by(WorkflowTrigger.created_at)
        )
        triggers = [TriggerResponse.model_validate(t) for t in triggers_result.scalars().all()]

        trigger_ids = [t.id for t in triggers]
        conditions_by_trigger: Dict[UUID, List[ConditionResponse]] = {t.id: [] for t in triggers}
        actions_by_condition: Dict[UUID, List[ActionResponse]] = {}

        if trigger_ids:
            conds_result = await self.db.execute(
                select(WorkflowCondition)
                .where(
                    WorkflowCondition.trigger_id.in_(trigger_ids),
                    WorkflowCondition.is_deleted == False,  # noqa: E712
                )
                .order_by(WorkflowCondition.priority, WorkflowCondition.created_at)
            )
            for c in conds_result.scalars().all():
                conditions_by_trigger.setdefault(c.trigger_id, []).append(
                    ConditionResponse.model_validate(c)
                )

            cond_ids = [c.id for cs in conditions_by_trigger.values() for c in cs]
            if cond_ids:
                acts_result = await self.db.execute(
                    select(WorkflowAction)
                    .where(
                        WorkflowAction.condition_id.in_(cond_ids),
                        WorkflowAction.is_deleted == False,  # noqa: E712
                    )
                    .order_by(WorkflowAction.priority, WorkflowAction.created_at)
                )
                for a in acts_result.scalars().all():
                    actions_by_condition.setdefault(a.condition_id, []).append(
                        ActionResponse.model_validate(a)
                    )

        return build_workflow_detail(workflow, triggers, conditions_by_trigger, actions_by_condition)

    # ========== Health ==========

    def health(self) -> dict:
        """Self-report for observability / integration tests."""
        return {"service": "workflow-service", "db_enabled": self.db is not None}
