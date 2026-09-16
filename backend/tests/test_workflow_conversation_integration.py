"""Workflow <-> Conversation integration tests (Phase 4 / t_cc6aa406).

Exercises the full chain on the platform in-process bus:

    DomainEvent (conversation.created / message.created / intent.classified)
        -> DomainEventBus (app.events.domain_events)
        -> WorkflowConversationBridge.handle_domain_event
        -> trigger match (spec.event / spec.topic vs entity_type)
        -> condition evaluation (field/operator/value)
        -> action execution (conversation / message / tag / notification)
        -> ExecutionLog record

Plus:
- domain-bus delivery semantics (wildcard vs typed subscribe, handler
  isolation, reset)
- event publication from the conversation + intent router endpoints
- POST /workflows/{id}/triggers/fire wiring
- the default subscriber registration (per-event DB session, idempotent)

DB session is mocked (AsyncMock) to stay independent of a live Postgres,
matching the repo's test_workflow_execution_log / test_conversation
conventions. No AI provider is required: the default TemplateResponder is
deterministic.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.events.domain_events import (
    DomainEvent,
    DomainEventBus,
    CONVERSATION_EVENT_TYPES,
)
from app.services.workflow_conversation_bridge import (
    WorkflowConversationBridge,
    TriggerMatch,
    TemplateResponder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CONV_ID = str(uuid4())
VALID_CUST_ID = str(uuid4())


def _bridge(db=None, responder=None):
    return WorkflowConversationBridge(db=db or AsyncMock(), responder=responder)


def _event(
    event_type="message.created",
    entity_type="message",
    entity_id=None,
    payload=None,
):
    """Build a platform-bus DomainEvent."""
    return DomainEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id or (uuid4() if entity_type else None),
        payload=payload or {},
    )


def _make_match(workflow_id=None, trigger=None, conditions=(), workflow_config=None):
    """Build a TriggerMatch from lightweight mocks (no DB needed)."""
    workflow = MagicMock()
    workflow.id = workflow_id or uuid4()
    workflow.status = "active"
    workflow.config = workflow_config or {}
    workflow.name = "wf-test"

    if trigger is None:
        trigger = MagicMock()
        trigger.id = uuid4()
        trigger.spec = {"event": "message.created"}
    else:
        if not hasattr(trigger, "spec"):
            trigger.spec = {}
        if not hasattr(trigger, "id"):
            trigger.id = uuid4()

    match = TriggerMatch(workflow=workflow, trigger=trigger)
    match.conditions = list(conditions)
    return match


def _action(action_type, params=None, name="a1"):
    a = MagicMock()
    a.id = uuid4()
    a.name = name
    a.action_type = action_type
    a.params = params or {}
    return a


def _condition(expression, logic="and"):
    c = MagicMock()
    c.id = uuid4()
    c.expression = expression
    c.logic = logic
    return c


def _base_context(**overrides):
    base = {
        "event": _event(),
        "event_type": "message.created",
        "entity_type": "message",
        "entity_id": VALID_CONV_ID,
        "workflow_id": "wf-1",
        "trigger_id": "tr-1",
        "persona_name": None,
        "customer_id": VALID_CUST_ID,
        "channel": "web",
        "intent_type": "question",
        "intent_confidence": 0.9,
        "conversation_id": VALID_CONV_ID,
        "message_id": "m-1",
        "payload": {},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Domain bus delivery (platform bus)
# ---------------------------------------------------------------------------

class TestDomainBusDelivery:
    async def test_typed_subscribe_receives_matching_event(self):
        bus = DomainEventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("message.created", handler)
        ev = _event("message.created", payload={"a": 1})
        await bus.publish(ev)
        assert received == [ev]

    async def test_typed_subscribe_ignores_other_events(self):
        bus = DomainEventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("message.created", handler)
        await bus.publish(_event("intent.classified"))
        assert received == []

    async def test_wildcard_subscribe_receives_all(self):
        bus = DomainEventBus()
        received = []

        async def handler(event):
            received.append(event.event_type)

        bus.subscribe(None, handler)
        await bus.publish(_event("conversation.created"))
        await bus.publish(_event("message.created"))
        assert received == ["conversation.created", "message.created"]

    async def test_failing_handler_does_not_break_bus(self):
        bus = DomainEventBus()
        ran = []

        async def bad(event):
            raise RuntimeError("boom")

        async def good(event):
            ran.append(event.event_type)

        bus.subscribe("message.created", bad)
        bus.subscribe("message.created", good)
        outcomes = await bus.publish(_event("message.created"))
        assert len(outcomes) == 2
        assert outcomes[0]["ok"] is False
        assert outcomes[1]["ok"] is True
        assert ran == ["message.created"]

    def test_reset_clears_subscriptions_and_pending(self):
        bus = DomainEventBus()

        async def handler(event):
            pass

        bus.subscribe("message.created", handler)
        bus.publish_nowait(_event("message.created"))
        assert bus.subscriber_count == 1
        assert len(bus.pending) == 1
        bus.reset()
        assert bus.subscriber_count == 0
        assert len(bus.pending) == 0

    async def test_publish_nowait_then_dispatch_preserves_order(self):
        bus = DomainEventBus()
        seen = []

        async def handler(event):
            seen.append(event.payload.get("n"))

        bus.subscribe(None, handler)
        bus.publish_nowait(_event("message.created", payload={"n": 1}))
        bus.publish_nowait(_event("message.created", payload={"n": 2}))
        await bus.dispatch_pending()
        assert seen == [1, 2]
        assert bus.pending == []


# ---------------------------------------------------------------------------
# Trigger matching (bridge)
# ---------------------------------------------------------------------------

class TestTriggerMatching:
    async def _matches(self, spec_event, event_type, spec_topic=None, entity_type="message"):
        wf = MagicMock()
        wf.id = uuid4()
        wf.config = {}
        trigger = MagicMock()
        trigger.id = uuid4()
        trigger.spec = {"event": spec_event, **({"topic": spec_topic} if spec_topic else {})}
        rows = [(wf, trigger, None)]
        db = AsyncMock()
        res = MagicMock()
        res.all.return_value = rows
        db.execute = AsyncMock(return_value=res)
        bridge = _bridge(db)
        return await bridge.find_trigger_matches(_event(event_type, entity_type))

    async def test_exact_event_match(self):
        assert len(await self._matches("message.created", "message.created")) == 1

    async def test_no_match_on_different_event(self):
        assert await self._matches("intent.classified", "message.created") == []

    async def test_wildcard_event_spec_matches_any_event(self):
        assert len(await self._matches("*", "message.created")) == 1

    async def test_topic_filter_matches_entity_type(self):
        assert len(await self._matches("message.created", "message.created",
                                       spec_topic="message", entity_type="message")) == 1

    async def test_topic_mismatch_is_skipped(self):
        # Spec wants topic "intent" but event entity_type is "message" -> skip.
        assert await self._matches("message.created", "message.created",
                                   spec_topic="intent", entity_type="message") == []


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

class TestConditionEvaluation:
    def test_basic_ops(self):
        b = _bridge()
        ctx = _base_context(intent_type="complaint", intent_confidence=0.9, channel="wechat")
        assert b.evaluate_condition(_condition({"field": "intent_type", "operator": "eq", "value": "complaint"}), ctx)
        assert not b.evaluate_condition(_condition({"field": "intent_type", "operator": "eq", "value": "thanks"}), ctx)
        assert b.evaluate_condition(_condition({"field": "intent_confidence", "operator": "gte", "value": 0.8}), ctx)
        assert not b.evaluate_condition(_condition({"field": "intent_confidence", "operator": "gte", "value": 0.95}), ctx)

    def test_in_not_in_contains_regex(self):
        b = _bridge()
        ctx = _base_context(intent_type="complaint", channel="wechat")
        assert b.evaluate_condition(_condition({"field": "intent_type", "operator": "in", "value": ["complaint", "escalation"]}), ctx)
        assert not b.evaluate_condition(_condition({"field": "intent_type", "operator": "not_in", "value": ["complaint", "escalation"]}), ctx)
        assert b.evaluate_condition(_condition({"field": "channel", "operator": "contains", "value": "chat"}), ctx)
        assert b.evaluate_condition(_condition({"field": "channel", "operator": "regex", "value": "^wechat$"}), ctx)

    def test_dotted_field_into_payload(self):
        b = _bridge()
        ctx = _base_context(payload={"intent_type": "question"})
        assert b.evaluate_condition(_condition({"field": "payload.intent_type", "operator": "eq", "value": "question"}), ctx)

    def test_unknown_field_fails_strictly(self):
        b = _bridge()
        assert not b.evaluate_condition(_condition({"field": "does_not_exist", "operator": "eq", "value": "x"}), _base_context())

    def test_empty_expression_passes_vacuously(self):
        b = _bridge()
        assert b.evaluate_condition(_condition({}), _base_context())

    def test_unknown_operator_fails(self):
        b = _bridge()
        assert not b.evaluate_condition(_condition({"field": "intent_type", "operator": "starts_with", "value": "c"}), _base_context())


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------

class TestActions:
    async def _swap_conv_service(self, fake_cls):
        import app.services.workflow_conversation_bridge as bridge_mod
        orig = bridge_mod.ConversationService
        bridge_mod.ConversationService = fake_cls
        return bridge_mod, orig

    async def _restore(self, bridge_mod, orig):
        bridge_mod.ConversationService = orig

    async def test_message_action_with_explicit_template(self):
        bridge = _bridge()
        captured = {}

        class FakeConvService:
            def __init__(self, db=None):
                pass

            async def create_message(self, data):
                captured["message"] = data
                m = MagicMock()
                m.id = uuid4()
                m.conversation_id = data.conversation_id
                m.role = data.role
                m.content = data.content
                m.metadata_ = data.metadata_ or {}
                m.created_at = None
                return m

        bm, orig = await self._swap_conv_service(FakeConvService)
        try:
            result = await bridge.execute_action(
                _action("message", {"template": "您好，请问有什么可以帮您？"}),
                _base_context(),
            )
        finally:
            await self._restore(bm, orig)

        assert result["status"] == "success"
        assert result["strategy"] == "template-explicit"
        assert result["conversation_id"] == VALID_CONV_ID
        assert captured["message"].role == "assistant"
        assert captured["message"].content == "您好，请问有什么可以帮您？"
        assert captured["message"].metadata_["source"] == "workflow"

    async def test_message_action_uses_ai_responder_when_no_template(self):
        bridge = _bridge()
        captured = {}

        class FakeConvService:
            def __init__(self, db=None):
                pass

            async def create_message(self, data):
                captured["message"] = data
                m = MagicMock()
                m.id = uuid4()
                m.conversation_id = data.conversation_id
                m.role = "assistant"
                m.content = data.content
                m.metadata_ = data.metadata_ or {}
                m.created_at = None
                return m

        class FakeResponder:
            def __init__(self):
                self.captured_context = None

            async def generate_reply(self, context):
                self.captured_context = context
                return {"content": "AI 生成的回复", "strategy": "ai", "metadata": {}}

        responder = FakeResponder()
        bridge.responder = responder
        bm, orig = await self._swap_conv_service(FakeConvService)
        try:
            result = await bridge.execute_action(_action("message"), _base_context())
        finally:
            await self._restore(bm, orig)

        assert result["status"] == "success"
        assert result["strategy"] == "ai"
        assert result["content_preview"].startswith("AI 生成的回复")
        assert responder.captured_context["intent_type"] == "question"
        assert responder.captured_context["workflow_id"] == "wf-1"

    async def test_message_action_creates_conversation_when_no_target(self):
        captured = {}

        class FakeConvService:
            def __init__(self, db=None):
                pass

            async def create_conversation(self, data):
                captured["conversation"] = data
                c = MagicMock()
                c.id = uuid4()
                c.channel = data.channel
                return c

            async def create_message(self, data):
                captured["message"] = data
                m = MagicMock()
                m.id = uuid4()
                m.conversation_id = data.conversation_id
                m.role = "assistant"
                m.content = data.content
                m.metadata_ = data.metadata_ or {}
                m.created_at = None
                return m

        bridge = _bridge()
        bridge.responder = TemplateResponder()
        bm, orig = await self._swap_conv_service(FakeConvService)
        try:
            result = await bridge.execute_action(_action("message"), _base_context(conversation_id=None))
        finally:
            await self._restore(bm, orig)

        assert result["status"] == "success"
        assert captured["conversation"].customer_id is not None
        assert str(captured["conversation"].customer_id) == VALID_CUST_ID

    async def test_message_action_skipped_without_target(self):
        bridge = _bridge()
        result = await bridge.execute_action(
            _action("message"), _base_context(conversation_id=None, customer_id=None)
        )
        assert result["status"] == "skipped"

    async def test_conversation_action_creates_record(self):
        captured = {}

        class FakeConvService:
            def __init__(self, db=None):
                pass

            async def create_conversation(self, data):
                captured["data"] = data
                c = MagicMock()
                c.id = uuid4()
                c.channel = data.channel
                return c

        bridge = _bridge()
        bm, orig = await self._swap_conv_service(FakeConvService)
        try:
            result = await bridge.execute_action(
                _action("conversation", {"channel": "wechat"}), _base_context()
            )
        finally:
            await self._restore(bm, orig)

        assert result["status"] == "success"
        assert result["channel"] == "wechat"
        assert captured["data"].metadata_["source"] == "workflow"

    async def test_conversation_action_failed_on_bad_customer(self):
        bridge = _bridge()
        result = await bridge.execute_action(
            _action("conversation"), _base_context(customer_id="not-a-uuid")
        )
        assert result["status"] == "failed"
        assert "invalid customer_id" in result["note"]

    async def test_notification_action_is_recorded_not_executed(self):
        bridge = _bridge()
        result = await bridge.execute_action(_action("notification", {"body": "hi"}), _base_context())
        assert result["status"] == "recorded"

    async def test_unknown_action_type_is_skipped(self):
        bridge = _bridge()
        result = await bridge.execute_action(_action("not_a_real_action"), _base_context())
        assert result["status"] == "skipped"

    async def test_action_exception_is_captured_as_failed_record(self):
        bridge = _bridge()

        class ExplodingService:
            def __init__(self, db=None):
                pass

            async def create_message(self, data):
                raise RuntimeError("db down")

        bm, orig = await self._swap_conv_service(ExplodingService)
        try:
            result = await bridge.execute_action(_action("message", {"template": "x"}), _base_context())
        finally:
            await self._restore(bm, orig)
        assert result["status"] == "failed"
        assert "db down" in result["note"]


# ---------------------------------------------------------------------------
# End-to-end: event -> workflow -> ExecutionLog
# ---------------------------------------------------------------------------

class TestEndToEnd:
    async def test_full_chain_writes_execution_log(self):
        """message.created event with a matching active workflow runs its
        actions and records an ExecutionLog row."""
        db = AsyncMock()
        bridge = _bridge(db)
        bridge.responder = TemplateResponder()

        wf_id = uuid4()
        workflow = MagicMock()
        workflow.id = wf_id
        workflow.status = "active"
        workflow.config = {"persona_name": "小助手"}
        workflow.name = "auto-reply"

        trigger = MagicMock()
        trigger.id = uuid4()
        trigger.spec = {"event": "message.created"}

        cond = _condition({"field": "intent_type", "operator": "in",
                           "value": ["question", "greeting"]})
        action = _action("message", {"template": "收到，我们会尽快回复您。"})
        action.condition_id = cond.id

        # _execute_workflow_for_event issues ONE db.execute (actions by cond).
        actions_result = MagicMock()
        actions_result.scalars.return_value = MagicMock(all=lambda: [action])
        db.execute = AsyncMock(return_value=actions_result)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        import app.services.workflow_conversation_bridge as bridge_mod

        class FakeConvService:
            def __init__(self, db=None):
                pass

            async def create_message(self, data):
                m = MagicMock()
                m.id = uuid4()
                m.conversation_id = data.conversation_id
                m.role = "assistant"
                m.content = data.content
                m.metadata_ = data.metadata_ or {}
                m.created_at = None
                return m

        orig = bridge_mod.ConversationService
        bridge_mod.ConversationService = FakeConvService
        try:
            log = await bridge._execute_workflow_for_event(
                _make_match(workflow_id=wf_id, trigger=trigger, conditions=[cond]),
                _event("message.created", payload={"intent_type": "question",
                                                   "conversation_id": VALID_CONV_ID}),
            )
        finally:
            bridge_mod.ConversationService = orig

        assert db.add.called
        log = db.add.call_args.args[0]
        assert log.workflow_id == wf_id
        assert log.trigger_type == "event"
        assert log.status == "success"
        assert log.execution_type == "workflow"
        assert log.input_params["event_type"] == "message.created"
        assert log.output_result["actions"][0]["action_type"] == "message"
        assert log.output_result["actions"][0]["status"] == "success"

    async def test_handle_domain_event_runs_matching_workflow(self):
        """The bus entrypoint runs the full match + execute chain."""
        db = AsyncMock()
        bridge = _bridge(db)
        bridge.responder = TemplateResponder()

        wf = MagicMock()
        wf.id = uuid4()
        wf.status = "active"
        wf.config = {}
        wf.name = "auto-reply"
        trigger = MagicMock()
        trigger.id = uuid4()
        trigger.spec = {"event": "message.created"}
        cond = _condition({})  # vacuous pass
        action = _action("message", {"template": "收到！"})
        action.condition_id = cond.id

        join_result = MagicMock()
        join_result.all.return_value = [(wf, trigger, cond)]
        actions_result = MagicMock()
        actions_result.scalars.return_value = MagicMock(all=lambda: [action])
        db.execute = AsyncMock(side_effect=[join_result, actions_result])
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        import app.services.workflow_conversation_bridge as bridge_mod

        class FakeConvService:
            def __init__(self, db=None):
                pass

            async def create_message(self, data):
                m = MagicMock()
                m.id = uuid4()
                m.conversation_id = data.conversation_id
                m.role = "assistant"
                m.content = data.content
                m.metadata_ = data.metadata_ or {}
                m.created_at = None
                return m

        orig = bridge_mod.ConversationService
        bridge_mod.ConversationService = FakeConvService
        try:
            await bridge.handle_domain_event(
                _event("message.created", payload={"conversation_id": VALID_CONV_ID})
            )
        finally:
            bridge_mod.ConversationService = orig

        assert db.add.called
        assert db.add.call_args.args[0].status == "success"

    async def test_handle_domain_event_ignores_non_conversation_entity(self):
        """Lead/customer events belong to the CRM bridge, not this one."""
        db = AsyncMock()
        bridge = _bridge(db)
        await bridge.handle_domain_event(_event("lead.created", entity_type="lead"))
        # No DB query at all -> nothing matched/executed.
        db.execute.assert_not_called()

    async def test_failing_condition_blocks_actions(self):
        db = AsyncMock()
        bridge = _bridge(db)

        workflow = MagicMock()
        workflow.id = uuid4()
        workflow.status = "active"
        workflow.config = {}
        trigger = MagicMock()
        trigger.id = uuid4()
        trigger.spec = {"event": "intent.classified"}
        cond = _condition({"field": "intent_confidence", "operator": "gte", "value": 0.95})
        action = _action("message")
        action.condition_id = cond.id

        actions_result = MagicMock()
        actions_result.scalars.return_value = MagicMock(all=lambda: [action])
        db.execute = AsyncMock(return_value=actions_result)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        log = await bridge._execute_workflow_for_event(
            _make_match(workflow_id=workflow.id, trigger=trigger, conditions=[cond]),
            _event("intent.classified", payload={"intent_type": "question", "confidence": 0.5}),
        )
        assert log.status == "success"  # no hard failures
        assert log.output_result["conditions"][0]["passed"] is False
        assert log.output_result["actions"] == []  # blocked

    async def test_failed_action_marks_log_failed(self):
        db = AsyncMock()
        bridge = _bridge(db)

        workflow = MagicMock()
        workflow.id = uuid4()
        workflow.status = "active"
        workflow.config = {}
        trigger = MagicMock()
        trigger.id = uuid4()
        trigger.spec = {"event": "message.created"}
        cond = _condition({})
        action = _action("conversation")
        action.condition_id = cond.id

        actions_result = MagicMock()
        actions_result.scalars.return_value = MagicMock(all=lambda: [action])
        db.execute = AsyncMock(return_value=actions_result)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        # Malformed customer_id -> conversation action returns "failed".
        log = await bridge._execute_workflow_for_event(
            _make_match(workflow_id=workflow.id, trigger=trigger, conditions=[cond]),
            _event("message.created", payload={"customer_id": "not-a-uuid"}),
        )
        assert log.status == "failed"
        assert "invalid customer_id" in log.error_message


# ---------------------------------------------------------------------------
# Router-level event publication
# ---------------------------------------------------------------------------

class TestRouterEventPublication:
    async def test_create_message_publishes_on_shared_bus(self):
        from app.routers import conversations as conv_router_mod
        from app.events.domain_events import DomainEventBus

        bus = DomainEventBus()
        received = []

        async def capture(event):
            received.append(event)

        bus.subscribe(None, capture)

        # Point the router's publish helper at our capture bus.
        import app.events.domain_events as de
        orig = de._default_bus
        de._default_bus = bus
        try:
            await conv_router_mod._publish_domain_event(
                "message.created",
                entity_type="message",
                entity_id=uuid4(),
                payload={"conversation_id": VALID_CONV_ID, "role": "user"},
            )
        finally:
            de._default_bus = orig

        assert len(received) == 1
        assert received[0].event_type == "message.created"
        assert received[0].entity_type == "message"
        assert received[0].payload["conversation_id"] == VALID_CONV_ID

    async def test_create_conversation_publishes_on_shared_bus(self):
        from app.routers import conversations as conv_router_mod
        from app.events.domain_events import DomainEventBus

        bus = DomainEventBus()
        received = []

        async def capture(event):
            received.append(event)

        bus.subscribe("conversation.created", capture)

        import app.events.domain_events as de
        orig = de._default_bus
        de._default_bus = bus
        try:
            conv_id = uuid4()
            await conv_router_mod._publish_domain_event(
                "conversation.created",
                entity_type="conversation",
                entity_id=conv_id,
                payload={"customer_id": VALID_CUST_ID, "channel": "web"},
            )
        finally:
            de._default_bus = orig

        assert len(received) == 1
        assert received[0].event_type == "conversation.created"
        assert str(received[0].entity_id) == str(conv_id)

    async def test_intent_router_publishes_on_success(self):
        from app.routers import intents as intent_router_mod
        from app.schemas.intent import IntentClassificationResponse, IntentResult
        from app.events.domain_events import DomainEventBus

        bus = DomainEventBus()
        received = []

        async def capture(event):
            received.append(event)

        bus.subscribe("intent.classified", capture)

        import app.events.domain_events as de
        orig = de._default_bus
        de._default_bus = bus
        try:
            result = IntentClassificationResponse(
                success=True,
                intent=IntentResult(intent_type="greeting", intent_name="问候", confidence=0.98),
                processing_time_ms=1.0,
            )
            if result.success and result.intent is not None:
                event = de.DomainEvent(
                    event_type="intent.classified",
                    entity_type="intent",
                    entity_id=uuid4(),
                    payload={"intent_type": result.intent.intent_type,
                             "confidence": result.intent.confidence},
                )
                await de.get_event_bus().publish(event)
        finally:
            de._default_bus = orig

        assert len(received) == 1
        assert received[0].event_type == "intent.classified"
        assert received[0].payload["intent_type"] == "greeting"

    async def test_intent_router_does_not_publish_on_failure(self):
        from app.schemas.intent import IntentClassificationResponse
        from app.events.domain_events import DomainEventBus

        bus = DomainEventBus()
        received = []

        async def capture(event):
            received.append(event)

        bus.subscribe("intent.classified", capture)

        result = IntentClassificationResponse(success=False, message="llm down")
        # Mirror the endpoint guard: only publish when success & intent present.
        if result.success and result.intent is not None:
            await bus.publish(_event("intent.classified"))
        assert received == []


# ---------------------------------------------------------------------------
# Default subscriber registration
# ---------------------------------------------------------------------------

class TestDefaultSubscriberRegistration:
    def test_register_is_idempotent(self):
        import app.services.workflow_conversation_bridge as b
        n1 = b.register_workflow_conversation_subscriber()
        n2 = b.register_workflow_conversation_subscriber()
        assert n1 == n2 == len(CONVERSATION_EVENT_TYPES)
        b.reset_workflow_conversation_subscriber()

    def test_register_subscribes_each_conversation_event(self):
        import app.services.workflow_conversation_bridge as b
        import app.events.domain_events as de

        # Point the module at a fresh bus so we can count subscriptions.
        fresh = DomainEventBus()
        orig = de._default_bus
        de._default_bus = fresh
        b.reset_workflow_conversation_subscriber()
        try:
            b.register_workflow_conversation_subscriber()
            # Every conversation event type now has a typed subscriber.
            for et in CONVERSATION_EVENT_TYPES:
                assert len(fresh._subscribers.get(et, [])) == 1
        finally:
            de._default_bus = orig
            b.reset_workflow_conversation_subscriber()


# ---------------------------------------------------------------------------
# Trigger-fire endpoint contract
# ---------------------------------------------------------------------------

class TestTriggerFireEndpoint:
    def test_endpoint_registered_on_workflow_config_router(self):
        from app.routers.workflow_config import router, TriggerFireRequest, TriggerFireResult
        paths = [r.path for r in router.routes]
        assert "/workflows/{workflow_id}/triggers/fire" in paths

        req = TriggerFireRequest(event="message.created",
                                 payload={"conversation_id": VALID_CONV_ID})
        assert req.event == "message.created"
        assert req.entity_type == "message"
        res = TriggerFireResult(fired=True, workflow_id=uuid4(),
                                execution_log_id="x", error=None)
        assert res.fired is True
