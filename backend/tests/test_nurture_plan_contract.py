"""
Contract B consistency tests: nurture_plan_item = single source of truth.

Ruling: t_1814d03d (Phase 5 architecture review, report §7 Contract B) and
task t_4b55abe8 (P1 dual-track unification).

Contract:
- The ordered step definitions of a NurturePlan live ONLY in the
  ``nurture_plan_item`` table.
- The legacy ``nurture_plan.sequence_steps`` JSON column is retired:
  new code writes [] and never reads it back as a data source.
- ``create_nurture_plan(sequence_steps=[...])`` INSERTs N rows in the
  same transaction (surplus rows never appear - the create path starts
  from an empty table and must leave N live rows).
- ``update_nurture_plan(sequence_steps=[...])`` reconciles the rows:
  upsert by step_order, surplus rows soft-deleted (is_deleted=True).
- ``get_nurture_plan`` returns steps from the table query only.

Style: same mock-session approach as tests/test_nurture_plan.py, but with
an in-memory row store so the real upsert/soft-delete logic in
``_reconcile_plan_items`` executes for real instead of being mocked away.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from typing import List

from app.db.models.private_domain import NurturePlan, NurturePlanItem
from app.schemas.private_domain import NurturePlanCreate, NurturePlanUpdate
from app.services.nurture_plan_service import (
    create_nurture_plan,
    update_nurture_plan,
    get_nurture_plan,
)
from app.services.private_domain import (
    create_nurture_plan as legacy_create_nurture_plan,
    update_nurture_plan as legacy_update_nurture_plan,
)


def _make_row(plan_id, step_order, delay_hours=0, trigger_type="time_based",
              content_id=None, config=None, is_deleted=False) -> NurturePlanItem:
    row = NurturePlanItem(
        plan_id=plan_id,
        step_order=step_order,
        content_id=content_id,
        delay_hours=delay_hours,
        trigger_type=trigger_type,
        config=config if config is not None else {},
    )
    row.id = uuid4()
    row.status = "active"
    row.is_deleted = is_deleted
    row.created_at = None
    return row


class Store:
    """In-memory stand-in for the nurture_plan_item table of one plan."""

    def __init__(self, plan_id, rows: List[NurturePlanItem]):
        self.plan_id = plan_id
        self.rows = rows

    def active(self) -> List[NurturePlanItem]:
        return [r for r in self.rows if r.is_deleted is False]

    def by_order(self) -> List[NurturePlanItem]:
        return sorted(self.rows, key=lambda r: (r.is_deleted, r.step_order))


def _result(rows) -> MagicMock:
    m = MagicMock()
    m.scalars.return_value.all.return_value = list(rows)
    return m


def _plan_result(plan):
    m = MagicMock()
    m.scalar_one_or_none.return_value = plan
    return m


def _make_session(store: Store, plan, with_plan_select: bool = False):
    """Mock AsyncSession wired to `store`.

    Each db.execute() is served from the store's *live* state (not a
    snapshot), so the reconcile pre-sweep and post-sweep SELECTs reflect
    rows staged via db.add between the two queries.

    Call sequences per service entry point:
      create_nurture_plan:   [reconcile-before, reconcile-final]
      update_nurture_plan:   [plan-select, reconcile-before, reconcile-final]
      get_nurture_plan:      [plan-select, items-select]
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    def on_add(obj):
        if isinstance(obj, NurturePlanItem):
            if obj.plan_id is None:
                obj.plan_id = store.plan_id
            if obj.id is None:
                obj.id = uuid4()
            if obj.status is None:
                obj.status = "active"
            if obj.is_deleted is None:
                obj.is_deleted = False
            if obj.created_at is None:
                obj.created_at = None
            store.rows.append(obj)

    db.add.side_effect = on_add

    call = {"n": 0}

    def execute(stmt):
        call["n"] += 1
        if with_plan_select and call["n"] == 1:
            return _plan_result(plan)
        # reconcile / item SELECTs: serve live store state
        return _result(store.active())

    db.execute.side_effect = execute
    return db


# ---- contract: create path ----

