"""Workflow-CRM integration tests (t_4f31af5e).

Two layers, matching the repo's conventions:

1. Unit tests with a mocked AsyncSession — no live DB required. Cover the
   event bus, pure condition operators, live-value resolution, trigger
   matching, per-condition execution, action routing through the CRM
   service layer, and the executor's observability record.
2. A real-Postgres integration test (skipped automatically when the test DB
   is unreachable) that drives the full trigger -> condition -> action ->
   ExecutionLog chain against the CRM service layer.
"""
from __future__ import annotations

import asyncio
import importlib.util
import socket
from types import SimpleNamespace
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

# Import the model package first so all mappers are registered (repo convention).
import app.db.models  # noqa: F401

from app.db.models.workflow import (
    Workflow,
    WorkflowTrigger,
    WorkflowCondition,
    WorkflowAction,
    ExecutionLog,
)
from app.events.domain_events import (
    DomainEvent,
    DomainEventBus,
    get_event_bus,
    EVENT_TYPES,
    CRM_EVENT_TYPES,
)
from app.services.workflow_crm import (
    WorkflowCrmExecutor,
    evaluate_expression,
    resolve_condition_value,
    register_workflow_crm_subscriber,
    reset_workflow_crm_subscriber,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_bus():
    """Each test starts from an isolated, empty bus + publisher, and every
    test ends with the real CRM tag service restored (unit tests may have
    swapped in no-ops via ``monkeypatch_crm_tag``)."""
    bus = get_event_bus()
    bus.reset()
    import app.services.crm_events as crm_events
    crm_events.reset_crm_publisher()
    yield
    bus.reset()
    crm_events.reset_crm_publisher()
    restore_crm_tag()


def _mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _event(
    event_type: str = "lead.status_changed",
    entity_type: str = "lead",
    entity_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> DomainEvent:
    return DomainEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=uuid4() if entity_id is None else entity_id,
        payload=payload or {},
    )


# ---------------------------------------------------------------------------
# 1. Domain event bus
# ---------------------------------------------------------------------------

class TestEventBus:
    def test_event_vocabulary_is_stable(self):
        assert "lead.status_changed" in EVENT_TYPES
        assert "lead.stage_changed" in EVENT_TYPES
        assert "lead.tags_changed" in EVENT_TYPES
        assert "customer.tag_changed" in EVENT_TYPES

    async def test_publish_reaches_type_subscriber(self):
        bus = DomainEventBus()
        seen: List[DomainEvent] = []

        def handler(event):
            seen.append(event)

        bus.subscribe("lead.status_changed", handler)
        ev = _event("lead.status_changed", payload={"old_status": "new"})
        outcomes = await bus.publish(ev)

        assert len(seen) == 1
        assert seen[0] is ev
        assert outcomes[0]["ok"] is True

    async def test_wildcard_subscriber_receives_every_event(self):
        bus = DomainEventBus()
        seen: List[str] = []
        bus.subscribe(None, lambda e: seen.append(e.event_type))
        bus.subscribe("lead.status_changed", lambda e: None)

        await bus.publish(_event("lead.status_changed"))
        await bus.publish(_event("customer.created"))

        assert seen == ["lead.status_changed", "customer.created"]

    async def test_handler_exception_is_caught_not_raised(self):
        bus = DomainEventBus()

        def bad(event):
            raise RuntimeError("boom")

        bus.subscribe("lead.status_changed", bad)
        # Must not raise even though the handler blows up.
        outcomes = await bus.publish(_event())
        assert outcomes[0]["ok"] is False
        assert "RuntimeError" in outcomes[0]["error"]

    async def test_publish_nowait_queues_then_dispatches(self):
        bus = DomainEventBus()
        seen: List[DomainEvent] = []
        bus.subscribe("lead.status_changed", lambda e: seen.append(e))

        ev1 = _event()
        ev2 = _event()
        bus.publish_nowait(ev1)
        bus.publish_nowait(ev2)
        assert bus.pending == [ev1, ev2]

        await bus.dispatch_pending()
        assert seen == [ev1, ev2]
        assert bus.pending == []

    def test_reset_clears_subscriptions_and_queue(self):
        bus = DomainEventBus()
        bus.subscribe("x", lambda e: None)
        bus.publish_nowait(_event())
        assert bus.subscriber_count == 1
        bus.reset()
        assert bus.subscriber_count == 0
        assert bus.pending == []


# ---------------------------------------------------------------------------
# 2. Pure condition-operator evaluation
# ---------------------------------------------------------------------------

class TestEvaluateExpression:
    @pytest.mark.parametrize(
        "actual,op,expected,want",
        [
            ("qualified", "eq", "qualified", True),
            ("new", "eq", "qualified", False),
            ("new", "neq", "qualified", True),
            (5, "gt", 3, True),
            (3, "gt", 3, False),
            (3, "gte", 3, True),
            (2, "lt", 3, True),
            (2, "lte", 2, True),
            ("a", "in", ["a", "b"], True),
            ("z", "in", ["a", "b"], False),
            ("z", "not_in", ["a", "b"], True),
            ("hello world", "contains", "world", True),
            ("abc123", "regex", r"^\d+$", False),
            ("12345", "regex", r"^\d+$", True),
            # missing value only satisfies explicit None-equality
            (None, "eq", None, True),
            (None, "eq", "x", False),
            (None, "gt", 0, False),
        ],
    )
    def test_operators(self, actual, op, expected, want):
        assert evaluate_expression(actual, op, expected) is want

    def test_unknown_operator_is_false(self):
        assert evaluate_expression(1, "nonsense", 1) is False


# ---------------------------------------------------------------------------
# 3. Live value resolution (event + entity re-read)
# ---------------------------------------------------------------------------

class TestResolveConditionValue:
    async def test_event_type_resolves(self):
        db = _mock_db()
        ev = _event("lead.status_changed", payload={"old_status": "new"})
        assert await resolve_condition_value(
            db, {"field": "event.type"}, ev
        ) == "lead.status_changed"

    async def test_event_payload_key_resolves(self):
        db = _mock_db()
        ev = _event(payload={"old_status": "new", "new_status": "contacted"})
        assert await resolve_condition_value(
            db, {"field": "event.new_status"}, ev
        ) == "contacted"

    async def test_event_entity_id_resolves(self):
        db = _mock_db()
        ev = _event(entity_id="11111111-1111-1111-1111-111111111111")
        assert str(
            await resolve_condition_value(db, {"field": "event.entity_id"}, ev)
        ) == "11111111-1111-1111-1111-111111111111"

    async def test_lead_field_re_reads_entity(self):
        """lead.* must re-read the Lead from the DB, not trust the payload."""
        db = _mock_db()
        lead = _make_lead(status="qualified", lifecycle_stage_code="高意向")

        # First execute() = the Lead SELECT.
        res = MagicMock()
        res.scalar_one_or_none.return_value = lead
        db.execute = AsyncMock(return_value=res)

        ev = _event(entity_type="lead")
        assert await resolve_condition_value(
            db, {"field": "lead.status"}, ev
        ) == "qualified"

    async def test_lead_tags_resolves_to_names(self):
        db = _mock_db()
        from app.db.models.tag import Tag
        tag = Tag(name="VIP")
        tag.id = uuid4()
        lead = _make_lead(tags=[tag])
        res = MagicMock()
        res.scalar_one_or_none.return_value = lead
        db.execute = AsyncMock(return_value=res)

        ev = _event(entity_type="lead")
        assert await resolve_condition_value(
            db, {"field": "lead.tags"}, ev
        ) == ["VIP"]

    async def test_unknown_namespace_returns_none(self):
        db = _mock_db()
        ev = _event()
        assert await resolve_condition_value(
            db, {"field": "bogus.field"}, ev
        ) is None

    async def test_missing_lead_returns_none(self):
        """If the referenced lead no longer exists, field resolves to None."""
        db = _mock_db()
        res = MagicMock()
        res.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=res)

        ev = _event(entity_type="lead")
        assert await resolve_condition_value(
            db, {"field": "lead.status"}, ev
        ) is None


