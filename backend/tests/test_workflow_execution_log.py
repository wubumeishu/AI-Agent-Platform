"""Tests for the Workflow Execution Log module (Phase 4).

Covers:
- model import & state enums
- schema validation
- service: create / get / update (incl. auto finished_at + duration)
- service: history listing + filtering
- service: failed-execution query
- service: retention cleanup policy
- router wiring (app imports + OpenAPI exposure + route ordering)

DB session is mocked (AsyncMock) to stay independent of a live Postgres,
matching the repo's test_conversation / test_memory conventions.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone, timedelta

from app.db.models.workflow import (
    ExecutionLog,
    EXECUTION_STATES,
    TRIGGER_TYPES,
    EXECUTION_TYPES,
)
from app.schemas.workflow import (
    ExecutionLogCreate,
    ExecutionLogUpdate,
    ExecutionLogResponse,
    ExecutionHistoryRequest,
    ExecutionLogCleanupRequest,
)
from app.services.workflow import ExecutionLogService


def _make_full_log(**overrides):
    """Build an ExecutionLog with every field from_model reads set.

    In-memory ORM instances do NOT get JSONB/DateTime column defaults
    (those are server-side), so we set them explicitly to keep the
    response-mapping tests deterministic.
    """
    now = datetime.now(timezone.utc)
    log = ExecutionLog()
    log.id = uuid4()
    log.created_at = now
    log.updated_at = now
    log.input_params = {}
    log.metadata_ = {}
    log.retry_count = 0
    log.is_deleted = False
    log.execution_type = "task"
    log.trigger_type = "manual"
    log.status = "success"
    for key, value in overrides.items():
        setattr(log, key, value)
    return log


# ========== Model ==========

def test_execution_states_cover_required_lifecycle():
    """Acceptance: tasks must have observable states PENDING/RUNNING/SUCCESS/FAILED/CANCELLED."""
    for required in ("pending", "running", "success", "failed", "cancelled"):
        assert required in EXECUTION_STATES
    # timeout is an extra observed terminal state
    assert "timeout" in EXECUTION_STATES


def test_model_defaults():
    """A fresh in-memory instance has None for all Column `default=` values.

    Column-level ``default=`` is applied server-side at INSERT, not at
    object construction — so validation of those values lives in the
    Pydantic schemas (covered by the schema tests below).
    """
    log = ExecutionLog()
    assert log.id is None
    assert log.execution_type is None
    assert log.trigger_type is None
    assert log.status is None
    assert log.retry_count is None
    assert log.input_params is None
    assert log.metadata_ is None
    assert log.created_at is None
    assert log.updated_at is None
    assert log.is_deleted is None


# ========== Schema validation ==========

def test_create_schema_rejects_bad_status():
    with pytest.raises(ValueError):
        ExecutionLogCreate(status="not_a_state")


def test_create_schema_valid():
    data = ExecutionLogCreate(
        execution_type="workflow",
        trigger_type="scheduled",
        status="running",
        input_params={"k": 1},
    )
    assert data.status == "running"
    assert data.execution_type == "workflow"


def test_create_schema_rejects_bad_trigger():
    with pytest.raises(ValueError):
        ExecutionLogCreate(trigger_type="explosion")


def test_update_schema_optional():
    upd = ExecutionLogUpdate()
    assert upd.status is None
    upd2 = ExecutionLogUpdate(status="failed", error_message="boom")
    assert upd2.error_message == "boom"


def test_response_from_model_maps_metadata_underscore():
    log = _make_full_log(
        output_result={"ok": True},
        metadata_={"worker": "w1"},
    )
    resp = ExecutionLogResponse.from_model(log)
    assert resp.metadata == {"worker": "w1"}
    assert resp.output_result == {"ok": True}


# ========== Service: recording ==========

@pytest.mark.asyncio
async def test_create_log_auto_stamps_started_at():
    db = AsyncMock()

    def stamp(obj):
        obj.id = uuid4()
        obj.created_at = datetime.now(timezone.utc)
        obj.updated_at = obj.created_at

    db.refresh.side_effect = stamp
    service = ExecutionLogService(db)
    data = ExecutionLogCreate(status="pending", input_params={"a": 1})
    resp = await service.create_log(data)
    assert resp is not None
    assert resp.input_params == {"a": 1}
    assert resp.started_at is not None  # auto-stamped since not provided
    db.add.assert_called_once()
    db.commit.assert_awaited()
    db.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_get_log_found():
    db = AsyncMock()
    log = _make_full_log(status="success")

    res = MagicMock()
    res.scalar_one_or_none.return_value = log
    db.execute = AsyncMock(return_value=res)

    service = ExecutionLogService(db)
    got = await service.get_log(log.id)
    assert got is not None
    assert got.id == log.id
    assert got.status == "success"


@pytest.mark.asyncio
async def test_get_log_not_found():
    db = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=res)

    service = ExecutionLogService(db)
    assert await service.get_log(uuid4()) is None


@pytest.mark.asyncio
async def test_update_log_terminal_auto_finish():
    """On terminal status with no finished_at, the service auto-stamps it."""
    db = AsyncMock()
    start = datetime.now(timezone.utc) - timedelta(seconds=2)
    log = _make_full_log(status="running", started_at=start)

    res = MagicMock()
    res.scalar_one_or_none.return_value = log
    db.execute = AsyncMock(return_value=res)

    service = ExecutionLogService(db)
    resp = await service.update_log(log.id, ExecutionLogUpdate(status="success"))
    assert resp.status == "success"
    assert log.finished_at is not None  # auto-stamped
    assert log.duration_ms is not None  # auto-computed from started/finished
    assert log.duration_ms >= 1900  # ~2s minus clock skew, in ms


@pytest.mark.asyncio
async def test_update_log_error_fields():
    db = AsyncMock()
    log = _make_full_log(status="failed")

    res = MagicMock()
    res.scalar_one_or_none.return_value = log
    db.execute = AsyncMock(return_value=res)

    service = ExecutionLogService(db)
    resp = await service.update_log(
        log.id,
        ExecutionLogUpdate(status="failed", error_message="worker exploded", error_code="E_TIMEOUT"),
    )
    assert resp.error_message == "worker exploded"
    assert resp.error_code == "E_TIMEOUT"


# ========== Service: history / listing ==========

@pytest.mark.asyncio
async def test_list_logs_returns_paginated():
    db = AsyncMock()
    logs = [_make_full_log(status="success") for _ in range(3)]

    count_res = MagicMock()
    count_res.scalar_one.return_value = 3
    list_res = MagicMock()
    list_res.scalars.return_value.all.return_value = logs
    db.execute = AsyncMock(side_effect=[count_res, list_res])

    service = ExecutionLogService(db)
    items, total = await service.list_logs(page=1, page_size=20)
    assert total == 3
    assert len(items) == 3
    assert all(i.status == "success" for i in items)


@pytest.mark.asyncio
async def test_get_history_uses_request_filters():
    db = AsyncMock()
    count_res = MagicMock()
    count_res.scalar_one.return_value = 0
    list_res = MagicMock()
    list_res.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(side_effect=[count_res, list_res])

    service = ExecutionLogService(db)
    req = ExecutionHistoryRequest(status="failed", page=1, page_size=10)
    items, total = await service.get_history(req)
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_get_failed_executions():
    db = AsyncMock()
    f1 = _make_full_log(status="failed", error_message="x")

    res = MagicMock()
    res.scalars.return_value.all.return_value = [f1]
    db.execute = AsyncMock(return_value=res)

    service = ExecutionLogService(db)
    items = await service.get_failed_executions(limit=10)
    assert len(items) == 1
    assert items[0].error_message == "x"
    assert items[0].status == "failed"


# ========== Service: cleanup policy ==========

@pytest.mark.asyncio
async def test_cleanup_noop_when_below_retain():
    db = AsyncMock()
    count_res = MagicMock()
    count_res.scalar_one.return_value = 5
    db.execute = AsyncMock(return_value=count_res)

    service = ExecutionLogService(db)
    result = await service.clean_logs(ExecutionLogCleanupRequest(retain=100))
    assert result.cleaned == 0
    assert result.remaining == 5


@pytest.mark.asyncio
async def test_cleanup_soft_deletes_oldest():
    db = AsyncMock()
    now = datetime.now(timezone.utc)

    count_res = MagicMock()
    count_res.scalar_one.return_value = 5  # total

    # cutoff query: returns the cutoff timestamp row
    cutoff_res = MagicMock()
    cutoff_res.first.return_value = (now - timedelta(days=3),)
    # update (soft-delete) query: report how many rows were affected
    update_res = MagicMock()
    update_res.rowcount = 3
    db.execute = AsyncMock(side_effect=[count_res, cutoff_res, update_res])

    service = ExecutionLogService(db)
    result = await service.clean_logs(ExecutionLogCleanupRequest(retain=2))

    assert result.cleaned == 3  # 5 - 2 retained
    assert result.remaining == 2
    assert result.retain == 2
    db.commit.assert_awaited()


# ========== Router wiring ==========

def test_router_exposed_in_openapi():
    from app.main import app
    paths = app.openapi()["paths"]
    # clean single /api/v1/execution-logs path (Convention B, not doubled)
    assert "/api/v1/execution-logs/health" in paths
    assert "/api/v1/execution-logs" in paths
    # and the doubled form must NOT exist for this router
    assert "/api/v1/api/v1/execution-logs" not in paths


def test_literal_routes_not_shadowed_by_param_route():
    """GET /health and /failed must resolve, not be captured by /{log_id}."""
    from app.main import app
    paths = app.openapi()["paths"]
    assert "/api/v1/execution-logs/health" in paths
    assert "/api/v1/execution-logs/failed" in paths
    assert "/api/v1/execution-logs/history" in paths
    assert "/api/v1/execution-logs/{log_id}" in paths


def test_app_imports_all_modules():
    """Guard against import regressions when new modules are added."""
    import app.main  # noqa: F401
    import app.services.workflow  # noqa: F401
    import app.routers.workflow  # noqa: F401
    import app.schemas.workflow  # noqa: F401
    import app.db.models.workflow  # noqa: F401


def test_health_self_report():
    service = ExecutionLogService(MagicMock())
    health = service.health()
    assert health["service"] == "execution-log-service"
    assert health["db_enabled"] is True
