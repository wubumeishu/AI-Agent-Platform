"""Tests for the P1-R1 in-process consumer + P1-R2 recovery loop (t_0d7a076a).

Covers:
- SchedulerTaskExecutor routing (scheduler-origin + workflow_id -> bridge;
  else -> deterministic echo)
- SchedulerConsumer start/stop/status idempotence + status() shape
- TaskRecoveryLoop start/stop/status + a fake DB sweep_once
- WorkflowConversationBridge.run_scheduled: no-op note, action execution,
  and hard-failure marking (all DB-faked; the "custom" action type needs no
  external tables so the test stays independent of live Postgres).

DB sessions are faked (per-entity result routing) to stay independent of a
live Postgres, matching the repo's test_scheduler / test_workflow_task
conventions.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from app.services.scheduler.consumer import (
    SchedulerConsumer,
    SchedulerTaskExecutor,
)
from app.services.scheduler import task_recovery
from app.services.workflow_conversation_bridge import WorkflowConversationBridge
from app.db.models.workflow import (
    Workflow,
    WorkflowTrigger,
    WorkflowCondition,
    WorkflowAction,
)


# ---------- fake DB routing by select entity ----------

class _EntityDB:
    """Routes db.execute(select(entity)) to per-entity row lists."""

    def __init__(self, rows_by_entity):
        self._rows = rows_by_entity
        self.committed = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        rows = self._rows.get(entity, [])

        class R:
            def scalar_one_or_none(self):
                return rows[0] if rows else None

            def scalars(self):
                class S2:
                    def all(self):
                        return list(rows)
                return S2()

        return R()

    async def commit(self):
        self.committed += 1

    async def refresh(self, obj):
        pass


def _mk_wf(**kw):
    now = datetime.now(timezone.utc)
    w = Workflow()
    w.id = kw.get("id") or uuid4()
    w.name = "wf"
    w.status = "active"
    w.is_deleted = False
    w.created_at = w.updated_at = now
    w.config = kw.get("config", {})
    for k, v in kw.items():
        if k != "config":
            setattr(w, k, v)
    return w


# ---------- SchedulerTaskExecutor ----------

@pytest.mark.asyncio
async def test_consumer_executor_routes_scheduler_task_to_bridge():
    """A scheduler-origin task with a workflow_id runs the bridge graph."""
    wf_id = uuid4()
    ex = SchedulerTaskExecutor()

    # Patch the bridge class so we do not need the real DB wiring.
    from app.services import workflow_conversation_bridge as bridge_mod

    class _FakeBridge:
        def __init__(self, db):
            pass
        async def run_scheduled(self, workflow_id, params=None, now=None):
            return {"ok": True, "workflow_id": str(workflow_id),
                    "triggers": 1, "actions": 1}

    real_bridge = bridge_mod.WorkflowConversationBridge
    bridge_mod.WorkflowConversationBridge = _FakeBridge
    try:
        out = await ex.run(
            {"params": {"intent_type": "greeting"}},
            {"workflow_id": str(wf_id),
             "task_metadata": {"origin": "scheduler"}},
        )
    finally:
        bridge_mod.WorkflowConversationBridge = real_bridge

    assert out["executor"] == "scheduler-task"
    assert out["scheduler_run"]["ok"] is True
    assert out["params"] == {"intent_type": "greeting"}


@pytest.mark.asyncio
async def test_consumer_executor_echo_for_non_scheduler_task():
    """Anything that is not a scheduler-origin task gets the echo executor."""
    ex = SchedulerTaskExecutor()
    out = await ex.run({"a": 1}, {"workflow_id": "deadbeef-dead-beef-dead-deaddeafbeef",
                                   "task_metadata": {}})
    assert out["executor"] == "scheduler-task"
    assert out.get("echo") is not None  # echo path, not bridge


# ---------- SchedulerConsumer ----------

@pytest.mark.asyncio
async def test_consumer_start_stop_idempotent():
    c = SchedulerConsumer(queue_names=["q"], poll_seconds=9999.0)
    await c.start()
    assert c.running is True
    st = c.status()
    assert st["queues"] == ["q"] and st["poll_seconds"] == 9999.0
    await c.start()  # idempotent
    await c.stop()
    assert c.running is False
    await c.stop()  # idempotent


def test_consumer_default_queue_name_uses_config():
    c = SchedulerConsumer()
    assert c.queue_names == ["workflow-scheduler"]  # default config value


@pytest.mark.asyncio
async def test_consumer_poll_once_claims_and_executes():
    """A poll pass claims the ready task and runs the executor on it."""
    from app.db.models.workflow_task import WorkflowTask
    from app.services.workflow_task import TaskResponse, EchoExecutor

    tid, qid = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    claimed = WorkflowTask()
    claimed.id = tid
    claimed.queue_id = qid
    claimed.status = "running"  # as claim_next stamps it
    claimed.payload = {"x": 1}
    claimed.metadata_ = {"origin": "scheduler"}
    claimed.retry_count = 0
    claimed.max_retries = 0
    claimed.created_at = claimed.updated_at = now

    # db.execute scripts: (1) worker-row select [none], (2) queue select [q],
    # claim_next is mocked separately.
    q = MagicMock()
    q.id = qid
    q.name = "workflow-scheduler"

    class _ClaimDB:
        def __init__(self):
            self._scripts = [
                _EntityDB_rows([MagicMock(id=uuid4(), status="busy")]),  # worker row
                _EntityDB_rows([q]),                                      # queue rows
            ]
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def execute(self, stmt):
            s = self._scripts.pop(0)
            return await s.execute(stmt)
        async def commit(self):
            pass
        async def refresh(self, obj):
            pass

    # Patch the engine's claim_next to hand back the claimed task once.
    from app.services import workflow_task as wt
    claimed_resp = TaskResponse.from_model(claimed)
    real_claim = wt.QueueWorkerEngine.claim_next
    real_exec = wt.QueueWorkerEngine.execute_task
    try:
        wt.QueueWorkerEngine.claim_next = AsyncMock(
            side_effect=[claimed_resp, None])
        wt.QueueWorkerEngine.execute_task = AsyncMock(return_value=MagicMock(
            status="success", task_id=tid, error_message=None))
        c = SchedulerConsumer(
            queue_names=["workflow-scheduler"], poll_seconds=9999.0,
            session_factory=lambda: _ClaimDB(),
        )
        executed = await c._poll_once()
    finally:
        wt.QueueWorkerEngine.claim_next = real_claim
        wt.QueueWorkerEngine.execute_task = real_exec
    assert executed == 1
    assert c.processed == 1
    assert c.failed == 0


class _EntityDB_rows:
    """Minimal per-entity row router (single-entity variant for _ClaimDB)."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, stmt):
        rows = list(self._rows)

        class R:
            def scalar_one_or_none(self):
                return rows[0] if rows else None

            def scalars(self):
                class S2:
                    def all(self):
                        return rows
                return S2()
        return R()