def _make_lead(
    status: str = "new",
    lifecycle_stage_code: str = "陌生",
    tags: Optional[List] = None,
) -> WorkflowCondition:
    """Build a lightweight Lead-shaped object for resolution tests.

    Uses the real Lead model so attribute names match, but no DB round trip.
    """
    from app.db.models.lead import Lead

    lead = Lead()
    lead.id = uuid4()
    lead.status = status
    lead.lifecycle_stage_code = lifecycle_stage_code
    lead.tags = tags or []
    lead.customer_id = uuid4()
    return lead


# ---------------------------------------------------------------------------
# 4. Trigger matching + per-condition execution
# ---------------------------------------------------------------------------

def _make_workflow(
    *,
    wf_status: str = "active",
    triggers=None,
) -> Workflow:
    wf = Workflow()
    wf.id = uuid4()
    wf.name = "lead-followup"
    wf.status = wf_status
    wf.workflow_type = "auto"
    wf.triggers = triggers or []
    wf.is_deleted = False
    return wf


def _make_trigger(event=None, trigger_type="event", enabled=True, conditions=None):
    t = WorkflowTrigger()
    t.id = uuid4()
    t.trigger_type = trigger_type
    t.spec = {"event": event} if event else {}
    t.enabled = enabled
    t.conditions = conditions or []
    t.is_deleted = False
    return t


