"""CRM + Conversation integration tests (Phase 3 / t_crm_007).

Covers the five acceptance criteria:

1. 高意向对话可自动创建 Lead      -> ConversationLeadBridge on intent.classified
2. Lead 来源正确记录为 Conversation  -> source_type="conversation",
                                        source_id=<conversation_id>
3. 不为同一客户重复创建 Lead       -> customer-level dedup in
                                        create_lead_from_conversation +
                                        check_duplicate_lead_for_customer
4. 手动触发接口可用                 -> POST /crm/leads/from-conversation
                                        (+ ?dedup_customer= opt-in)
5. 集成逻辑符合架构分离            -> bridge is a SEPARATE bus subscriber,
                                        delegates persistence to the CRM
                                        lead service, never raises bus-safely

DB is mocked (AsyncMock) to stay independent of a live Postgres, matching
the repo's test_workflow_conversation_integration / test_lead conventions.
The pure trigger rule (evaluate_intent_event) has no DB dependency.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime

from app.events.domain_events import DomainEvent, get_event_bus
from app.crm.services.conversation_lead_bridge import (
    ConversationLeadBridge,
    DEFAULT_HIGH_VALUE_INTENTS,
    DEFAULT_CONFIDENCE_FLOOR,
    register_conversation_lead_subscriber,
    reset_conversation_lead_subscriber,
)
from app.db.models.lead import Lead


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def bridge(mock_db):
    return ConversationLeadBridge(mock_db)


def _intent_event(payload, entity_type="intent", entity_id=None):
    return DomainEvent(
        event_type="intent.classified",
        entity_type=entity_type,
        entity_id=entity_id or uuid4(),
        payload=payload,
    )


# ---------------------------------------------------------------------------
# 1. The pure trigger rule (architecture separation: no DB, no vendor)
# ---------------------------------------------------------------------------

class TestTriggerRule:
    def test_high_value_intent_above_floor_creates(self):
        b = ConversationLeadBridge(db=None)
        d = b.evaluate_intent_event(
            {"conversation_id": "abc", "intent_type": "command", "confidence": 0.9}
        )
        assert d.should_create is True
        assert d.intent_type == "command"
        assert d.conversation_id == "abc"

    def test_low_intent_type_does_not_create(self):
        b = ConversationLeadBridge(db=None)
        d = b.evaluate_intent_event(
            {"conversation_id": "abc", "intent_type": "greeting", "confidence": 0.9}
        )
        assert d.should_create is False
        assert "not in high-value set" in d.reason

    def test_confidence_below_floor_does_not_create(self):
        b = ConversationLeadBridge(db=None)
        d = b.evaluate_intent_event(
            {"conversation_id": "abc", "intent_type": "callback_request", "confidence": 0.5}
        )
        assert d.should_create is False

    def test_missing_conversation_id_does_not_create(self):
        b = ConversationLeadBridge(db=None)
        d = b.evaluate_intent_event({"intent_type": "command", "confidence": 0.9})
        assert d.should_create is False
        assert "no conversation_id" in d.reason

    def test_missing_confidence_treated_as_zero(self):
        b = ConversationLeadBridge(db=None)
        d = b.evaluate_intent_event(
            {"conversation_id": "abc", "intent_type": "escalation"}
        )
        assert d.should_create is False

    def test_custom_config_overrides_defaults(self):
        b = ConversationLeadBridge(
            db=None,
            high_value_intents=frozenset({"question"}),
            confidence_floor=0.3,
        )
        d = b.evaluate_intent_event(
            {"conversation_id": "abc", "intent_type": "question", "confidence": 0.4}
        )
        assert d.should_create is True

    def test_defaults_are_consistent_with_intent_service(self):
        # The confidence floor matches IntentService's own 0.7 threshold,
        # so the bridge only acts on classifications the classifier trusts.
        assert DEFAULT_CONFIDENCE_FLOOR == 0.7
        for t in DEFAULT_HIGH_VALUE_INTENTS:
            assert t in {"command", "callback_request", "escalation", "complaint"}


# ---------------------------------------------------------------------------
# 2. Bus handler: non-matching events are no-ops (never touch the DB)
# ---------------------------------------------------------------------------

class TestHandlerNoOpPaths:
    async def test_non_intent_event_ignored(self, bridge, mock_db):
        ev = DomainEvent("conversation.created", "conversation", uuid4(), {})
        out = await bridge.handle_domain_event(ev)
        assert out is None
        mock_db.execute.assert_not_called()

    async def test_low_intent_event_does_not_query_db(self, bridge, mock_db):
        ev = _intent_event({"conversation_id": "x", "intent_type": "greeting", "confidence": 0.9})
        out = await bridge.handle_domain_event(ev)
        assert out is None
        mock_db.execute.assert_not_called()

    async def test_bad_conversation_id_is_skipped_not_raised(self, bridge, mock_db):
        ev = _intent_event({"conversation_id": "not-a-uuid", "intent_type": "command", "confidence": 0.9})
        out = await bridge.handle_domain_event(ev)
        assert out is None
        mock_db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Auto path delegates to the CRM lead service with customer-level dedup
# ---------------------------------------------------------------------------

class TestHandlerDelegation:
    async def test_high_intent_creates_lead_via_service(self, bridge, mock_db):
        conv_id = uuid4()
        created = {
            "id": str(uuid4()),
            "source_type": "conversation",
            "source_id": str(conv_id),
            "customer_id": str(uuid4()),
            "status": "new",
        }
        with patch(
            "app.crm.services.lead.create_lead_from_conversation",
            new=AsyncMock(return_value=created),
        ) as mock_create:
            ev = _intent_event(
                {"conversation_id": str(conv_id), "intent_type": "command", "confidence": 0.9}
            )
            out = await bridge.handle_domain_event(ev)

        assert out == created
        mock_create.assert_awaited_once()
        args, kwargs = mock_create.call_args
        # customer-level dedup must be ON for the auto path
        assert kwargs.get("allow_customer_duplicate") is False
        assert args[1] == conv_id

    async def test_service_exception_is_swallowed(self, bridge, mock_db):
        conv_id = uuid4()
        with patch(
            "app.crm.services.lead.create_lead_from_conversation",
            new=AsyncMock(side_effect=Exception("db down")),
        ):
            ev = _intent_event(
                {"conversation_id": str(conv_id), "intent_type": "command", "confidence": 0.9}
            )
            out = await bridge.handle_domain_event(ev)  # must NOT raise
        assert out is None


# ---------------------------------------------------------------------------
# 4. Customer-level dedup in the shared service (single source of truth)
# ---------------------------------------------------------------------------

class TestCustomerLevelDedup:
    @staticmethod
    def _conv_result(conversation):
        r = MagicMock()
        r.scalar_one_or_none.return_value = conversation
        return r

    @staticmethod
    def _none_result():
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    @staticmethod
    def _scalars_result(rows):
        r = MagicMock()
        r.scalars.return_value.first.return_value = rows[0] if rows else None
        return r

    @staticmethod
    def _get_result(lead_obj):
        """get_lead's underlying execute returns an ORM Lead object; get_lead
        itself builds the response dict. Mirror the repo's mock convention."""
        r = MagicMock()
        r.scalar_one_or_none.return_value = lead_obj
        return r

    async def test_same_customer_other_conversation_reuses_existing(
        self, mock_db
    ):
        from app.crm.services.lead import create_lead_from_conversation

        conv_id = uuid4()
        cust_id = uuid4()
        conv = MagicMock()
        conv.id = conv_id
        conv.customer_id = cust_id
        conv.metadata_ = {"intent_score": 80}
        conv.sentiment = "positive"
        conv.subject = "第二次咨询"

        existing_lead = Lead(
            id=uuid4(),
            customer_id=cust_id,
            lifecycle_stage_code="高意向",
            intent_score=80,
            source_type="conversation",
            source_id=str(uuid4()),  # a DIFFERENT conversation
            status="new",
            is_deleted=False,
        )
        existing_lead.tags = []
        existing_lead.lifecycle_logs = []

        # call sequence: (1) load conversation (2) per-conversation dedup -> None
        # (3) customer-level dedup -> existing lead (4) get_lead(existing)
        # get_lead builds its response dict from the ORM object, so the final
        # execute must return the ORM Lead (with .tags/.lifecycle_logs/.created_at).
        mock_db.execute.side_effect = [
            self._conv_result(conv),
            self._none_result(),
            self._scalars_result([existing_lead]),
            self._get_result(existing_lead),
        ]

        lead = await create_lead_from_conversation(
            mock_db, conv_id, allow_customer_duplicate=False
        )
        # Reused the customer's existing lead instead of creating a new one
        assert lead["id"] == str(existing_lead.id)
        assert lead["source_id"] == existing_lead.source_id
        # No new Lead row was added (dedup short-circuited before creation)
        assert len(mock_db.add.call_args_list) == 0

    async def test_customer_dedup_disabled_allows_second_lead(self, mock_db):
        from app.crm.services.lead import create_lead_from_conversation

        conv_id = uuid4()
        cust_id = uuid4()
        conv = MagicMock()
        conv.id = conv_id
        conv.customer_id = cust_id
        conv.metadata_ = {"intent_score": 80}
        conv.sentiment = "positive"
        conv.subject = "手动触发"

        new_lead = Lead(
            id=uuid4(),
            customer_id=cust_id,
            lifecycle_stage_code="高意向",
            intent_score=80,
            source_type="conversation",
            source_id=str(conv_id),
            status="new",
            is_deleted=False,
        )
        new_lead.tags = []
        new_lead.lifecycle_logs = []
        # get_lead's dict build reads .created_at/.updated_at; give real values.
        new_lead.created_at = datetime.utcnow()
        new_lead.updated_at = datetime.utcnow()

        # call sequence: (1) load conv (2) per-conversation dedup -> None
        # (3) get_lead(new_lead)  [customer dedup disabled -> no 3rd query]
        mock_db.execute.side_effect = [
            self._conv_result(conv),
            self._none_result(),
            self._get_result(new_lead),
        ]
        mock_db.refresh.side_effect = lambda obj: setattr(obj, "id", new_lead.id)

        lead = await create_lead_from_conversation(
            mock_db, conv_id, allow_customer_duplicate=True  # manual default
        )
        # A fresh lead was created for THIS conversation (human override allowed)
        assert lead["id"] == str(new_lead.id)
        assert lead["source_id"] == str(conv_id)
        assert len(mock_db.add.call_args_list) == 1

    async def test_check_duplicate_lead_for_customer_detects_existing(self, mock_db):
        from app.crm.services.lead import check_duplicate_lead_for_customer

        existing = Lead(id=uuid4(), customer_id=uuid4(), is_deleted=False)
        mock_db.execute.return_value = self._scalars_result([existing])
        assert await check_duplicate_lead_for_customer(mock_db, uuid4()) is True

    async def test_check_duplicate_lead_for_customer_none_customer(self, mock_db):
        from app.crm.services.lead import check_duplicate_lead_for_customer
        mock_db.execute.return_value = self._scalars_result([])
        assert await check_duplicate_lead_for_customer(mock_db, None) is False
        mock_db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Auto path end-to-end through the in-process bus (wiring idempotency)