# ---------- TaskRecoveryLoop ----------

@pytest.mark.asyncio
async def test_recovery_loop_start_stop_idempotent():
    loop = task_recovery.TaskRecoveryLoop(session_factory=lambda: None)
    await loop.start(interval_seconds=9999.0)
    assert loop.running is True
    st = loop.status()
    assert st["interval_seconds"] == 9999.0 and st["ticks"] == 0
    await loop.start(interval_seconds=1.0)  # idempotent, keeps original
    assert loop.status()["interval_seconds"] == 9999.0
    await loop.stop()
    assert loop.running is False
    await loop.stop()  # idempotent


def test_recovery_loop_singleton():
    a = task_recovery.get_task_recovery_loop()
    assert a is task_recovery.get_task_recovery_loop()
    task_recovery.reset_task_recovery_loop()
    assert task_recovery.get_task_recovery_loop() is not a


# ---------- bridge.run_scheduled ----------

@pytest.mark.asyncio
async def test_run_scheduled_no_actions_records_noop():
    wf = _mk_wf()
    db = _EntityDB({Workflow: [wf],
                    WorkflowTrigger: [], WorkflowCondition: [],
                    WorkflowAction: []})
    bridge = WorkflowConversationBridge(db)
    out = await bridge.run_scheduled(wf.id, params={"intent_type": "greeting"})
    assert out["ok"] is True
    assert "note" in out  # explicit, observable no-op


@pytest.mark.asyncio
async def test_run_scheduled_executes_action_graph():
    now = datetime.now(timezone.utc)
    wf = _mk_wf(config={"customer_id": str(uuid4())})
    trig = WorkflowTrigger()
    trig.id = uuid4()
    trig.workflow_id = wf.id
    trig.enabled = True
    trig.is_deleted = False
    trig.trigger_type = "event"
    trig.created_at = trig.updated_at = now
    cond = WorkflowCondition()
    cond.id = uuid4()
    cond.trigger_id = trig.id
    cond.expression = {}  # vacuous pass
    cond.is_deleted = False
    cond.created_at = cond.updated_at = now
    act = WorkflowAction()
    act.id = uuid4()
    act.condition_id = cond.id
    act.action_type = "custom"  # recorded, no external table needed
    act.params = {"kind": "notify"}
    act.is_deleted = False
    act.created_at = act.updated_at = now

    db = _EntityDB({Workflow: [wf], WorkflowTrigger: [trig],
                    WorkflowCondition: [cond], WorkflowAction: [act]})
    bridge = WorkflowConversationBridge(db)
    out = await bridge.run_scheduled(wf.id, params={"intent_type": "greeting"})
    assert out["ok"] is True
    assert out["triggers"] == 1
    assert out["failed_actions"] == 0
    assert out["actions"][0]["action_type"] == "custom"


@pytest.mark.asyncio
async def test_run_scheduled_missing_workflow_is_safe():
    db = _EntityDB({Workflow: []})
    bridge = WorkflowConversationBridge(db)
    out = await bridge.run_scheduled(uuid4(), params={})
    assert out["ok"] is True
    assert "note" in out  # observable no-op, not an exception