def _make_condition(expression, logic="and", priority=0, actions=None):
    c = WorkflowCondition()
    c.id = uuid4()
    c.expression = expression
    c.logic = logic
    c.priority = priority
    c.actions = actions or []
    c.is_deleted = False
    return c


def _make_action(action_type="tag", params=None, priority=0):
    a = WorkflowAction()
    a.id = uuid4()
    a.action_type = action_type
    a.params = params or {}
    a.priority = priority
    a.is_deleted = False
    return a


class TestTriggerMatching:
    def test_event_trigger_matches_configured_event(self):
        wf = _make_workflow(triggers=[
            _make_trigger(event="lead.status_changed", conditions=[]),
            _make_trigger(event="customer.tag_changed", conditions=[]),
        ])
        ev = _event("lead.status_changed")
        matched = WorkflowCrmExecutor(_mock_db())._matching_triggers(wf, ev, force=False)
        assert len(matched) == 1
        assert matched[0].spec["event"] == "lead.status_changed"

    def test_disabled_trigger_is_excluded(self):
        wf = _make_workflow(triggers=[_make_trigger(
            event="lead.status_changed", enabled=False, conditions=[]
        )])
        ev = _event("lead.status_changed")
        assert WorkflowCrmExecutor(_mock_db())._matching_triggers(wf, ev, force=False) == []

    def test_scheduled_trigger_does_not_match_events(self):
        wf = _make_workflow(triggers=[_make_trigger(
            trigger_type="scheduled", enabled=True, conditions=[]
        )])
        ev = _event("lead.status_changed")
        assert WorkflowCrmExecutor(_mock_db())._matching_triggers(wf, ev, force=False) == []

    def test_wildcard_event_spec_matches_any_event(self):
        wf = _make_workflow(triggers=[_make_trigger(
            event="*", conditions=[]
        )])
        ev = _event("customer.created")
        assert len(WorkflowCrmExecutor(_mock_db())._matching_triggers(wf, ev, force=False)) == 1

    def test_force_matches_event_or_manual_triggers(self):
        wf = _make_workflow(triggers=[
            _make_trigger(event="lead.status_changed", conditions=[]),
            _make_trigger(trigger_type="manual", conditions=[]),
            _make_trigger(trigger_type="scheduled", conditions=[]),
        ])
        ev = _event()
        matched = WorkflowCrmExecutor(_mock_db())._matching_triggers(wf, ev, force=True)
        # manual + event, NOT scheduled
        assert {t.trigger_type for t in matched} == {"event", "manual"}


