"""Workflow framework CRUD services (Phase 4 / t_wf_001 - scaffold layer).

Scaffold-only business layer: it provides uniform, generic CRUD for the
workflow subsystem entities. No execution engine, no cron evaluation, no
cross-module integration (those are later waves: t_wf_002/t_wf_003/
t_wf_004/t_wf_006/t_wf_007).

Design
------
``_GenericCRUD`` is a small, table-agnostic CRUD engine parameterised by the
ORM model + Pydantic create/response schemas + a default sort column. It
implements the shared behavior the card calls for:

- list with filtering (equality on scalar fields), sorting, pagination
- get by id
- create (commit + refresh)
- update (partial, via ``model_dump(exclude_unset=True)``)
- soft delete (``is_deleted = True``)

Each entity gets a thin service class that binds the engine to its model and
exposes the usual verbs. This keeps the code DRY and every entity behaving
identically, while remaining independently unit-testable with a mocked
AsyncSession.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy import asc, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


logger = logging.getLogger(__name__)


class NotFoundError(Exception):
    """Raised when a create/update fails an integrity check (e.g. unique)."""


class ConflictError(Exception):
    """Raised when a create/update violates a uniqueness constraint.

    t_a986f957: ``WorkflowQueue.name`` (and other unique columns) used to
    surface as an unhandled ``IntegrityError`` → HTTP 500. Routers map this
    to 409 Conflict instead.
    """

    def __init__(self, model: str, detail: str = ""):
        self.model = model
        self.detail = detail
        super().__init__(f"{model} uniqueness conflict: {detail}" if detail else f"{model} uniqueness conflict")


M = TypeVar("M", bound=DeclarativeBase)
CreateSchema = TypeVar("CreateSchema", bound=BaseModel)
UpdateSchema = TypeVar("UpdateSchema", bound=BaseModel)
ResponseSchema = TypeVar("ResponseSchema", bound=BaseModel)


class _GenericCRUD:
    """Table-agnostic CRUD engine.

    Args:
        db:      active AsyncSession (from a parent service)
        model:   the ORM model class
        create:  Pydantic create schema (or None for read-only lists)
        update:  Pydantic update schema (or None)
        resp:    Pydantic response schema (uses ``from_attributes``)
        default_sort: column name used for the default ordering
    """

    def __init__(
        self,
        db: AsyncSession,
        model: type,
        resp: Type[ResponseSchema],
        create: Optional[Type[CreateSchema]] = None,
        update: Optional[Type[UpdateSchema]] = None,
        default_sort: str = "created_at",
        filter_fields: Optional[List[str]] = None,
    ):
        self.db = db
        self.model = model
        self.resp = resp
        self.create_schema = create   # Pydantic Create schema (renamed to avoid shadowing create())
        self.update_schema = update   # Pydantic Update schema (renamed to avoid shadowing update())
        self.default_sort = default_sort
        # scalar columns allowed as equality filters (for list queries).
        self.filter_fields = filter_fields or []

    # ---- filtering / sorting / pagination ----

    def _apply_filters(self, query, params: Dict[str, Any]):
        for field in self.filter_fields:
            if params.get(field) is not None:
                query = query.where(getattr(self.model, field) == params[field])
        return query

    def _soft_deleted(self):
        return getattr(self.model, "is_deleted", None)

    async def list(
        self,
        page: int = 1,
        page_size: int = 20,
        order_by: Optional[str] = None,
        ascending: bool = False,
        **filters,
    ) -> Tuple[List[ResponseSchema], int]:
        """List with filtering + sorting + pagination (returns items, total)."""
        query = select(self.model)
        deleted = self._soft_deleted()
        if deleted is not None:
            query = query.where(deleted == False)  # noqa: E712

        # Apply equality filters only for keys that are real filter fields.
        query = self._apply_filters(query, {k: v for k, v in filters.items() if v is not None})

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        # Sort: default is newest-first on created_at; explicit order_by uses ascending flag.
        sort_col = getattr(self.model, order_by or self.default_sort)
        if not order_by:
            query = query.order_by(desc(sort_col))
        else:
            query = query.order_by(asc(sort_col) if ascending else desc(sort_col))
        query = query.offset((page - 1) * page_size).limit(page_size)

        rows = (await self.db.execute(query)).scalars().all()
        items = [self.resp.model_validate(r) for r in rows]
        return items, total

    async def get(self, instance_id) -> Optional[ResponseSchema]:
        query = select(self.model).where(self.model.id == instance_id)
        deleted = self._soft_deleted()
        if deleted is not None:
            query = query.where(deleted == False)  # noqa: E712
        obj = (await self.db.execute(query)).scalar_one_or_none()
        return self.resp.model_validate(obj) if obj else None

    async def create(self, data: CreateSchema) -> ResponseSchema:
        # Use the full schema dump so model-level defaults (config={}, version=1,
        # status defaults, ...) are materialised on the ORM object deterministically,
        # rather than relying on the DB to apply column defaults at flush time.
        obj = self.model(**data.model_dump())
        self.db.add(obj)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            # t_a986f957: unique-constraint violations (e.g. WorkflowQueue.name)
            # must surface as a clean 409, not a 500.
            raise ConflictError(self.model.__name__) from None
        await self.db.refresh(obj)
        logger.info("Created %s %s", self.model.__name__, obj.id)
        return self.resp.model_validate(obj)

    # P2-3 (t_c94bba06): system columns that must never be writable through
    # the generic update path. Today no framework Update schema exposes them,
    # but the engine is shared and a future schema could; a deny-list makes the
    # guard structural rather than relying on every schema staying clean.
    _SYSTEM_UPDATE_DENYLIST = frozenset({"id", "created_at", "updated_at", "is_deleted"})

    async def update(self, instance_id, data: UpdateSchema) -> Optional[ResponseSchema]:
        query = select(self.model).where(self.model.id == instance_id)
        deleted = self._soft_deleted()
        if deleted is not None:
            query = query.where(deleted == False)  # noqa: E712
        obj = (await self.db.execute(query)).scalar_one_or_none()
        if obj is None:
            return None
        model_cols = {c.name for c in self.model.__table__.columns}
        for field, value in data.model_dump(exclude_unset=True).items():
            if field in self._SYSTEM_UPDATE_DENYLIST:
                # Ignore (don't 400) so a lenient payload still applies the
                # legitimate fields; the overwrite is simply not performed.
                logger.warning(
                    "Ignored system column %r in update of %s %s (P2-3)",
                    field, self.model.__name__, instance_id,
                )
                continue
            if field not in model_cols:
                # Not a real column (e.g. a stale schema field) — skip rather
                # than setattr a stray attribute the ORM will never flush.
                continue
            setattr(obj, field, value)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            # t_a986f957: unique-constraint violations on update -> clean 409.
            raise ConflictError(self.model.__name__) from None
        await self.db.refresh(obj)
        logger.info("Updated %s %s", self.model.__name__, obj.id)
        return self.resp.model_validate(obj)

    async def delete(self, instance_id) -> bool:
        """Soft delete. Returns False when the id does not exist."""
        query = select(self.model).where(self.model.id == instance_id)
        deleted = self._soft_deleted()
        if deleted is not None:
            query = query.where(deleted == False)  # noqa: E712
        obj = (await self.db.execute(query)).scalar_one_or_none()
        if obj is None:
            return False
        if self._soft_deleted() is not None:
            obj.is_deleted = True
        else:
            await self.db.delete(obj)
        await self.db.commit()
        logger.info("Deleted %s %s", self.model.__name__, obj.id)
        return True


# =====================================================================
# Per-entity services (thin, uniform CRUD over the engine)
# =====================================================================

class _ServiceBase:
    def __init__(self, db, model, create, update, resp, filter_fields=None,
                 default_sort="created_at"):
        self._crud = _GenericCRUD(
            db, model, resp, create=create, update=update,
            default_sort=default_sort, filter_fields=filter_fields,
        )

    async def list(self, page=1, page_size=20, order_by=None, ascending=False, **f):
        return await self._crud.list(page, page_size, order_by, ascending, **f)

    async def get(self, instance_id):
        return await self._crud.get(instance_id)

    async def create(self, data):
        return await self._crud.create(data)

    async def update(self, instance_id, data):
        return await self._crud.update(instance_id, data)

    async def delete(self, instance_id):
        return await self._crud.delete(instance_id)


class WorkflowService(_ServiceBase):  # type: ignore[valid-subclass]
    def __init__(self, db: AsyncSession):
        from app.db.models import Workflow
        from app.schemas.workflow_framework import (
            WorkflowCreate,
            WorkflowResponse,
            WorkflowUpdate,
        )
        super().__init__(db, Workflow, WorkflowCreate, WorkflowUpdate,
                         WorkflowResponse, filter_fields=["status", "workflow_type"])

    async def list(self, page=1, page_size=20, order_by=None, ascending=False,
                   status=None, workflow_type=None):
        return await super().list(page, page_size, order_by, ascending,
                                   status=status, workflow_type=workflow_type)


class WorkflowTriggerService(_ServiceBase):
    def __init__(self, db: AsyncSession):
        from app.db.models import WorkflowTrigger
        from app.schemas.workflow_framework import (
            TriggerCreate,
            TriggerResponse,
            TriggerUpdate,
        )
        super().__init__(db, WorkflowTrigger, TriggerCreate, TriggerUpdate,
                         TriggerResponse, filter_fields=["workflow_id", "trigger_type", "enabled"])

    async def list(self, page=1, page_size=20, order_by=None, ascending=False,
                   workflow_id=None, trigger_type=None, enabled=None):
        return await super().list(page, page_size, order_by, ascending,
                                  workflow_id=workflow_id, trigger_type=trigger_type,
                                  enabled=enabled)


class WorkflowConditionService(_ServiceBase):
    def __init__(self, db: AsyncSession):
        from app.db.models import WorkflowCondition
        from app.schemas.workflow_framework import (
            ConditionCreate,
            ConditionResponse,
            ConditionUpdate,
        )
        super().__init__(db, WorkflowCondition, ConditionCreate, ConditionUpdate,
                         ConditionResponse, filter_fields=["trigger_id", "logic"])

    async def list(self, page=1, page_size=20, order_by=None, ascending=False,
                   trigger_id=None, logic=None):
        return await super().list(page, page_size, order_by, ascending,
                                   trigger_id=trigger_id, logic=logic)


class WorkflowActionService(_ServiceBase):
    def __init__(self, db: AsyncSession):
        from app.db.models import WorkflowAction
        from app.schemas.workflow_framework import (
            ActionCreate,
            ActionResponse,
            ActionUpdate,
        )
        super().__init__(db, WorkflowAction, ActionCreate, ActionUpdate,
                         ActionResponse, filter_fields=["condition_id", "action_type"])

    async def list(self, page=1, page_size=20, order_by=None, ascending=False,
                   condition_id=None, action_type=None):
        return await super().list(page, page_size, order_by, ascending,
                                  condition_id=condition_id, action_type=action_type)


class WorkflowDelayService(_ServiceBase):
    def __init__(self, db: AsyncSession):
        from app.db.models import WorkflowDelay
        from app.schemas.workflow_framework import (
            DelayCreate,
            DelayResponse,
            DelayUpdate,
        )
        super().__init__(db, WorkflowDelay, DelayCreate, DelayUpdate,
                         DelayResponse, filter_fields=["workflow_id", "unit"])

    async def list(self, page=1, page_size=20, order_by=None, ascending=False,
                   workflow_id=None, unit=None):
        return await super().list(page, page_size, order_by, ascending,
                                  workflow_id=workflow_id, unit=unit)


class WorkflowBranchService(_ServiceBase):
    def __init__(self, db: AsyncSession):
        from app.db.models import WorkflowBranch
        from app.schemas.workflow_framework import (
            BranchCreate,
            BranchResponse,
            BranchUpdate,
        )
        super().__init__(db, WorkflowBranch, BranchCreate, BranchUpdate,
                         BranchResponse, filter_fields=["workflow_id"])

    async def list(self, page=1, page_size=20, order_by=None, ascending=False,
                   workflow_id=None):
        return await super().list(page, page_size, order_by, ascending,
                                  workflow_id=workflow_id)


class WorkflowSchedulerService(_ServiceBase):
    def __init__(self, db: AsyncSession):
        from app.db.models import WorkflowScheduler
        from app.schemas.workflow_framework import (
            SchedulerCreate,
            SchedulerResponse,
            SchedulerUpdate,
        )
        super().__init__(db, WorkflowScheduler, SchedulerCreate, SchedulerUpdate,
                         SchedulerResponse,
                         filter_fields=["workflow_id", "schedule_type", "enabled"])

    async def list(self, page=1, page_size=20, order_by=None, ascending=False,
                   workflow_id=None, schedule_type=None, enabled=None):
        return await super().list(page, page_size, order_by, ascending,
                                   workflow_id=workflow_id, schedule_type=schedule_type,
                                   enabled=enabled)


class WorkflowQueueService(_ServiceBase):
    def __init__(self, db: AsyncSession):
        from app.db.models import WorkflowQueue
        from app.schemas.workflow_framework import (
            QueueCreate,
            QueueResponse,
            QueueUpdate,
        )
        super().__init__(db, WorkflowQueue, QueueCreate, QueueUpdate,
                         QueueResponse,
                         filter_fields=["workflow_id", "type", "status"])

    async def list(self, page=1, page_size=20, order_by=None, ascending=False,
                   workflow_id=None, type_=None, status=None):
        # ``type`` is reserved in Python, so the router passes it as type_.
        return await super().list(page, page_size, order_by, ascending,
                                   workflow_id=workflow_id, **({"type": type_} if type_ else {}),
                                   status=status)


class WorkflowWorkerService(_ServiceBase):
    def __init__(self, db: AsyncSession):
        from app.db.models import WorkflowWorker
        from app.schemas.workflow_framework import (
            WorkerCreate,
            WorkerResponse,
            WorkerUpdate,
        )
        super().__init__(db, WorkflowWorker, WorkerCreate, WorkerUpdate,
                         WorkerResponse, filter_fields=["queue_id", "status"])

    async def list(self, page=1, page_size=20, order_by=None, ascending=False,
                   queue_id=None, status=None):
        return await super().list(page, page_size, order_by, ascending,
                                   queue_id=queue_id, status=status)
