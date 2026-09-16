"""Tests for the Queue + Worker execution engine (Phase 4 / t_wf_004).

Covers:
- model: state enums + derived properties
- schemas: validation + response mapping
- engine: enqueue / get / list
- engine: atomic claim (dequeue) incl. scheduling + priority + empty queue
- engine: execute with a pluggable executor (success / failure / guards)
- engine: explicit state transitions (complete / fail / cancel)
- engine: retry (re-queue, exhausted, illegal)
- engine: timeout sweep (task-level + queue fallback + not-expired)
- engine: queue stats + clear/drain
- router wiring (OpenAPI exposure + route ordering + import guard)

DB session is mocked (AsyncMock) to stay independent of a live Postgres,
matching the repo's test_workflow_execution_log convention.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone, timedelta

from app.db.models.workflow_task import (
    WorkflowTask,
    TASK_STATES,
    TERMINAL_STATES,
    NON_TERMINAL_STATES,
)
from app.schemas.workflow_task import (
    TaskCreate,
    TaskFilter,
    TaskGeneralUpdate,
    TaskResponse,
    TaskStateUpdate,
    TimeoutSweepRequest,
    ClearQueueRequest,
    ClearQueueResponse,
)
from app.services.workflow_task import (
    EchoExecutor,
    QueueWorkerEngine,
    TaskNotFoundError,
    TaskStateError,
    LEGAL_TRANSITIONS,
)


def _make_task(**overrides):
    """Build a WorkflowTask with every from_model-read field set deterministically.

    In-memory ORM instances do NOT get JSONB/DateTime column defaults
    (those are server-side), so we set them explicitly.
    """
    now = datetime.now(timezone.utc)
    t = WorkflowTask()
    t.id = uuid4()
    t.queue_id = uuid4()
    t.created_at = now
    t.updated_at = now
    t.payload = {}
    t.metadata_ = {}
    t.status = "pending"
    t.priority = 0
    t.retry_count = 0
    t.max_retries = 0
    t.is_deleted = False
    for key, value in overrides.items():
        setattr(t, key, value)
    return t


def _execute_result(*rows):
    """Fake a db.execute() result with .scalars().all() / .first() / .scalar_one(_or_none)."""
    res = MagicMock()
    res.scalars.return_value.all.return_value = list(rows)
    res.scalars.return_value.first.return_value = rows[0] if rows else None
    res.scalar_one_or_none.return_value = rows[0] if rows else None
    res.scalar_one.return_value = len(rows)
    res.all.return_value = list(rows)
    return res


# ========== Model ==========

def test_task_states_cover_required_lifecycle():
    """Acceptance: task execution states pending/running/success/failed (cancelled/timeout extra)."""
    for required in ("pending", "running", "success", "failed"):
        assert required in TASK_STATES
    assert "cancelled" in TASK_STATES
    assert "timeout" in TASK_STATES


def test_terminal_vs_non_terminal_partition():
    assert set(TERMINAL_STATES) == {"success", "failed", "cancelled", "timeout"}
    assert set(NON_TERMINAL_STATES) == {"pending", "running"}
    assert set(TERMINAL_STATES).isdisjoint(set(NON_TERMINAL_STATES))


def test_model_defaults():
    t = WorkflowTask()
    t.queue_id = uuid4()
    # Intentionally set server-side defaults explicitly (they are NOT applied
    # to in-memory instances); then verify the Python-side defaults the
    # construction path actually guarantees.
    t.payload = {}
    t.metadata_ = {}
    t.is_deleted = False
    # In-memory ORM instances do NOT get the Column(server_default) values
    # (status/priority/retry_count are server defaults), so we assert only the
    # ones the engine's constructor path sets.
    assert t.status is None  # server default 'pending', not applied in-memory
    assert t.created_at is None  # server default, not applied in-memory


def test_is_terminal_property():
    assert _make_task(status="pending").is_terminal is False
    assert _make_task(status="running").is_terminal is False
    assert _make_task(status="success").is_terminal is True
    assert _make_task(status="timeout").is_terminal is True


def test_is_retryable_property():
    assert _make_task(status="failed", retry_count=0, max_retries=2).is_retryable is True
    assert _make_task(status="failed", retry_count=2, max_retries=2).is_retryable is False
    assert _make_task(status="timeout", retry_count=0, max_retries=1).is_retryable is True
    # non-terminal states are never retryable
    assert _make_task(status="pending").is_retryable is False
    assert _make_task(status="success").is_retryable is False


def test_legal_transitions_graph():
    assert "running" in LEGAL_TRANSITIONS["pending"]
    assert "cancelled" in LEGAL_TRANSITIONS["pending"]
    assert "success" in LEGAL_TRANSITIONS["running"]
    assert "timeout" in LEGAL_TRANSITIONS["running"]
    assert LEGAL_TRANSITIONS["success"] == frozenset()
    assert LEGAL_TRANSITIONS["cancelled"] == frozenset()
    # retry edges
    assert "pending" in LEGAL_TRANSITIONS["failed"]
    assert "pending" in LEGAL_TRANSITIONS["timeout"]


# ========== Schema ==========

def test_task_create_defaults():
    data = TaskCreate(queue_id=uuid4())
    assert data.priority == 0
    assert data.max_retries == 0
    assert data.payload == {}


def test_task_create_valid_payload():
    data = TaskCreate(
        queue_id=uuid4(),
        workflow_id=uuid4(),
        name="send-msg",
        payload={"a": 1},
        max_retries=3,
        timeout_seconds=60,
    )
    assert data.name == "send-msg"
    assert data.max_retries == 3


def test_task_state_update_rejects_bad_status():
    with pytest.raises(ValueError):
        TaskStateUpdate(status="not_a_state")


def test_task_state_update_valid():
    upd = TaskStateUpdate(status="failed", error_message="boom", error_code="E1")
    assert upd.status == "failed"
    assert upd.error_code == "E1"


def test_task_filter_rejects_bad_status():
    with pytest.raises(ValueError):
        TaskFilter(status="nope")


def test_task_filter_valid():
    f = TaskFilter(queue_id=uuid4(), status="running", page=2, page_size=50)
    assert f.page == 2


def test_task_filter_rejects_bad_order_by():
    with pytest.raises(ValueError):
        TaskFilter(order_by="password_hash")


def test_response_from_model_maps_metadata_underscore():
    t = _make_task(payload={"k": 1}, metadata_={"w": "1"}, result={"ok": True})
    resp = TaskResponse.from_model(t)
    assert resp.metadata == {"w": "1"}
    assert resp.payload == {"k": 1}
    assert resp.result == {"ok": True}
    assert resp.is_retryable in (True, False)


def test_clear_queue_request_default():
    assert ClearQueueRequest().keep_running is False


# ========== Engine: enqueue / read ==========

@pytest.mark.asyncio
async def test_enqueue_creates_pending_task():
    db = AsyncMock()
    created = {}

    def add(task):
        created["task"] = task

    db.add.side_effect = add

    def stamp(obj):
        # Simulates what a real DB round-trip returns: the row now has an
        # id + timestamps set by the DB layer.
        obj.id = uuid4()
        obj.created_at = datetime.now(timezone.utc)
        obj.updated_at = obj.created_at
        obj.is_deleted = False

    db.refresh.side_effect = stamp

    engine = QueueWorkerEngine(db)
    data = TaskCreate(queue_id=uuid4(), payload={"x": 1}, max_retries=2, timeout_seconds=30)
    resp = await engine.enqueue(data)

    assert resp.status == "pending"
    assert resp.max_retries == 2
    assert resp.timeout_seconds == 30
    assert resp.payload == {"x": 1}
    assert resp.id is not None  # stamped by db.refresh
    db.add.assert_called_once()
    db.commit.assert_awaited()
    db.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_get_task_found():
    db = AsyncMock()
    task = _make_task(status="running")
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    got = await engine.get_task(task.id)
    assert got is not None
    assert got.id == task.id
    assert got.status == "running"


@pytest.mark.asyncio
async def test_get_task_not_found():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_execute_result())  # empty
    engine = QueueWorkerEngine(db)
    assert await engine.get_task(uuid4()) is None


@pytest.mark.asyncio
async def test_list_tasks_with_filters():
    db = AsyncMock()
    tasks = [_make_task(status="pending"), _make_task(status="running")]
    count_res = MagicMock()
    count_res.scalar_one.return_value = 2
    list_res = _execute_result(*tasks)
    db.execute = AsyncMock(side_effect=[count_res, list_res])

    engine = QueueWorkerEngine(db)
    items, total = await engine.list_tasks(TaskFilter(queue_id=uuid4(), status=None))
    assert total == 2
    assert len(items) == 2
    assert items[0].status in ("pending", "running")


# ========== Engine: claim (dequeue) ==========

@pytest.mark.asyncio
async def test_claim_next_empty_queue_returns_none():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_execute_result())  # scalars().first() -> None
    engine = QueueWorkerEngine(db)
    assert await engine.claim_next(uuid4()) is None


@pytest.mark.asyncio
async def test_claim_next_transitions_to_running_and_stamps():
    db = AsyncMock()
    task = _make_task(status="pending", worker_id=None)
    db.execute = AsyncMock(return_value=_execute_result(task))
    now = datetime.now(timezone.utc)
    engine = QueueWorkerEngine(db)
    claimed = await engine.claim_next(uuid4(), worker_id=uuid4(), now=now)
    assert claimed is not None
    assert task.status == "running"
    assert task.claimed_at == now
    assert task.started_at == now
    # worker_id pinned because it was None originally
    assert task.worker_id is not None
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_claim_next_keeps_pinned_worker():
    db = AsyncMock()
    pinned_worker = uuid4()
    task = _make_task(status="pending", worker_id=pinned_worker)
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    await engine.claim_next(uuid4(), worker_id=uuid4())
    # original pinning preserved (only set when it was None)
    assert task.worker_id == pinned_worker


@pytest.mark.asyncio
async def test_claim_next_respects_scheduled_future():
    """A task scheduled in the future is excluded from the ready set by the SQL predicate."""
    db = AsyncMock()
    # The engine adds `scheduled_at <= now` (or IS NULL). We simulate the DB having
    # applied that filter by returning None (no ready task).
    db.execute = AsyncMock(return_value=_execute_result())
    engine = QueueWorkerEngine(db)
    assert await engine.claim_next(uuid4(), now=datetime.now(timezone.utc)) is None


# ========== Engine: execute ==========

@pytest.mark.asyncio
async def test_execute_task_success():
    db = AsyncMock()
    task = _make_task(status="running", started_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    tresp = TaskResponse.from_model(task)
    result = await engine.execute_task(tresp, EchoExecutor())
    assert result.status == "success"
    assert task.status == "success"
    assert task.result == {"echo": {}, "ok": True, "executor": "echo"}
    assert task.finished_at is not None
    assert task.duration_ms is not None
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_execute_task_failure_records_error():
    class Boom:
        async def run(self, payload, context):
            raise RuntimeError("kaboom")

    db = AsyncMock()
    task = _make_task(status="running", started_at=datetime.now(timezone.utc))
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    tresp = TaskResponse.from_model(task)
    result = await engine.execute_task(tresp, Boom())
    assert result.status == "failed"
    assert task.status == "failed"
    assert "kaboom" in (task.error_message or "")
    assert task.error_code == "EXECUTION_FAILED"


@pytest.mark.asyncio
async def test_execute_task_not_found():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_execute_result())  # empty -> None
    engine = QueueWorkerEngine(db)
    tresp = TaskResponse.from_model(_make_task(status="running"))
    with pytest.raises(TaskNotFoundError):
        await engine.execute_task(tresp, EchoExecutor())


@pytest.mark.asyncio
async def test_execute_task_wrong_state_guard():
    db = AsyncMock()
    task = _make_task(status="pending")  # not running yet
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    tresp = TaskResponse.from_model(task)
    with pytest.raises(TaskStateError):
        await engine.execute_task(tresp, EchoExecutor())


# ========== Engine: explicit state transitions ==========

@pytest.mark.asyncio
async def test_complete_task_from_running():
    db = AsyncMock()
    task = _make_task(status="running", started_at=datetime.now(timezone.utc))
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    resp = await engine.complete_task(task.id, result={"ok": True})
    assert resp.status == "success"
    assert task.result == {"ok": True}


@pytest.mark.asyncio
async def test_fail_task_from_running():
    db = AsyncMock()
    task = _make_task(status="running")
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    resp = await engine.fail_task(task.id, error_message="err", error_code="E")
    assert resp.status == "failed"
    assert task.error_message == "err"


@pytest.mark.asyncio
async def test_cancel_task_from_pending():
    db = AsyncMock()
    task = _make_task(status="pending")
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    resp = await engine.cancel_task(task.id, reason="user asked")
    assert resp.status == "cancelled"
    assert task.error_code == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_terminal_task_rejected():
    db = AsyncMock()
    task = _make_task(status="success")
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    with pytest.raises(TaskStateError):
        await engine.cancel_task(task.id)


@pytest.mark.asyncio
async def test_complete_non_running_rejected():
    db = AsyncMock()
    task = _make_task(status="pending")
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    with pytest.raises(TaskStateError):
        await engine.complete_task(task.id)


# ========== Engine: retry ==========

@pytest.mark.asyncio
async def test_retry_failed_task_requeues():
    db = AsyncMock()
    task = _make_task(status="failed", retry_count=0, max_retries=3)
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    resp = await engine.retry_task(task.id)
    assert resp.status == "pending"
    assert task.retry_count == 1
    assert task.started_at is None
    assert task.finished_at is None
    assert task.error_message is None


@pytest.mark.asyncio
async def test_retry_exhausted_rejected():
    db = AsyncMock()
    task = _make_task(status="failed", retry_count=3, max_retries=3)
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    with pytest.raises(TaskStateError):
        await engine.retry_task(task.id)


@pytest.mark.asyncio
async def test_retry_from_non_terminal_rejected():
    db = AsyncMock()
    task = _make_task(status="pending")
    db.execute = AsyncMock(return_value=_execute_result(task))
    engine = QueueWorkerEngine(db)
    with pytest.raises(TaskStateError):
        await engine.retry_task(task.id)


# ========== Engine: timeout sweep ==========

@pytest.mark.asyncio
async def test_sweep_marks_expired_task():
    db = AsyncMock()
    task = _make_task(status="running", timeout_seconds=5, started_at=datetime.now(timezone.utc) - timedelta(seconds=10))
    running_res = _execute_result(task)
    # second execute call: per-queue WorkflowQueue lookup -> empty
    queue_res = _execute_result()
    db.execute = AsyncMock(side_effect=[running_res, queue_res])
    engine = QueueWorkerEngine(db)
    resp = await engine.sweep_timeouts(TimeoutSweepRequest())
    assert resp.swept == 1
    assert task.status == "timeout"
    assert task.error_code == "TIMEOUT"
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_sweep_leaves_fresh_task():
    db = AsyncMock()
    task = _make_task(status="running", timeout_seconds=300, started_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    running_res = _execute_result(task)
    queue_res = _execute_result()
    db.execute = AsyncMock(side_effect=[running_res, queue_res])
    engine = QueueWorkerEngine(db)
    resp = await engine.sweep_timeouts(TimeoutSweepRequest())
    assert resp.swept == 0
    assert task.status == "running"


@pytest.mark.asyncio
async def test_sweep_no_task_timeout_uses_queue_fallback():
    db = AsyncMock()
    # task has no per-task timeout -> must fall back to queue.timeout_seconds
    task = _make_task(status="running", timeout_seconds=None, started_at=datetime.now(timezone.utc) - timedelta(seconds=10))
    running_res = _execute_result(task)

    # Fake a WorkflowQueue row with timeout_seconds=5. P2-2 batched fetch reads
    # the queue via a single in_() query -> .scalars().all(), so wrap the row
    # with _execute_result (NOT the old per-queue scalar_one_or_none shape).
    from app.db.models.workflow_runtime import WorkflowQueue
    q = WorkflowQueue()
    q.id = task.queue_id
    q.timeout_seconds = 5

    db.execute = AsyncMock(side_effect=[running_res, _execute_result(q)])
    engine = QueueWorkerEngine(db)
    resp = await engine.sweep_timeouts(TimeoutSweepRequest())
    assert resp.swept == 1
    assert task.status == "timeout"


@pytest.mark.asyncio
async def test_sweep_no_timeout_at_all_untouched():
    db = AsyncMock()
    task = _make_task(status="running", timeout_seconds=None, started_at=datetime.now(timezone.utc) - timedelta(seconds=100))
    running_res = _execute_result(task)
    # queue has no timeout either (P2-2: batched in_() fetch -> scalars().all())
    from app.db.models.workflow_runtime import WorkflowQueue
    q = WorkflowQueue()
    q.id = task.queue_id
    q.timeout_seconds = None
    db.execute = AsyncMock(side_effect=[running_res, _execute_result(q)])
    engine = QueueWorkerEngine(db)
    resp = await engine.sweep_timeouts(TimeoutSweepRequest())
    assert resp.swept == 0
    assert task.status == "running"


# ========== Engine: stats + clear ==========

@pytest.mark.asyncio
async def test_queue_stats_counts_by_state():
    db = AsyncMock()
    # First execute: group_by status counts. rows: (status, count)
    status_rows = MagicMock()
    status_rows.all.return_value = [("pending", 2), ("running", 1), ("success", 5)]
    # Second execute: retryable count
    retry_res = MagicMock()
    retry_res.scalar_one.return_value = 1
    db.execute = AsyncMock(side_effect=[status_rows, retry_res])
    engine = QueueWorkerEngine(db)
    resp = await engine.queue_stats(uuid4())
    s = resp.stats
    assert s.pending == 2
    assert s.running == 1
    assert s.success == 5
    assert s.failed == 0
    assert s.total == 8
    assert s.retryable == 1
    assert resp.has_backlog is True
    assert resp.is_idle is False


@pytest.mark.asyncio
async def test_queue_stats_idle():
    db = AsyncMock()
    status_rows = MagicMock()
    status_rows.all.return_value = [("success", 3)]
    retry_res = MagicMock()
    retry_res.scalar_one.return_value = 0
    db.execute = AsyncMock(side_effect=[status_rows, retry_res])
    engine = QueueWorkerEngine(db)
    resp = await engine.queue_stats(uuid4())
    assert resp.is_idle is True
    assert resp.has_backlog is False


@pytest.mark.asyncio
async def test_clear_queue_cancels_pending_and_running():
    db = AsyncMock()
    res = MagicMock()
    res.rowcount = 4
    db.execute = AsyncMock(return_value=res)
    engine = QueueWorkerEngine(db)
    out = await engine.clear_queue(uuid4())
    assert out.cancelled == 4
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_clear_queue_keep_running_zero_pending_cancelled():
    db = AsyncMock()
    res = MagicMock()
    res.rowcount = 0
    db.execute = AsyncMock(return_value=res)
    engine = QueueWorkerEngine(db)
    out = await engine.clear_queue(uuid4(), ClearQueueRequest(keep_running=True))
    assert out.cancelled == 0


# ========== Router wiring ==========

def test_router_exposed_in_openapi():
    from app.main import app
    paths = app.openapi()["paths"]
    base = "/api/v1/workflow-tasks"
    assert base in paths
    assert f"{base}/health" in paths
    assert f"{base}/queues/{{queue_id}}/claim" in paths
    assert f"{base}/sweep-timeouts" in paths
    # doubled prefix must NOT exist
    assert "/api/v1/api/v1/workflow-tasks" not in paths


def test_literal_routes_not_shadowed():
    """/health must not be captured by /{task_id}."""
    from app.main import app
    paths = app.openapi()["paths"]
    base = "/api/v1/workflow-tasks"
    assert f"{base}/health" in paths
    assert f"{base}/{{task_id}}" in paths


def test_health_route_registered_before_param_route():
    """Regression guard: the literal GET /health route must be registered
    before the parameterised GET /{task_id} route on the workflow-tasks
    router, otherwise FastAPI (which matches in registration order) swallows
    /health into task_id and 500s on UUID parse.

    Inspects the flat, registration-ordered router (not the app-level routes,
    which nest included routers as opaque ``_IncludedRouter`` objects).
    """
    from app.routers import workflow_task as wf
    paths = [getattr(r, "path", "") for r in wf.router.routes]
    health_idx = next(
        (i for i, p in enumerate(paths) if p.endswith("/workflow-tasks/health")),
        None,
    )
    param_idx = next(
        (i for i, p in enumerate(paths) if p.endswith("/workflow-tasks/{task_id}")),
        None,
    )
    assert health_idx is not None, "GET /health route missing on workflow-tasks router"
    assert param_idx is not None, "GET /{task_id} route missing on workflow-tasks router"
    assert health_idx < param_idx, "GET /health must be registered before GET /{task_id}"


def test_get_task_endpoint_uses_task_id_path_only():
    """The GET /{task_id} route must be a real path-param route, not shadowed."""
    from app.main import app
    paths = app.openapi()["paths"]
    base = "/api/v1/workflow-tasks"
    assert f"{base}/{{task_id}}" in paths
    assert "get" in paths[f"{base}/{{task_id}}"]


def test_import_guard():
    import app.main  # noqa: F401
    import app.services.workflow_task  # noqa: F401
    import app.routers.workflow_task  # noqa: F401
    import app.schemas.workflow_task  # noqa: F401
    import app.db.models.workflow_task  # noqa: F401


def test_health_self_report():
    engine = QueueWorkerEngine(MagicMock())
    health = engine.health()
    assert health["service"] == "queue-worker-engine"
    assert health["db_enabled"] is True


# ========== P1-R2: crash recovery + sweep-and-retry ==========

class _SeqDB:
    """Stateful fake DB: db.execute pops scripted results in call order.

    Mirrors the repo's ``_execute_result`` convention (result has
    ``.scalars().all()`` / ``.first()`` / ``.scalar_one_or_none()``) but lets a
    multi-call flow (sweep -> fetch -> retry) script a different result for
    each execute() without a fixed-length side_effect list.
    """

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self.execute_calls = 0
        self.committed = 0

    def _next_result(self):
        idx = self.execute_calls - 1  # execute_calls is incremented in execute()
        if self._scripts and 0 <= idx < len(self._scripts):
            return self._scripts[idx]
        return _execute_result()

    async def execute(self, stmt):
        self.execute_calls += 1
        return self._next_result()

    async def commit(self):
        self.committed += 1

    async def refresh(self, obj):
        pass


@pytest.mark.asyncio
async def test_recover_stale_running_resets_to_pending():
    """P1-R2: stuck running tasks are reset to pending at boot."""
    task = _make_task(status="running", claimed_at=datetime.now(timezone.utc) - timedelta(hours=2),
                      started_at=datetime.now(timezone.utc) - timedelta(hours=2))
    db = _SeqDB([_execute_result(task), _execute_result()])
    engine = QueueWorkerEngine(db)
    recovered = await engine.recover_stale_running()
    assert recovered == 1
    assert task.status == "pending"
    assert task.claimed_at is None
    assert task.started_at is None
    assert task.finished_at is None
    assert task.result is None
    assert task.worker_id is None
    assert db.committed >= 1


@pytest.mark.asyncio
async def test_recover_stale_running_no_running_returns_zero():
    db = _SeqDB([_execute_result()])
    engine = QueueWorkerEngine(db)
    assert await engine.recover_stale_running() == 0


@pytest.mark.asyncio
async def test_recover_stale_running_respects_staleness_window():
    """A task claimed very recently (within the staleness window) is NOT reset
    (a live sibling worker may still own it); only clearly-stale ones are.
    """
    fresh = _make_task(status="running", claimed_at=datetime.now(timezone.utc))
    stale = _make_task(status="running", claimed_at=datetime.now(timezone.utc) - timedelta(hours=2))
    db = _SeqDB([_execute_result(fresh, stale)])
    engine = QueueWorkerEngine(db)
    recovered = await engine.recover_stale_running(staleness_seconds=3600)
    assert recovered == 1
    assert fresh.status == "running"   # recent -> untouched
    assert stale.status == "pending"   # clearly stale -> reset


@pytest.mark.asyncio
async def test_sweep_and_retry_requeues_swept_task():
    """P1-R2: a timed-out running task is swept to ``timeout`` and re-queued to
    ``pending`` (retries remain), so it actually runs again — not an orphan.
    """
    task = _make_task(status="running", timeout_seconds=5,
                      started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
                      retry_count=0, max_retries=2)
    # Call order: (1) running select [task], (2) queue lookup [none],
    # (3) terminal backlog select of WorkflowTask.id [task.id],
    # (4) retry_task _get_task [task].
    db = _SeqDB([
        _execute_result(task),
        _execute_result(),
        _execute_result(task.id),  # the backlog query selects WorkflowTask.id
        _execute_result(task),
    ])
    engine = QueueWorkerEngine(db)
    summary = await engine.sweep_and_retry()
    assert summary["swept"] == 1
    assert summary["requeued"] == 1
    assert task.status == "pending"      # back in the queue for re-execution
    assert task.retry_count == 1


@pytest.mark.asyncio
async def test_sweep_and_retry_does_not_exceed_max_retries():
    """A task with no retries left stays terminal (swept, not re-queued)."""
    task = _make_task(status="running", timeout_seconds=5,
                      started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
                      retry_count=2, max_retries=2)
    db = _SeqDB([
        _execute_result(task),   # running select
        _execute_result(),       # queue lookup (none)
        _execute_result(),       # terminal backlog: not retryable -> empty
    ])
    engine = QueueWorkerEngine(db)
    summary = await engine.sweep_and_retry()
    assert summary["swept"] == 1
    assert summary["requeued"] == 0
    assert task.status == "timeout"   # terminal, unrecoverable by default