class TestConditionExecution:
    async def test_actions_run_only_when_condition_passes(self):
        db = _mock_db()
        passed_cond = _make_condition(
            {"field": "lead.status", "operator": "eq", "value": "qualified"},
            actions=[_make_action("tag", {"target": "lead"})],
        )
        failed_cond = _make_condition(
            {"field": "lead.status", "operator": "eq", "value": "converted"},
            actions=[_make_action("tag", {"target": "lead"})],
        )
        trigger = _make_trigger(event="lead.status_changed", conditions=[passed_cond, failed_cond])
        wf = _make_workflow(triggers=[trigger])

        # The lead re-read returns status="qualified".
        lead = _make_lead(status="qualified")
        res = MagicMock()
        res.scalar_one_or_none.return_value = lead
        db.execute = AsyncMock(return_value=res)

        # Stub the CRM tag service so no DB mutation is attempted.
        monkeypatch_crm_tag()
        executor = WorkflowCrmExecutor(db)
        outcome = await executor._run_trigger(wf, trigger, _event("lead.status_changed"))

        assert outcome["status"] == "success"
        # exactly one action executed (the passing condition's)
        assert len(outcome["actions"]) == 1
        # condition entries reflect both, only the first passed
        assert [e["passed"] for e in outcome["conditions"]] == [True, False]

    async def test_skipped_when_conditions_present_but_none_pass(self):
        db = _mock_db()
        cond = _make_condition(
            {"field": "lead.status", "operator": "eq", "value": "converted"},
            actions=[_make_action("tag", {"target": "lead"})],
        )
        trigger = _make_trigger(event="lead.status_changed", conditions=[cond])
        wf = _make_workflow(triggers=[trigger])

        lead = _make_lead(status="new")
        res = MagicMock()
        res.scalar_one_or_none.return_value = lead
        db.execute = AsyncMock(return_value=res)
        monkeypatch_crm_tag()

        executor = WorkflowCrmExecutor(db)
        outcome = await executor._run_trigger(wf, trigger, _event("lead.status_changed"))
        assert outcome["status"] == "skipped"
        assert outcome["actions"] == []

    async def test_no_conditions_means_actions_run_unconditionally(self):
        db = _mock_db()
        action = _make_action("tag", {"target": "lead"})
        cond = _make_condition({}, actions=[action])
        # empty expression -> evaluate_expression(None, eq, None) -> True
        trigger = _make_trigger(event="lead.status_changed", conditions=[cond])
        wf = _make_workflow(triggers=[trigger])

        res = MagicMock()
        res.scalar_one_or_none.return_value = _make_lead()
        db.execute = AsyncMock(return_value=res)
        monkeypatch_crm_tag()

        executor = WorkflowCrmExecutor(db)
        outcome = await executor._run_trigger(wf, trigger, _event())
        assert outcome["status"] == "success"
        assert len(outcome["actions"]) == 1

    async def test_failed_action_marks_trigger_failed(self):
        db = _mock_db()
        cond = _make_condition({}, actions=[_make_action("status_change", {"new_status": "nonexistent"})])
        trigger = _make_trigger(event="lead.status_changed", conditions=[cond])
        wf = _make_workflow(triggers=[trigger])

        res = MagicMock()
        res.scalar_one_or_none.return_value = _make_lead(status="new")
        db.execute = AsyncMock(return_value=res)
        monkeypatch_crm_tag()
        # Make update_lead raise ValueError to simulate an invalid transition.
        import app.services.workflow_crm as wcrm
        orig = wcrm.update_lead
        wcrm.update_lead = _raise_valueerror

        try:
            executor = WorkflowCrmExecutor(db)
            outcome = await executor._run_trigger(wf, trigger, _event())
        finally:
            wcrm.update_lead = orig

        assert outcome["status"] == "failed"
        assert outcome["actions"][0]["status"] == "failed"


