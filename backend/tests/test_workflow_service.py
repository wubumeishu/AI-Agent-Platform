"""Service-layer tests for WorkflowService (t_wf_002).

Uses a mocked AsyncSession following the project's established pattern:
``db.execute`` returns pre-built result mocks, ``db.add`` is spied on to
capture the constructed ORM object so response mapping can be exercised.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, call
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowUpdate,
    TriggerCreate,
    TriggerUpdate,
    ConditionCreate,
    ConditionUpdate,
    ActionCreate,
    ActionUpdate,
)
from app.services.workflow import WorkflowService, WorkflowNotFoundError


def make_db():
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def orm_workhorse(**overrides):
    """Build a minimally complete ORM mock for a given table role."""
    obj = MagicMock()
    defaults = dict(
        id=overrides.pop("id", uuid4()),
        created_at="2026-09-14T00:00:00Z",
        updated_at="2026-09-14T00:00:00Z",
    )
    defaults.update(overrides)
    for key, value in defaults.items():
        setattr(obj, key, value)
    return obj


def scalars_result(rows):
    """An execute-result mock whose .scalars().all() returns rows."""
    m = MagicMock()
    m.scalars.return_value.all.return_value = rows
    return m


def scalar_result(obj):
    """An execute-result mock whose .scalar_one_or_none() returns obj."""
    m = MagicMock()
    m.scalar_one_or_none.return_value = obj
    return m


def workflow_orm(**kw):
    base = dict(
        name="Auto follow-up", description="desc", workflow_type="auto",
        status="active", config={"a": 1}, execution_policy={"timeout_s": 60},
        version=1, is_deleted=False,
    )
    base.update(kw)
    return orm_workhorse(**base)


def trigger_orm(workflow_id, **kw):
    base = dict(
        workflow_id=workflow_id, name="t", trigger_type="manual",
        spec={}, enabled=True, is_deleted=False,
    )
    base.update(kw)
    return orm_workhorse(**base)


def condition_orm(trigger_id, **kw):
    base = dict(
        trigger_id=trigger_id, name="c",
        expression={"field": "x", "operator": "eq", "value": 1},
        logic="and", priority=0, is_deleted=False,
    )
    base.update(kw)
    return orm_workhorse(**base)


def action_orm(condition_id, **kw):
    base = dict(
        condition_id=condition_id, name="a", action_type="message",
        params={}, priority=0, is_deleted=False,
    )
    base.update(kw)
    return orm_workhorse(**base)


# ========== Workflow CRUD ==========

class TestWorkflowCRUD:
    @pytest.mark.asyncio
    async def test_create_persists(self):
        db = make_db()
        svc = WorkflowService(db)
        result = await svc.create_workflow(WorkflowCreate(name="WF1", config={"k": "v"}))
        assert result.name == "WF1"
        assert result.status == "draft"
        assert result.version == 1
        added = db.add.call_args[0][0]
        assert added.name == "WF1"
        assert added.config == {"k": "v"}
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_get_found(self):
        db = make_db()
        wf = workflow_orm()
        res = MagicMock(); res.scalar_one_or_none.return_value = wf
        db.execute.return_value = res
        result = await WorkflowService(db).get_workflow(wf.id)
        assert result.id == wf.id

    @pytest.mark.asyncio
    async def test_get_missing(self):
        db = make_db()
        res = MagicMock(); res.scalar_one_or_none.return_value = None
        db.execute.return_value = res
        assert await WorkflowService(db).get_workflow(uuid4()) is None

    @pytest.mark.asyncio
    async def test_list_pagination(self):
        db = make_db()
        w1, w2 = workflow_orm(name="A"), workflow_orm(name="B")
        count_res = MagicMock(); count_res.scalar_one.return_value = 2
        db.execute.side_effect = [count_res, scalars_result([w1, w2])]
        items, total = await WorkflowService(db).list_workflows(page=1, page_size=2)
        assert total == 2 and len(items) == 2
        assert [i.name for i in items] == ["A", "B"]

    @pytest.mark.asyncio
    async def test_update_bumps_version(self):
        db = make_db()
        wf = workflow_orm()
        res = MagicMock(); res.scalar_one_or_none.return_value = wf
        db.execute.return_value = res
        result = await WorkflowService(db).update_workflow(wf.id, WorkflowUpdate(status="paused"))
        assert result.status == "paused"
        assert wf.version == 2
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_missing_returns_none(self):
        db = make_db()
        res = MagicMock(); res.scalar_one_or_none.return_value = None
        db.execute.return_value = res
        assert await WorkflowService(db).update_workflow(uuid4(), WorkflowUpdate()) is None

    @pytest.mark.asyncio
    async def test_delete_cascades_soft_delete(self):
        db = make_db()
        wf = workflow_orm()
        res = MagicMock(); res.scalar_one_or_none.return_value = wf

        def scalars_result(rows):
            m = MagicMock()
            m.scalars.return_value.all.return_value = rows
            return m

        # select(Model.id) returns raw UUID scalars, not model rows
        trig_id, cond_id = uuid4(), uuid4()
        upd = MagicMock(); upd.rowcount = 1
        # execute order: lookup, select trig ids, select cond ids,
        # update triggers, update conditions, update actions
        db.execute.side_effect = [res, scalars_result([trig_id]), scalars_result([cond_id]), upd, upd, upd]
        result = await WorkflowService(db).delete_workflow(wf.id)
        assert result is True
        assert wf.is_deleted is True
        assert db.execute.await_count == 6
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self):
        db = make_db()
        res = MagicMock(); res.scalar_one_or_none.return_value = None
        db.execute.return_value = res
        assert await WorkflowService(db).delete_workflow(uuid4()) is False


    @pytest.mark.asyncio
    async def test_update_with_config_and_policy(self):
        db = make_db()
        wf = workflow_orm()
        res = MagicMock(); res.scalar_one_or_none.return_value = wf
        db.execute.return_value = res
        result = await WorkflowService(db).update_workflow(
            wf.id,
            WorkflowUpdate(
                config={"new": True},
                execution_policy={"max_retries": 3},
                workflow_type="manual",
                description="updated desc",
            ),
        )
        assert wf.config == {"new": True}
        assert wf.execution_policy == {"max_retries": 3}
        assert wf.workflow_type == "manual"
        assert wf.description == "updated desc"
        assert result.config == {"new": True}
        assert wf.version == 2

    @pytest.mark.asyncio
    async def test_delete_without_children(self):
        """Delete a workflow that has no triggers/conditions yet."""
        db = make_db()
        wf = workflow_orm()
        res = MagicMock(); res.scalar_one_or_none.return_value = wf
        no_trigs = MagicMock()
        no_trigs.scalars.return_value.all.return_value = []
        upd = MagicMock(); upd.rowcount = 0
        db.execute.side_effect = [res, no_trigs, upd]
        result = await WorkflowService(db).delete_workflow(wf.id)
        assert result is True
        assert wf.is_deleted is True
        assert db.execute.await_count == 3  # no condition/action updates issued


# ========== Trigger CRUD ==========

class TestTriggerCRUD:
    @pytest.mark.asyncio
    async def test_create_on_existing_workflow(self):
        db = make_db()
        wf = workflow_orm()
        res = MagicMock(); res.scalar_one_or_none.return_value = wf
        db.execute.return_value = res
        result = await WorkflowService(db).create_trigger(
            wf.id, TriggerCreate(trigger_type="cron", spec={"cron": "* * * * *"})
        )
        added = db.add.call_args[0][0]
        assert added.workflow_id == wf.id
        assert added.trigger_type == "cron"
        assert result.trigger_type == "cron"

    @pytest.mark.asyncio
    async def test_create_raises_for_missing_workflow(self):
        db = make_db()
        res = MagicMock(); res.scalar_one_or_none.return_value = None
        db.execute.return_value = res
        with pytest.raises(WorkflowNotFoundError):
            await WorkflowService(db).create_trigger(uuid4(), TriggerCreate())

    @pytest.mark.asyncio
    async def test_list_triggers(self):
        db = make_db()
        wf = workflow_orm()
        t = trigger_orm(wf.id)
        lookup = MagicMock(); lookup.scalar_one_or_none.return_value = wf
        db.execute.side_effect = [lookup, scalars_result([t])]
        items = await WorkflowService(db).list_triggers(wf.id)
        assert len(items) == 1 and items[0].workflow_id == wf.id

    @pytest.mark.asyncio
    async def test_update_partial(self):
        db = make_db()
        t = trigger_orm(uuid4())
        res = MagicMock(); res.scalar_one_or_none.return_value = t
        db.execute.return_value = res
        result = await WorkflowService(db).update_trigger(
            t.id, TriggerUpdate(enabled=False, name="renamed")
        )
        assert t.enabled is False
        assert t.name == "renamed"
        assert result.enabled is False

    @pytest.mark.asyncio
    async def test_delete_trigger_cascades(self):
        db = make_db()
        t = trigger_orm(uuid4())

        def scalars_result(rows):
            m = MagicMock()
            m.scalars.return_value.all.return_value = rows
            return m

        lookup = MagicMock(); lookup.scalar_one_or_none.return_value = t
        upd = MagicMock(); upd.rowcount = 1
        # select(WorkflowCondition.id) returns raw UUID scalars
        cond_id = uuid4()
        # execute order: lookup, update conditions, select cond ids, update actions
        db.execute.side_effect = [lookup, upd, scalars_result([cond_id]), upd]
        assert await WorkflowService(db).delete_trigger(t.id) is True
        assert t.is_deleted is True
        assert db.execute.await_count == 4


# ========== Condition CRUD ==========

class TestConditionCRUD:
    @pytest.mark.asyncio
    async def test_create(self):
        db = make_db()
        t = trigger_orm(uuid4())
        res = MagicMock(); res.scalar_one_or_none.return_value = t
        db.execute.return_value = res
        data = ConditionCreate(expression={"field": "orders", "operator": "gt", "value": 5})
        result = await WorkflowService(db).create_condition(t.id, data)
        added = db.add.call_args[0][0]
        assert added.trigger_id == t.id
        assert added.expression["operator"] == "gt"
        assert result.logic == "and"

    @pytest.mark.asyncio
    async def test_create_raises_for_missing_trigger(self):
        db = make_db()
        res = MagicMock(); res.scalar_one_or_none.return_value = None
        db.execute.return_value = res
        with pytest.raises(WorkflowNotFoundError):
            await WorkflowService(db).create_condition(
                uuid4(), ConditionCreate(expression={"field": "x"})
            )

    @pytest.mark.asyncio
    async def test_update(self):
        db = make_db()
        c = condition_orm(uuid4())
        res = MagicMock(); res.scalar_one_or_none.return_value = c
        db.execute.return_value = res
        result = await WorkflowService(db).update_condition(
            c.id, ConditionUpdate(logic="or", priority=3)
        )
        assert c.logic == "or" and c.priority == 3
        assert result.logic == "or"

    @pytest.mark.asyncio
    async def test_update_missing_returns_none(self):
        db = make_db()
        res = MagicMock(); res.scalar_one_or_none.return_value = None
        db.execute.return_value = res
        assert await WorkflowService(db).update_condition(
            uuid4(), ConditionUpdate(logic="or")
        ) is None

    @pytest.mark.asyncio
    async def test_list_conditions(self):
        db = make_db()
        t = trigger_orm(uuid4())
        c1, c2 = condition_orm(t.id, id=uuid4()), condition_orm(t.id, id=uuid4())
        db.execute.side_effect = [scalar_result(t), scalars_result([c1, c2])]
        items = await WorkflowService(db).list_conditions(t.id)
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_list_conditions_missing_trigger_raises(self):
        db = make_db()
        db.execute.return_value = scalar_result(None)
        with pytest.raises(WorkflowNotFoundError):
            await WorkflowService(db).list_conditions(uuid4())

    @pytest.mark.asyncio
    async def test_delete_condition(self):
        db = make_db()
        c = condition_orm(uuid4())
        upd = MagicMock(); upd.rowcount = 1
        db.execute.side_effect = [scalar_result(c), upd]
        assert await WorkflowService(db).delete_condition(c.id) is True
        assert c.is_deleted is True
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_delete_condition_missing_returns_false(self):
        db = make_db()
        db.execute.return_value = scalar_result(None)
        assert await WorkflowService(db).delete_condition(uuid4()) is False


# ========== Action CRUD ==========

class TestActionCRUD:
    @pytest.mark.asyncio
    async def test_create(self):
        db = make_db()
        c = condition_orm(uuid4())
        res = MagicMock(); res.scalar_one_or_none.return_value = c
        db.execute.return_value = res
        result = await WorkflowService(db).create_action(
            c.id, ActionCreate(action_type="tag", params={"tag_ids": ["vip"]})
        )
        added = db.add.call_args[0][0]
        assert added.condition_id == c.id
        assert added.action_type == "tag"
        assert result.params == {"tag_ids": ["vip"]}

    @pytest.mark.asyncio
    async def test_delete(self):
        db = make_db()
        a = action_orm(uuid4())
        res = MagicMock(); res.scalar_one_or_none.return_value = a
        db.execute.return_value = res
        assert await WorkflowService(db).delete_action(a.id) is True
        assert a.is_deleted is True

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self):
        db = make_db()
        res = MagicMock(); res.scalar_one_or_none.return_value = None
        db.execute.return_value = res
        assert await WorkflowService(db).delete_action(uuid4()) is False

    @pytest.mark.asyncio
    async def test_list_actions(self):
        db = make_db()
        c = condition_orm(uuid4())
        a1, a2 = action_orm(c.id, id=uuid4()), action_orm(c.id, id=uuid4())
        db.execute.side_effect = [scalar_result(c), scalars_result([a1, a2])]
        items = await WorkflowService(db).list_actions(c.id)
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_list_actions_missing_condition_raises(self):
        db = make_db()
        db.execute.return_value = scalar_result(None)
        with pytest.raises(WorkflowNotFoundError):
            await WorkflowService(db).list_actions(uuid4())

    @pytest.mark.asyncio
    async def test_update_action(self):
        db = make_db()
        a = action_orm(uuid4())
        db.execute.return_value = scalar_result(a)
        result = await WorkflowService(db).update_action(
            a.id, ActionUpdate(name="renamed", params={"mode": "remove"}, priority=9)
        )
        assert a.name == "renamed"
        assert a.params == {"mode": "remove"}
        assert a.priority == 9
        assert result.name == "renamed"

    @pytest.mark.asyncio
    async def test_update_action_partial_only_name(self):
        db = make_db()
        a = action_orm(uuid4())
        db.execute.return_value = scalar_result(a)
        await WorkflowService(db).update_action(a.id, ActionUpdate(name="x"))
        assert a.params == {}  # untouched
        assert a.priority == 0

    @pytest.mark.asyncio
    async def test_update_action_missing_returns_none(self):
        db = make_db()
        db.execute.return_value = scalar_result(None)
        assert await WorkflowService(db).update_action(uuid4(), ActionUpdate()) is None


# ========== Detail view ==========

class TestDetail:
    @pytest.mark.asyncio
    async def test_full_tree(self):
        db = make_db()
        wf = workflow_orm()
        t1, t2 = trigger_orm(wf.id), trigger_orm(wf.id)
        c1 = condition_orm(t1.id)
        a1 = action_orm(c1.id)

        wf_res = scalar_result(wf)
        db.execute.side_effect = [wf_res, scalars_result([t1, t2]), scalars_result([c1]), scalars_result([a1])]

        detail = await WorkflowService(db).get_workflow_detail(wf.id)
        # build_workflow_detail's return shape (model vs dict) can shift with
        # the unified schemas module; normalize to dict and assert on content.
        payload = detail if isinstance(detail, dict) else detail.model_dump()
        assert len(payload["triggers"]) == 2
        first_trig = payload["triggers"][0]
        first_cond = first_trig["conditions"][0]
        assert first_cond["actions"][0]["action_type"] == "message"
        assert payload["triggers"][1]["conditions"] == []

    @pytest.mark.asyncio
    async def test_detail_missing_returns_none(self):
        db = make_db()
        res = MagicMock(); res.scalar_one_or_none.return_value = None
        db.execute.return_value = res
        assert await WorkflowService(db).get_workflow_detail(uuid4()) is None


# ========== Health ==========

def test_service_health():
    assert WorkflowService(MagicMock()).health()["service"] == "workflow-service"