@pytest.mark.asyncio
async def test_contract_b_create_inserts_item_rows():
    plan_id = uuid4()
    store = Store(plan_id, [])
    data = NurturePlanCreate(
        channel_id=uuid4(),
        account_id=uuid4(),
        name="Contract B Plan",
        schedule_type="drip",
        sequence_steps=[
            {"content_id": str(uuid4()), "delay_hours": 0, "trigger_type": "time_based"},
            {"content_id": str(uuid4()), "delay_hours": 24, "trigger_type": "event_based"},
            {"delay_hours": 48},
        ],
    )
    db = _make_session(store, None)

    result = await create_nurture_plan(db, data)

    # (1) N rows inserted into the SoT table, live (not soft-deleted)
    items = [r for r in db.add.call_args_list if r.args and isinstance(r.args[0], NurturePlanItem)]
    assert len(items) == 3
    assert len(store.active()) == 3
    live = sorted(store.active(), key=lambda r: r.step_order)
    assert [r.step_order for r in live] == [0, 1, 2]
    assert [r.delay_hours for r in live] == [0, 24, 48]
    assert [r.trigger_type for r in live] == ["time_based", "event_based", "time_based"]
    # content_id coerced from str -> UUID
    assert isinstance(live[0].content_id, type(uuid4()))

    # (2) legacy JSON column written as []
    plan_row = [c.args[0] for c in db.add.call_args_list
                if c.args and isinstance(c.args[0], NurturePlan)][0]
    assert plan_row.sequence_steps == []

    # (3) response exposes steps from the table, never sequence_steps
    assert "sequence_steps" not in result
    assert len(result["steps"]) == 3


@pytest.mark.asyncio
async def test_contract_b_create_without_steps():
    plan_id = uuid4()
    store = Store(plan_id, [])
    data = NurturePlanCreate(
        channel_id=uuid4(),
        account_id=uuid4(),
        name="No Steps",
    )
    db = _make_session(store, None)

    result = await create_nurture_plan(db, data)

    assert result["steps"] == []
    plan_row = [c.args[0] for c in db.add.call_args_list
                if c.args and isinstance(c.args[0], NurturePlan)][0]
    assert plan_row.sequence_steps == []
    assert [r for r in store.rows if isinstance(r, NurturePlanItem)] == []


# ---- contract: update path (reconcile) ----

@pytest.mark.asyncio
async def test_contract_b_update_upsert_and_soft_delete_surplus():
    plan_id = uuid4()
    # 3 live rows pre-existing; request shrinks to 2
    store = Store(plan_id, [
        _make_row(plan_id, 0, delay_hours=0),
        _make_row(plan_id, 1, delay_hours=24),
        _make_row(plan_id, 2, delay_hours=48),
    ])
    plan = NurturePlan(channel_id=uuid4(), account_id=uuid4(), name="P")
    plan.id = plan_id
    plan.status = "draft"
    plan.schedule_type = "fixed"
    plan.sequence_steps = [{"stale": True}]  # proves the column is not carried forward

    db = _make_session(store, plan, with_plan_select=True)
    result = await update_nurture_plan(
        db, plan_id,
        NurturePlanUpdate(
            name="P2",
            sequence_steps=[
                {"content_id": str(uuid4()), "delay_hours": 0},
                {"delay_hours": 72, "trigger_type": "event_based"},
            ],
        ),
    )

    live = sorted(store.active(), key=lambda r: r.step_order)
    # upserted: 2 live rows exactly as requested
    assert [r.step_order for r in live] == [0, 1]
    assert [r.delay_hours for r in live] == [0, 72]
    assert live[0].trigger_type == "time_based"
    assert live[1].trigger_type == "event_based"
    # surplus row (order 2) soft-deleted but retained for audit
    surplus = [r for r in store.rows if r.step_order == 2][0]
    assert surplus.is_deleted is True
    # legacy JSON column stayed []-like (never written from the payload)
    assert plan.sequence_steps == []
    # response: updated name, steps from table, no sequence_steps key
    assert result["name"] == "P2"
    assert "sequence_steps" not in result
    assert len(result["steps"]) == 2


@pytest.mark.asyncio
async def test_contract_b_update_clear_all_steps():
    plan_id = uuid4()
    store = Store(plan_id, [
        _make_row(plan_id, 0),
        _make_row(plan_id, 1),
    ])
    plan = NurturePlan(channel_id=uuid4(), account_id=uuid4(), name="P")
    plan.id = plan_id
    plan.status = "draft"
    plan.schedule_type = "fixed"
    plan.sequence_steps = []

    db = _make_session(store, plan, with_plan_select=True)
    result = await update_nurture_plan(db, plan_id, NurturePlanUpdate(sequence_steps=[]))

    assert store.active() == []
    assert all(r.is_deleted is True for r in store.rows)
    assert result["steps"] == []
    assert plan.sequence_steps == []


