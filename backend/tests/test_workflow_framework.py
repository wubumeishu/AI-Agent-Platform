"""Workflow Framework (t_wf_001) unit tests.

Covers, without a live database (mocked AsyncSession, matching the project's
structure/contract test convention):

- ORM model registration + table-name uniqueness (no collisions)
- schema validation (create/update/response, allowed value sets)
- router structure (all 9 resources expose CRUD endpoints)
- generic CRUD service behavior (create / get / update / delete / list)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from app.db.models import Base
from app.db.models.workflow import (
    Workflow,
    WorkflowTrigger,
    WorkflowCondition,
    WorkflowAction,
    ExecutionLog,
)
from app.db.models.workflow_runtime import (
    WorkflowDelay,
    WorkflowBranch,
    WorkflowScheduler,
    WorkflowQueue,
    WorkflowWorker,
)


# =====================================================================
# Model layer
# =====================================================================

class TestWorkflowModels:
    """ORM model registration & table topology."""

    def test_all_workflow_tables_registered(self):
        expected = {
            "workflow",
            "workflow_trigger",
            "workflow_condition",
            "workflow_action",
            "workflow_delay",
            "workflow_branch",
            "workflow_scheduler",
            "workflow_queue",
            "workflow_worker",
            "execution_log",
        }
        registered = set(Base.metadata.tables.keys())
        missing = expected - registered
        assert not missing, f"missing tables: {missing}"

    def test_table_names_unique(self):
        names = list(Base.metadata.tables.keys())
        assert len(names) == len(set(names)), "duplicate table names!"

    def test_runtime_classes_map_to_correct_tables(self):
        mapping = [
            (Workflow, "workflow"),
            (WorkflowTrigger, "workflow_trigger"),
            (WorkflowCondition, "workflow_condition"),
            (WorkflowAction, "workflow_action"),
            (WorkflowDelay, "workflow_delay"),
            (WorkflowBranch, "workflow_branch"),
            (WorkflowScheduler, "workflow_scheduler"),
            (WorkflowQueue, "workflow_queue"),
            (WorkflowWorker, "workflow_worker"),
            (ExecutionLog, "execution_log"),
        ]
        for cls, table in mapping:
            assert cls.__tablename__ == table

    def test_runtime_entities_have_soft_delete_and_timestamps(self):
        for cls in [WorkflowDelay, WorkflowBranch, WorkflowScheduler,
                    WorkflowQueue, WorkflowWorker]:
            cols = {c.name for c in cls.__table__.columns}
            assert "is_deleted" in cols
            assert "created_at" in cols
            assert "updated_at" in cols
            assert "id" in cols

    def test_queue_name_is_unique(self):
        col = WorkflowQueue.__table__.c.name
        assert col.unique is True, "queue name must be unique"
        # the column carries an (auto) unique index on top of the constraint
        assert col.index is True

    def test_fk_on_delete_behavior(self):
        fks = WorkflowScheduler.__table__.foreign_keys
        targets = {(fk.column.table.name, fk.ondelete) for fk in fks}
        # workflow_id -> workflow.id CASCADE ; trigger_id -> trigger SET NULL
        assert ("workflow", "CASCADE") in targets
        assert ("workflow_trigger", "SET NULL") in targets


# =====================================================================
# Schema layer
# =====================================================================

class TestWorkflowFrameworkSchemas:
    """Pydantic create/update/response validation."""

    def test_workflow_create_defaults(self):
        from app.schemas.workflow_framework import WorkflowCreate
        d = WorkflowCreate(name="lead-nurture")
        assert d.name == "lead-nurture"
        assert d.workflow_type == "auto"
        assert d.status == "draft"
        assert d.config == {}
        assert d.execution_policy == {}

    def test_workflow_create_invalid_status(self):
        from pydantic import ValidationError
        from app.schemas.workflow_framework import WorkflowCreate
        with pytest.raises(ValidationError):
            WorkflowCreate(name="x", status="not_a_status")

    def test_trigger_create_requires_workflow_id(self):
        from pydantic import ValidationError
        from app.schemas.workflow_framework import TriggerCreate
        with pytest.raises(ValidationError):
            TriggerCreate()  # workflow_id is required

    def test_trigger_create_valid(self):
        from app.schemas.workflow_framework import TriggerCreate
        d = TriggerCreate(workflow_id=uuid4(), trigger_type="cron",
                          spec={"cron": "*/5 * * * *", "timezone": "Asia/Tokyo"})
        assert d.trigger_type == "cron"
        assert d.enabled is True

    def test_trigger_invalid_type_rejected(self):
        from pydantic import ValidationError
        from app.schemas.workflow_framework import TriggerCreate
        with pytest.raises(ValidationError):
            TriggerCreate(workflow_id=uuid4(), trigger_type="bogus")

    def test_scheduler_cron_vs_interval(self):
        from app.schemas.workflow_framework import SchedulerCreate
        cron = SchedulerCreate(name="s", schedule_type="cron",
                               cron_expression="0 9 * * *")
        assert cron.schedule_type == "cron"
        ivl = SchedulerCreate(name="s", schedule_type="interval",
                              interval_seconds=3600)
        assert ivl.interval_seconds == 3600

    def test_action_type_validation(self):
        from pydantic import ValidationError
        from app.schemas.workflow_framework import ActionCreate
        ok = ActionCreate(condition_id=uuid4(), action_type="message")
        assert ok.action_type == "message"
        with pytest.raises(ValidationError):
            ActionCreate(condition_id=uuid4(), action_type="teleport")

    def test_queue_create_name_required_and_defaults(self):
        from pydantic import ValidationError
        from app.schemas.workflow_framework import QueueCreate
        with pytest.raises(ValidationError):
            QueueCreate()
        q = QueueCreate(name="main-queue")
        assert q.type == "fifo"
        assert q.max_concurrency == 1
        assert q.status == "idle"

    def test_worker_response_from_attributes(self):
        from app.schemas.workflow_framework import WorkerResponse
        obj = MagicMock()
        obj.id = uuid4()
        obj.name = "w1"
        obj.queue_id = None
        obj.status = "idle"
        obj.config = {}
        obj.last_heartbeat_at = None
        obj.created_at = datetime.now(timezone.utc)
        obj.updated_at = datetime.now(timezone.utc)
        r = WorkerResponse.model_validate(obj)
        assert r.name == "w1"
        assert r.status == "idle"

    def test_condition_logic_validation(self):
        from pydantic import ValidationError
        from app.schemas.workflow_framework import ConditionCreate
        assert ConditionCreate(trigger_id=uuid4(), logic="or").logic == "or"
        with pytest.raises(ValidationError):
            ConditionCreate(trigger_id=uuid4(), logic="xor")

    def test_delay_unit_validation(self):
        from pydantic import ValidationError
        from app.schemas.workflow_framework import DelayCreate
        assert DelayCreate(workflow_id=uuid4(), unit="hours").unit == "hours"
        with pytest.raises(ValidationError):
            DelayCreate(workflow_id=uuid4(), unit="eons")


# =====================================================================
# Router layer
# =====================================================================

def _router_by_path():
    """Map of route path -> set of HTTP methods for the framework router."""
    from app.routers.workflow_framework import router
    mapping = {}
    for route in router.routes:
        if hasattr(route, "path"):
            mapping.setdefault(route.path, set()).update(route.methods or set())
    return mapping


class TestWorkflowFrameworkRouter:
    """P1-1 convergence: the framework router now exposes ONLY the 5 runtime
    entities. The 4 configuration entities (workflows / triggers / conditions /
    actions) live exclusively in the nested ``workflow_config`` router — their
    flat copies were removed here to end the dual /workflows API surface.
    """

    def test_all_resources_present(self):
        by_path = _router_by_path()
        for res in ["workflow-delays", "workflow-branches",
                    "workflow-schedulers", "workflow-queues", "workflow-workers"]:
            assert f"/{res}" in by_path, f"missing resource path /{res}"

    def test_each_resource_has_collection_crud(self):
        by_path = _router_by_path()
        for res in ["workflow-delays", "workflow-branches", "workflow-schedulers",
                    "workflow-queues", "workflow-workers"]:
            assert {"GET", "POST"} <= by_path[f"/{res}"]
            item = f"/{res}/{{instance_id}}"
            assert {"GET", "PUT", "DELETE"} <= by_path[item]

    def test_framework_no_longer_declares_config_entities(self):
        """P1-1: /workflows and the flat trigger/condition/action routes are gone
        from the framework router (they moved to the nested workflow_config
        router as the single canonical /workflows surface)."""
        by_path = _router_by_path()
        for res in ["workflows", "workflow-triggers", "workflow-conditions",
                    "workflow-actions"]:
            assert f"/{res}" not in by_path, f"config entity /{res} still present"

    def test_no_doubled_api_prefix(self):
        by_path = _router_by_path()
        assert not any("/api/v1/api/v1" in p for p in by_path)


# =====================================================================
# Service layer (mocked session)
# =====================================================================

def _mock_db(result_rows=None, total=0):
    """Build an AsyncMock db whose execute() returns a result with scalars/rows.

    The first call returns the total-count result; subsequent calls return
    row results. Simpler: return a fresh result per call based on query text
    is overkill — instead we let tests set scalar_one / scalars as needed.
    """
    db = AsyncMock()
    return db


def _result_with(rows, total=0):
    r = MagicMock()
    r.scalars.return_value.all.return_value = rows
    r.scalar_one.return_value = total
    r.scalar_one_or_none.return_value = rows[0] if rows else None
    return r


class TestWorkflowServiceCRUD:
    """Exercise the generic CRUD engine through the real service classes."""

    def test_create_workflow(self):
        from app.services.workflow_framework import WorkflowService
        db = AsyncMock()
        db.commit = AsyncMock()
        # db.add is synchronous on a real AsyncSession; keep it a plain mock
        # (not an awaited coroutine) to avoid RuntimeWarnings.
        db.add = MagicMock()
        created_at = datetime.now(timezone.utc)

        def _stamp_defaults(obj):
            # Emulate what refresh() exposes after a real INSERT: id is
            # generated, timestamps + the Python-side column default (version)
            # are materialised.
            if obj.id is None:
                obj.id = uuid4()
            if obj.created_at is None:
                obj.created_at = created_at
            if obj.updated_at is None:
                obj.updated_at = created_at
            if obj.version is None:
                obj.version = 1

        db.refresh = AsyncMock(side_effect=_stamp_defaults)
        svc = WorkflowService(db)

        from app.schemas.workflow_framework import WorkflowCreate
        out = _run_async(svc.create(WorkflowCreate(name="nurture")))

        # verify a Workflow ORM object was added to the session
        added = db.add.call_args[0][0]
        assert isinstance(added, Workflow)
        assert added.name == "nurture"
        assert out.name == "nurture"
        assert out.id == added.id
        assert out.version == 1

    def test_get_workflow_returns_none_when_missing(self):
        from app.services.workflow_framework import WorkflowService
        db = AsyncMock()
        db.execute.return_value = _result_with([])
        svc = WorkflowService(db)
        assert _run_async(svc.get(uuid4())) is None

    def test_get_workflow_returns_response(self):
        from app.services.workflow_framework import WorkflowService
        db = AsyncMock()
        row = _mock_workflow_row()
        db.execute.return_value = _result_with([row])
        svc = WorkflowService(db)
        out = _run_async(svc.get(uuid4()))
        assert out.name == row.name

    def test_update_workflow_not_found(self):
        from app.services.workflow_framework import WorkflowService
        db = AsyncMock()
        db.execute.return_value = _result_with([])
        svc = WorkflowService(db)
        from app.schemas.workflow_framework import WorkflowUpdate
        assert _run_async(svc.update(uuid4(), WorkflowUpdate(name="x"))) is None

    def test_delete_workflow_soft(self):
        from app.services.workflow_framework import WorkflowService
        db = AsyncMock()
        db.commit = AsyncMock()
        row = _mock_workflow_row()
        row.is_deleted = False
        db.execute.return_value = _result_with([row])
        svc = WorkflowService(db)
        assert _run_async(svc.delete(uuid4())) is True
        assert row.is_deleted is True

    def test_list_workflows_filters_and_paginates(self):
        from app.services.workflow_framework import WorkflowService
        db = AsyncMock()
        db.execute.return_value = _result_with([_mock_workflow_row()], total=3)
        svc = WorkflowService(db)
        items, total = _run_async(
            svc.list(1, 20, status="active", workflow_type="auto")
        )
        assert total == 3
        assert len(items) == 1
        # the count query is executed first, so total comes from scalar_one
        assert db.execute.called

    def test_queue_service_maps_type_field(self):
        from app.services.workflow_framework import WorkflowQueueService
        db = AsyncMock()
        db.execute.return_value = _result_with([], total=0)
        svc = WorkflowQueueService(db)
        items, total = _run_async(svc.list(1, 20, type_="fifo"))
        assert total == 0
        assert items == []

    def test_worker_service(self):
        from app.services.workflow_framework import WorkflowWorkerService
        db = AsyncMock()
        db.execute.return_value = _result_with([], total=0)
        svc = WorkflowWorkerService(db)
        items, total = _run_async(svc.list(1, 20, status="idle"))
        assert total == 0


def _mock_workflow_row():
    row = MagicMock()
    row.id = uuid4()
    row.name = "nurture"
    row.description = None
    row.workflow_type = "auto"
    row.status = "draft"
    row.config = {}
    row.execution_policy = {}
    row.version = 1
    row.created_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    return row


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)