# ---------------------------------------------------------------------------

class TestBusWiring:
    def test_register_is_idempotent(self):
        bus = get_event_bus()
        before = len(bus._subscribers.get("intent.classified", []))
        reset_conversation_lead_subscriber()
        n1 = register_conversation_lead_subscriber()
        n2 = register_conversation_lead_subscriber()
        assert n1 == 1 and n2 == 1
        after = len(bus._subscribers.get("intent.classified", []))
        # exactly one new handler from the two register calls (idempotent)
        assert after - before == 1


# ---------------------------------------------------------------------------
# 6. Manual trigger API surface (envelope + opt-in dedup flag)
# ---------------------------------------------------------------------------

class TestManualTriggerEndpoint:
    def test_route_registered_with_dedup_customer_param(self):
        from app.main import app
        from app.crm.routers.lead import create_lead_from_conversation as ep
        import inspect

        paths = [getattr(r, "path", "") for r in app.routes]
        assert "/api/v1/crm/leads/from-conversation/{conversation_id}" in paths
        assert "dedup_customer" in inspect.signature(ep).parameters
        # default keeps human-override semantics (customer dedup off). The
        # parameter default is a fastapi Query(...) object; the declared default
        # value lives on its .default attribute (Query(False, ...).default == False).
        q = inspect.signature(ep).parameters["dedup_customer"].default
        assert getattr(q, "default", q) is False

    def test_customer_dedup_route_registered(self):
        from app.main import app
        paths = [getattr(r, "path", "") for r in app.routes]
        assert (
            "/api/v1/crm/leads/customer/{customer_id}/duplicate-check"
            in paths
        )
        # static routes must precede the dynamic /{lead_id} route
        assert paths.index(
            "/api/v1/crm/leads/customer/{customer_id}/duplicate-check"
        ) < paths.index("/api/v1/crm/leads/{lead_id}")