@pytest.mark.asyncio
async def test_contract_b_update_without_steps_no_reconcile():
    plan_id = uuid4()
    store = Store(plan_id, [_make_row(plan_id, 0), _make_row(plan_id, 1)])
    plan = NurturePlan(channel_id=uuid4(), account_id=uuid4(), name="P")
    plan.id = plan_id
    plan.status = "draft"
    plan.schedule_type = "fixed"
    plan.sequence_steps = []

    # no sequence_steps in payload -> only the plan SELECT happens
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock(return_value=_plan_result(plan))

    result = await update_nurture_plan(db, plan_id, NurturePlanUpdate(name="Renamed"))

    # table untouched
    assert [r.is_deleted for r in store.rows] == [False, False]
    assert result["name"] == "Renamed"
    assert result["steps"] == []


@pytest.mark.asyncio
async def test_contract_b_update_not_found():
    plan_id = uuid4()
    store = Store(plan_id, [])
    plan = NurturePlan(channel_id=uuid4(), account_id=uuid4(), name="P")
    plan.id = plan_id
    plan.status = "draft"

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    none_result = MagicMock()
    none_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=none_result)

    result = await update_nurture_plan(
        db, plan_id, NurturePlanUpdate(sequence_steps=[{"delay_hours": 1}])
    )

    assert result is None
    assert store.rows == []  # no reconcile happened


# ---- contract: read path ----

@pytest.mark.asyncio
async def test_contract_b_get_returns_steps_from_table_only():
    plan_id = uuid4()
    store = Store(plan_id, [
        _make_row(plan_id, 0, delay_hours=0),
        _make_row(plan_id, 1, delay_hours=24),
        _make_row(plan_id, 2, is_deleted=True),  # soft-deleted: must NOT appear
    ])
    plan = NurturePlan(channel_id=uuid4(), account_id=uuid4(), name="P")
    plan.id = plan_id
    plan.status = "active"
    plan.schedule_type = "drip"
    plan.sequence_steps = [{"ghost": True}]  # legacy data may linger in the column

    db = _make_session(store, plan, with_plan_select=True)
    result = await get_nurture_plan(db, plan_id)

    assert result is not None
    assert "sequence_steps" not in result
    assert [s["step_order"] for s in result["steps"]] == [0, 1]
    assert [s["delay_hours"] for s in result["steps"]] == [0, 24]
    assert all(not s.get("is_deleted") for s in result["steps"])


# ---- contract: legacy entry point keeps the same behaviour ----

@pytest.mark.asyncio
async def test_contract_b_legacy_create_delegates():
    plan_id = uuid4()
    store = Store(plan_id, [])
    data = NurturePlanCreate(
        channel_id=uuid4(),
        account_id=uuid4(),
        name="Legacy Entry",
        sequence_steps=[{"delay_hours": 5}, {"delay_hours": 10}],
    )
    db = _make_session(store, None)

    result = await legacy_create_nurture_plan(db, data)

    assert "sequence_steps" not in result
    assert len(result["steps"]) == 2
    assert len(store.active()) == 2
    plan_row = [c.args[0] for c in db.add.call_args_list
                if c.args and isinstance(c.args[0], NurturePlan)][0]
    assert plan_row.sequence_steps == []


@pytest.mark.asyncio
async def test_contract_b_legacy_update_delegates():
    plan_id = uuid4()
    store = Store(plan_id, [
        _make_row(plan_id, 0),
        _make_row(plan_id, 1),
        _make_row(plan_id, 2),
    ])
    plan = NurturePlan(channel_id=uuid4(), account_id=uuid4(), name="P")
    plan.id = plan_id
    plan.status = "draft"
    plan.schedule_type = "fixed"
    plan.sequence_steps = []

    db = _make_session(store, plan, with_plan_select=True)
    result = await legacy_update_nurture_plan(
        db, plan_id, NurturePlanUpdate(sequence_steps=[{"delay_hours": 1}])
    )

    assert result is not None
    assert len(store.active()) == 1
    assert len(store.rows) == 3  # surplus rows retained as soft-deleted
    assert all(r.is_deleted for r in store.rows if r.step_order != 0)
    assert plan.sequence_steps == []