def monkeypatch_crm_tag():
    """Neutralize the tag service so unit tests do not touch the DB.

    Remembers the originals on first call and swaps in no-ops. Pair with
    ``restore_crm_tag`` (run in the autouse fixture) so the real service
    is back for later, real-DB tests.
    """
    import app.services.workflow_crm as wcrm

    global _ORIG_CRM_TAG
    if not _ORIG_CRM_TAG:
        _ORIG_CRM_TAG = {
            "add_lead": wcrm.add_tags_to_lead,
            "remove_lead": wcrm.remove_tag_from_lead,
            "add_customer": wcrm.add_tags_to_customer,
            "remove_customer": wcrm.remove_tag_from_customer,
        }

    async def _noop_add_lead(db, lead_id, tag_ids):
        return {"inserted": 0, "already_existed": len(tag_ids)}

    wcrm.add_tags_to_lead = _noop_add_lead
    wcrm.remove_tag_from_lead = lambda *a, **k: False


_ORIG_CRM_TAG: dict = {}


def restore_crm_tag():
    """Put the real CRM tag service back after unit tests patched it."""
    import app.services.workflow_crm as wcrm

    global _ORIG_CRM_TAG
    if _ORIG_CRM_TAG:
        wcrm.add_tags_to_lead = _ORIG_CRM_TAG["add_lead"]
        wcrm.remove_tag_from_lead = _ORIG_CRM_TAG["remove_lead"]
        wcrm.add_tags_to_customer = _ORIG_CRM_TAG["add_customer"]
        wcrm.remove_tag_from_customer = _ORIG_CRM_TAG["remove_customer"]
        _ORIG_CRM_TAG = {}


def _raise_valueerror(db, lead_id, updates):
    raise ValueError("invalid status transition")


# ---------------------------------------------------------------------------
# 5. Action routing (custom sub-action + unsupported)
# ---------------------------------------------------------------------------

class TestActionRouting:
    async def test_custom_routes_to_sub_action(self):
        db = _mock_db()
        # status_change sub-action via the custom wrapper
        res = MagicMock()
        res.scalar_one_or_none.return_value = _make_lead(status="new")
        db.execute = AsyncMock(return_value=res)
        monkeypatch_crm_tag()

        import app.services.workflow_crm as wcrm
        orig = wcrm.update_lead
        captured = {}

        async def _capture(db_, lead_id, updates):
            captured["updates"] = updates
            return {"id": str(lead_id), "status": updates.get("status")}

        wcrm.update_lead = _capture
        try:
            executor = WorkflowCrmExecutor(db)
            action = _make_action("custom", {"action": "update_lead", "status": "contacted"})
            r = await executor._execute_action(_make_workflow(), action, _event())
        finally:
            wcrm.update_lead = orig

        assert r["status"] == "success"
        assert captured["updates"]["status"] == "contacted"

    async def test_unsupported_crm_action_type_is_flagged(self):
        db = _mock_db()
        executor = WorkflowCrmExecutor(db)
        action = _make_action("message", {"text": "hi"})
        r = await executor._execute_action(_make_workflow(), action, _event())
        assert r["status"] == "unsupported"

    async def test_unknown_action_type_is_flagged(self):
        executor = WorkflowCrmExecutor(_mock_db())
        action = _make_action("teleport", {})
        r = await executor._execute_action(_make_workflow(), action, _event())
        assert r["status"] == "unsupported"


# ---------------------------------------------------------------------------
# 5b. create_lead target resolution (P2: event.entity_id fallback)
# ---------------------------------------------------------------------------

def monkeypatch_crm_create_lead():
    """Capture create_lead calls; remember + restore the real service.

    Pairs with ``restore_crm_create_lead`` — call it in a ``finally`` block
    (the autouse fixture only restores the tag service).
    """
    import app.services.workflow_crm as wcrm

    global _ORIG_CRM_CREATE_LEAD
    if not _ORIG_CRM_CREATE_LEAD:
        _ORIG_CRM_CREATE_LEAD = {"create_lead": wcrm.create_lead}

    captured: dict = {}

    async def _capture(db, lead_data):
        captured["lead_data"] = lead_data
        return {"id": "00000000-0000-0000-0000-000000000001"}

    wcrm.create_lead = _capture
    return captured


def restore_crm_create_lead():
    import app.services.workflow_crm as wcrm

    global _ORIG_CRM_CREATE_LEAD
    if _ORIG_CRM_CREATE_LEAD:
        wcrm.create_lead = _ORIG_CRM_CREATE_LEAD["create_lead"]
        _ORIG_CRM_CREATE_LEAD = {}


_ORIG_CRM_CREATE_LEAD: dict = {}


class TestCreateLeadTargetResolution:
    async def test_customer_event_falls_back_to_event_entity_id(self):
        """customer.created + create_lead with no customer_id param ->
        the lead is created FOR the triggering customer (P2 fix)."""
        cust = str(uuid4())
        captured = monkeypatch_crm_create_lead()
        try:
            executor = WorkflowCrmExecutor(_mock_db())
            action = _make_action("create_lead", {})
            ev = _event("customer.created", "customer", entity_id=cust)
            r = await executor._execute_action(_make_workflow(), action, ev)
        finally:
            restore_crm_create_lead()

        assert r["status"] == "success"
        assert captured["lead_data"]["customer_id"] == UUID(cust)
        # still carries the workflow lineage
        assert captured["lead_data"]["source_type"] == "workflow"

    async def test_customer_tag_changed_event_also_falls_back(self):
        cust = str(uuid4())
        captured = monkeypatch_crm_create_lead()
        try:
            executor = WorkflowCrmExecutor(_mock_db())
            action = _make_action("custom", {"action": "create_lead"})
            ev = _event(
                "customer.tag_changed", "customer", entity_id=cust,
                payload={"tag_ids": [str(uuid4())]},
            )
            r = await executor._execute_action(_make_workflow(), action, ev)
        finally:
            restore_crm_create_lead()

        assert r["status"] == "success"
        assert captured["lead_data"]["customer_id"] == UUID(cust)

    async def test_explicit_params_customer_id_wins_over_event_entity(self):
        """Override behavior is preserved: an explicit customer_id param
        beats the event's own entity."""
        cust_from_event = str(uuid4())
        cust_from_params = str(uuid4())
        captured = monkeypatch_crm_create_lead()
        try:
            executor = WorkflowCrmExecutor(_mock_db())
            action = _make_action("create_lead", {"customer_id": cust_from_params})
            ev = _event("customer.created", "customer", entity_id=cust_from_event)
            r = await executor._execute_action(_make_workflow(), action, ev)
        finally:
            restore_crm_create_lead()

        assert r["status"] == "success"
        assert captured["lead_data"]["customer_id"] == UUID(cust_from_params)

    async def test_payload_customer_id_wins_over_event_entity(self):
        cust_from_event = str(uuid4())
        cust_from_payload = str(uuid4())
        captured = monkeypatch_crm_create_lead()
        try:
            executor = WorkflowCrmExecutor(_mock_db())
            action = _make_action("create_lead", {})
            ev = _event(
                "customer.created", "customer", entity_id=cust_from_event,
                payload={"customer_id": cust_from_payload},
            )
            r = await executor._execute_action(_make_workflow(), action, ev)
        finally:
            restore_crm_create_lead()

        assert r["status"] == "success"
        assert captured["lead_data"]["customer_id"] == UUID(cust_from_payload)

    async def test_non_customer_event_does_not_invent_a_customer(self):
        """A lead-typed event has no customer to fall back to — the lead
        stays customer-less (documented behavior, not an orphan surprise)."""
        lead_id = str(uuid4())
        captured = monkeypatch_crm_create_lead()
        try:
            executor = WorkflowCrmExecutor(_mock_db())
            action = _make_action("create_lead", {})
            ev = _event("lead.status_changed", "lead", entity_id=lead_id)
            r = await executor._execute_action(_make_workflow(), action, ev)
        finally:
            restore_crm_create_lead()

        assert r["status"] == "success"
        assert "customer_id" not in captured["lead_data"]



# ---------------------------------------------------------------------------
# 6. Subscriber wiring
# ---------------------------------------------------------------------------

class TestSubscriberWiring:
    def test_register_is_idempotent(self):
        reset_workflow_crm_subscriber()
        first = register_workflow_crm_subscriber()
        second = register_workflow_crm_subscriber()
        # The CRM executor subscribes to CRM events only (conversation events
        # are owned by the conversation bridge, t_cc6aa406).
        assert first == second == len(CRM_EVENT_TYPES)
        assert get_event_bus().subscriber_count == len(CRM_EVENT_TYPES)
        reset_workflow_crm_subscriber()


# ---------------------------------------------------------------------------
# 7. Real-Postgres integration (skipped when the test DB is unreachable)
# ---------------------------------------------------------------------------

def _pg_available() -> bool:
    if importlib.util.find_spec("asyncpg") is None:
        return False
    try:
        import asyncpg
        asyncio.get_event_loop_policy()

        async def _probe():
            conn = await asyncpg.connect(
                "postgresql://postgres:postgres@localhost:5432/ai_agent_platform_test",
                timeout=3,
            )
            await conn.close()
            return True

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_probe())
        finally:
            loop.close()
    except Exception:
        return False


pytestmark_int = pytest.mark.skipif(
    not _pg_available(), reason="Postgres test DB unreachable"
)


@pytestmark_int
class TestRealIntegration:
    """Drive the full trigger->condition->action->ExecutionLog chain on the
    real test DB through the CRM service layer."""

    @pytest.fixture
    async def db(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from app.db.models import Base

        engine = create_async_engine(
            "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"
        )
        # Ensure the workflow config + execution_log tables exist.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            yield session
        await engine.dispose()

    async def test_status_change_triggers_tag_action(self, db):
        from app.crm.services.lead import create_lead, update_lead
        from app.crm.services.tag import create_tag, add_tags_to_lead
        from app.db.models.workflow import ExecutionLog

        # 1. Seed a tag + a lead.
        tag = await create_tag(db, {"name": f"vip-{uuid4().hex[:6]}", "color": "#000"})
        lead = await create_lead(
            db,
            {"source_type": "manual", "status": "new", "lifecycle_stage_code": "陌生"},
        )
        lead_id, tag_id, lead_uuid = lead["id"], tag["id"], lead["id"]

        # 2. Build an active workflow: event trigger on lead.status_changed,
        #    condition lead.status eq 'contacted', action = add the tag.
        wf = Workflow(
            name="tag-on-contacted",
            workflow_type="auto",
            status="active",
            config={},
            execution_policy={},
        )
        db.add(wf)
        await db.commit()
        await db.refresh(wf)

        trigger = WorkflowTrigger(
            workflow_id=wf.id,
            trigger_type="event",
            spec={"event": "lead.status_changed"},
            enabled=True,
        )
        db.add(trigger)
        await db.commit()
        await db.refresh(trigger)

        condition = WorkflowCondition(
            trigger_id=trigger.id,
            expression={"field": "lead.status", "operator": "eq", "value": "contacted"},
            logic="and",
        )
        db.add(condition)
        await db.commit()
        await db.refresh(condition)

        action = WorkflowAction(
            condition_id=condition.id,
            action_type="tag",
            params={"target": "lead", "entity_id": lead_uuid, "tag_ids": [tag_id], "operation": "add"},
        )
        db.add(action)
        await db.commit()

        # 3. Mutate the lead through the real CRM service (fires the hook).
        await update_lead(db, lead_uuid, {"status": "contacted", "operator": "qa"})

        # 4. Run the executor against the synthetic event.
        executor = WorkflowCrmExecutor(db)
        event = _event(
            "lead.status_changed",
            "lead",
            entity_id=lead_uuid,
            payload={"old_status": "new", "new_status": "contacted"},
        )
        result = await executor.run_event(event)

        assert result["status"] == "success"
        assert result["executed"] >= 1

        # 5. The tag was actually applied through the CRM service.
        from sqlalchemy import select
        from app.db.models.tag import tag_lead
        row = await db.execute(
            select(tag_lead).where(
                tag_lead.c.tag_id == tag_id, tag_lead.c.lead_id == lead_uuid
            )
        )
        assert row.scalar_one_or_none() is not None

        # 6. An ExecutionLog was written for the run.
        logs = (
            await db.execute(
                select(ExecutionLog).where(ExecutionLog.workflow_id == wf.id)
            )
        ).scalars().all()
        assert logs and logs[0].status == "success"
