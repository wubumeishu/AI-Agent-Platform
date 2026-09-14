"""P6AN-04 Conversation Metrics: unit + 对拍 (SQL cross-check) tests.

Two layers, matching the repo convention (``test_analytics_p6an01`` fake
session; ``test_customer_messages`` live PG class gated by reachability,
``asyncio_mode="auto"``):

1. **Pure unit tests** (no DB) for the two pure pieces of the service:
   - ``ConversationMetricsService.resolve_range`` — window resolution.
   - ``ConversationMetricsService._assemble`` — the single place all
     division-by-zero / empty-data safety lives, so the "empty data returns
     safe defaults" acceptance criterion is asserted here explicitly.

2. **Live Postgres 对拍** (skipped when the test DB is unreachable): seed a
   fully deterministic customer/agent/conversation/message/intent graph, run
   the service, and assert **every** metric against hand-derived values AND
   against an independent, subquery-based raw SQL (a second opinion on the
   base counts — no ``IN``-list bind, no shared CTE with the service).
   Covers: unfiltered, ``agent_id``, ``intent_type`` and ``channel`` filters,
   and the empty-scope safe-defaults path.

Isolation: the seeded rows carry a far-future ``created_at`` (_NOW era) so a
7d window contains ONLY the seeded conversations — pre-existing test-DB rows
fall outside and never pollute the scoped queries.
"""
from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import uuid4

import pytest

from app.schemas.conversation_metrics import (
    AgentMetric,
    ConversationMetricsResponse,
    DEFAULT_INTENT_ACCURACY_THRESHOLD,
    ESCALATING_INTENT_TYPES,
    IntentMetric,
    PlatformMetric,
)
from app.services.conversation_metrics_service import (
    ConversationMetricsService,
    _safe_ratio,
)

_NOW = datetime(2035, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_TEST_URL = "postgresql+asyncpg://postgres:***@localhost:5432/ai_agent_platform_test"
_TEST_URL_ASYNCPG = "postgresql://postgres:***@localhost:5432/ai_agent_platform_test"


# ===========================================================================
# Pure helper
# ===========================================================================

def test_safe_ratio_zero_denominator():
    assert _safe_ratio(10, 0) == 0.0
    assert _safe_ratio(0, 0) == 0.0
    assert abs(_safe_ratio(5, 4) - 1.25) < 1e-9


# ===========================================================================
# resolve_range
# ===========================================================================

def test_resolve_range_default_is_30d():
    start, end, label = ConversationMetricsService.resolve_range(None, _NOW)
    assert label == "30d"
    assert end == _NOW
    assert start == _NOW - timedelta(days=30)


def test_resolve_range_explicit_tokens():
    for token, days in (("1d", 1), ("7d", 7), ("30d", 30), ("90d", 90), ("365d", 365)):
        start, end, label = ConversationMetricsService.resolve_range(token, _NOW)
        assert label == token
        assert start == _NOW - timedelta(days=days)
        assert end == _NOW


def test_resolve_range_unknown_falls_back_to_30d():
    start, end, label = ConversationMetricsService.resolve_range("bogus", _NOW)
    assert label == "30d"
    assert start == _NOW - timedelta(days=30)


def test_resolve_range_case_and_whitespace_insensitive():
    _, _, label = ConversationMetricsService.resolve_range("  7D ", _NOW)
    assert label == "7d"


# ===========================================================================
# _assemble — pure, empty-data safety + metric math
# ===========================================================================

def _raw_empty() -> Dict[str, Any]:
    """All-zero raw row, exactly as the SQL layer returns for an empty scope."""
    return {
        "total_conversations": 0, "total_messages": 0, "total_user_messages": 0,
        "avg_response_seconds": 0.0, "avg_duration_seconds": 0.0,
        "positive_sentiment": 0, "with_sentiment": 0,
        "total_intents": 0, "confident_intents": 0, "accurate_intents": 0,
        "escalating_intents": 0, "handoff_conversations": 0, "avg_confidence": 0.0,
    }


def test_assemble_empty_data_returns_safe_defaults():
    resp = ConversationMetricsService._assemble(
        _raw_empty(), [], [], [],
        filters={"agent_id": None, "intent_type": None, "channel": None},
        window={"start": "s", "end": "e", "window": "30d"},
        threshold=DEFAULT_INTENT_ACCURACY_THRESHOLD,
    )
    assert isinstance(resp, ConversationMetricsResponse)
    assert resp.has_data is False
    assert resp.sample_size == 0
    # every headline metric is a safe 0.0, no ZeroDivisionError
    assert resp.avg_conversation_rounds == 0.0
    assert resp.intent_accuracy == 0.0
    assert resp.human_handoff_rate == 0.0
    assert resp.satisfaction_rate == 0.0
    assert resp.by_platform == []
    assert resp.by_agent == []
    assert resp.by_intent == []


def test_assemble_rounds_and_rates_from_raw():
    raw = dict(_raw_empty())
    raw.update({
        "total_conversations": 4,
        "total_user_messages": 5,
        "total_intents": 4,
        "accurate_intents": 2,
        "handoff_conversations": 2,
        "positive_sentiment": 1,
        "with_sentiment": 3,
        "avg_response_seconds": 28 / 3,
        "avg_confidence": 0.6625,
    })
    resp = ConversationMetricsService._assemble(
        raw, [], [], [],
        filters={}, window={"start": "s", "end": "e", "window": "7d"},
        threshold=0.7,
    )
    assert resp.has_data is True
    assert resp.sample_size == 4
    assert resp.avg_conversation_rounds == round(5 / 4, 3)          # 1.25
    assert resp.intent_accuracy == round(2 / 4, 4)                   # 0.5
    assert resp.human_handoff_rate == round(2 / 4, 4)                # 0.5
    assert resp.satisfaction_rate == round(1 / 3, 4)                 # 0.3333
    assert resp.avg_response_time_seconds == round(28 / 3, 3)        # 9.333


def test_assemble_breakdown_rows_derived_fields():
    by_platform = [
        {"channel": "web", "conversations": 2, "user_messages": 3,
         "avg_duration_seconds": 60.0, "positive_sentiment": 0, "with_sentiment": 2},
        {"channel": "wechat", "conversations": 1, "user_messages": 2,
         "avg_duration_seconds": 120.0, "positive_sentiment": 1, "with_sentiment": 1},
    ]
    by_agent = [
        {"agent_id": uuid4(), "agent_name": "Alpha", "conversations": 2, "user_messages": 3},
    ]
    by_intent = [
        {"intent_type": "question", "total": 2, "accurate": 1, "avg_confidence": 0.65},
        {"intent_type": "escalation", "total": 1, "accurate": 1, "avg_confidence": 0.85},
    ]
    resp = ConversationMetricsService._assemble(
        _raw_empty(), by_platform, by_agent, by_intent,
        filters={}, window={}, threshold=0.7,
    )
    web, wechat = resp.by_platform
    assert isinstance(web, PlatformMetric)
    assert web.avg_rounds == round(3 / 2, 3)          # 1.5
    assert web.satisfaction_rate == 0.0               # 0 positive
    assert wechat.satisfaction_rate == 1.0            # 1/1
    assert wechat.avg_rounds == 2.0

    a = resp.by_agent[0]
    assert isinstance(a, AgentMetric)
    assert a.avg_rounds == 1.5

    q, esc = resp.by_intent
    assert isinstance(q, IntentMetric)
    assert q.accuracy == 0.5
    assert q.is_escalating is False
    assert esc.is_escalating is True                  # escalation is a handoff intent
    assert esc.accuracy == 1.0


def test_escalating_constant_matches_decision_engine():
    # Contract: the handoff intent set must stay in lockstep with the engine.
    from app.services.decision_engine import ESCALATING_INTENTS
    assert set(ESCALATING_INTENT_TYPES) == set(ESCALATING_INTENTS)


# ===========================================================================
# Live Postgres 对拍 — seed deterministic data, cross-check every metric
# ===========================================================================

def _pg_available() -> bool:
    if importlib.util.find_spec("asyncpg") is None:
        return False
    try:
        import asyncpg

        async def _probe():
            c = await asyncpg.connect(_TEST_URL_ASYNCPG, timeout=3)
            await c.close()

        asyncio.new_event_loop().run_until_complete(_probe())
        return True
    except Exception:
        return False


requires_pg = pytest.mark.skipif(not _pg_available(), reason="Postgres test DB unreachable")


# ---------------------------------------------------------------------------
# Expected hand-computed values (the 对拍 targets) for the seeded graph.
#
# Seed (all created_at = base_dt = 2034-12-30, which is inside a 7d window
# ending _NOW = 2035-01-01):
#   conv1 C1 web... wechat positive  duration=120  msgs: u(0),a(5),u(10),a(13)
#   conv2 C2 web   neutral          duration=60   msgs: u(0),a(20)
#   conv3 C3 douyin None           duration=300  msgs: (none)
#   conv4 C4 web   negative        duration=None msgs: u(0),u(5)
#   conv5 C1 web   None            duration=999  created 31 days before -> OUT
#   agents: AG1->{C1,C2}, AG2->{C2,C3}
#   intents (all live except the last, which is soft-deleted):
#     conv1 question 0.9 answer_question
#     conv2 escalation 0.85 escalate
#     conv3 complaint 0.5 None
#     conv4 question 0.4 None
#     conv1 thanks 0.99  -> SOFT-DELETED (excluded)
# ---------------------------------------------------------------------------

def _expected_no_filter() -> Dict[str, Any]:
    # Every key here must be a field on ConversationMetricsResponse (the test
    # does ``getattr(resp, k)`` for each). The per-intent "accurate" count is
    # exposed only through the derived ``intent_accuracy`` (accurate/total).
    return {
        "total_conversations": 4,        # conv1..4 (conv5 out of window)
        "total_messages": 8,             # 4 + 2 + 0 + 2
        "total_user_messages": 5,        # 2 + 1 + 0 + 2
        "avg_response_time_seconds": round(28 / 3, 3),  # user->assistant gaps [5,3,20]
        "avg_duration_seconds": 160.0,   # (120+60+300)/3, conv4 duration NULL
        "positive_sentiment": 1,
        "with_sentiment": 3,             # conv1, conv2, conv4
        "total_intents": 4,             # thanks is soft-deleted
        "confident_intents": 2,         # 0.9, 0.85  (>=0.7)
        "escalating_intents": 2,        # conv2 escalation + conv3 complaint
        "handoff_conversations": 2,     # conv2, conv3
        "avg_confidence": round(2.65 / 4, 4),  # 0.6625
        "avg_conversation_rounds": 1.25,
        "intent_accuracy": 0.5,         # accurate(2)/total(4)
        "human_handoff_rate": 0.5,
        "satisfaction_rate": round(1 / 3, 4),
    }


@requires_pg
class TestConversationMetricsLive:
    """Every metric cross-checked against hand-computed values on live PG."""

    # --------------------------------------------------------------- #
    # deterministic seed (isolated by far-future created_at) + cleanup
    # --------------------------------------------------------------- #
    @pytest.fixture
    async def graph(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.db.models import Base
        from app.db.models.agent import Agent, AgentCustomerBinding
        from app.db.models.conversation import Conversation, Message
        from app.db.models.customer import Customer
        from app.db.models.intent import Intent
        from sqlalchemy import delete, select

        base_dt = datetime(2034, 12, 30, 0, 0, 0, tzinfo=timezone.utc)

        engine = create_async_engine(self.TEST_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as db:
            c1, c2, c3, c4 = (Customer(name=f"CPM-{i}") for i in range(1, 5))
            for c in (c1, c2, c3, c4):
                db.add(c)
            await db.commit()

            ag1, ag2 = Agent(name="Alpha"), Agent(name="Beta")
            db.add_all([ag1, ag2])
            await db.commit()
            bindings = [
                AgentCustomerBinding(agent_id=ag1.id, customer_id=c1.id),
                AgentCustomerBinding(agent_id=ag1.id, customer_id=c2.id),
                AgentCustomerBinding(agent_id=ag2.id, customer_id=c2.id),
                AgentCustomerBinding(agent_id=ag2.id, customer_id=c3.id),
            ]
            db.add_all(bindings)
            await db.commit()

            def conv(customer, channel, sentiment, duration):
                return Conversation(customer_id=customer.id, channel=channel,
                                    sentiment=sentiment, duration_seconds=duration,
                                    created_at=base_dt)
            conv1 = conv(c1, "wechat", "positive", 120)
            conv2 = conv(c2, "web", "neutral", 60)
            conv3 = conv(c3, "douyin", None, 300)
            conv4 = conv(c4, "web", "negative", None)
            conv5 = conv(c1, "web", None, 999)
            conv5.created_at = base_dt - timedelta(days=31)   # outside the 7d window
            convs = [conv1, conv2, conv3, conv4, conv5]
            db.add_all(convs)
            await db.commit()

            def add_msgs(conversation, spec):
                for role, offset_s in spec:
                    db.add(Message(conversation_id=conversation.id, role=role,
                                   content="x",
                                   created_at=base_dt + timedelta(seconds=offset_s)))
            add_msgs(conv1, [("user", 0), ("assistant", 5), ("user", 10), ("assistant", 13)])
            add_msgs(conv2, [("user", 0), ("assistant", 20)])
            add_msgs(conv4, [("user", 0), ("user", 5)])
            add_msgs(conv5, [("user", 0)])
            await db.commit()

            def intent(conversation, itype, conf, action):
                return Intent(conversation_id=conversation.id, intent_type=itype,
                              intent_name=itype, confidence=conf, raw_input="probe",
                              matched_action=action)
            db.add_all([
                intent(conv1, "question", 0.9, "answer_question"),
                intent(conv2, "escalation", 0.85, "escalate"),
                intent(conv3, "complaint", 0.5, None),
                intent(conv4, "question", 0.4, None),
                intent(conv1, "thanks", 0.99, "acknowledge_thanks"),
            ])
            await db.commit()
            thanks = (await db.execute(
                select(Intent).where(Intent.conversation_id == conv1.id,
                                     Intent.intent_type == "thanks")
            )).scalar_one()
            thanks.is_deleted = True
            await db.commit()

            conv_ids = [c.id for c in convs]
            cust_ids = [c.id for c in (c1, c2, c3, c4)]
            agent_ids = [ag1.id, ag2.id]
            handle = {"db": db, "ag1": ag1, "ag2": ag2}
            try:
                yield handle
            finally:
                # Deterministic cleanup so re-runs see a clean scoped window.
                await db.execute(delete(Intent).where(Intent.conversation_id.in_(conv_ids)))
                await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
                await db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))
                await db.execute(delete(AgentCustomerBinding)
                                 .where(AgentCustomerBinding.agent_id.in_(agent_ids)))
                await db.execute(delete(Agent).where(Agent.id.in_(agent_ids)))
                await db.execute(delete(Customer).where(Customer.id.in_(cust_ids)))
                await db.commit()
                await db.close()
                await engine.dispose()

    # --------------------------------------------------------------- #
    # test helpers
    # --------------------------------------------------------------- #
    TEST_URL = "postgresql+asyncpg://postgres:***@localhost:5432/ai_agent_platform_test"

    async def _compute(self, graph, now=_NOW, range_value="7d", **kw):
        svc = ConversationMetricsService(graph["db"])
        return await svc.compute(
            agent_id=kw.get("agent_id"), range_value=range_value,
            intent_type=kw.get("intent_type"), channel=kw.get("channel"),
            threshold=kw.get("threshold", DEFAULT_INTENT_ACCURACY_THRESHOLD), now=now,
        )

    # --------------------------------------------------------------- #
    # unfiltered: every metric + all three breakdowns
    # --------------------------------------------------------------- #
    async def test_unfiltered_matches_hand_computed(self, graph):
        resp = await self._compute(graph)
        exp = _expected_no_filter()
        assert resp.sample_size == exp["total_conversations"]
        assert resp.has_data is True
        for k, v in exp.items():
            assert abs(getattr(resp, k) - v) < 1e-3, f"{k}: {getattr(resp, k)} != {v}"

        # by_platform: 3 channels
        by_ch = {p.channel: p for p in resp.by_platform}
        assert sorted(by_ch) == ["douyin", "web", "wechat"]
        assert by_ch["wechat"].conversations == 1 and by_ch["wechat"].avg_rounds == 2.0
        assert by_ch["wechat"].satisfaction_rate == 1.0
        assert by_ch["web"].conversations == 2 and by_ch["web"].avg_rounds == 1.5
        assert by_ch["web"].satisfaction_rate == 0.0
        assert by_ch["douyin"].conversations == 1 and by_ch["douyin"].avg_rounds == 0.0

        # by_agent: both agents co-cover conv2
        agents = {a.agent_name: a for a in resp.by_agent}
        assert agents["Alpha"].conversations == 2 and agents["Alpha"].user_messages == 3
        assert agents["Beta"].conversations == 2 and agents["Beta"].user_messages == 1

        # by_intent
        intents = {i.intent_type: i for i in resp.by_intent}
        assert intents["question"].total == 2 and intents["question"].accuracy == 0.5
        assert intents["escalation"].is_escalating and intents["escalation"].accuracy == 1.0
        assert intents["complaint"].is_escalating and intents["complaint"].accuracy == 0.0

    # --------------------------------------------------------------- #
    # agent filter
    # --------------------------------------------------------------- #
    async def test_agent_filter_scopes_to_that_agent(self, graph):
        resp = await self._compute(graph, agent_id=graph["ag1"].id)
        assert resp.sample_size == 2                    # AG1 -> C1,C2 => conv1,conv2
        assert resp.total_user_messages == 3            # conv1(2) + conv2(1)
        assert resp.total_intents == 2                  # conv1 question + conv2 escalation
        assert resp.accurate_intents == 2
        assert resp.handoff_conversations == 1          # only conv2
        assert len(resp.by_agent) == 1
        assert resp.by_agent[0].agent_id == graph["ag1"].id
        assert resp.by_agent[0].conversations == 2

    # --------------------------------------------------------------- #
    # intent_type filter
    # --------------------------------------------------------------- #
    async def test_intent_type_filter(self, graph):
        resp = await self._compute(graph, intent_type="escalation")
        assert resp.sample_size == 1                     # only conv2
        assert resp.total_intents == 1
        assert resp.accurate_intents == 1
        assert resp.human_handoff_rate == 1.0            # 1/1
        assert resp.avg_response_time_seconds == 20.0     # conv2 gap

    # --------------------------------------------------------------- #
    # channel (platform) filter
    # --------------------------------------------------------------- #
    async def test_channel_filter(self, graph):
        resp = await self._compute(graph, channel="wechat")
        assert resp.sample_size == 1                      # only conv1
        assert resp.total_user_messages == 2
        assert resp.avg_conversation_rounds == 2.0
        assert resp.avg_response_time_seconds == round(4.0, 3)  # (5+3)/2
        assert resp.satisfaction_rate == 1.0               # conv1 positive

    # --------------------------------------------------------------- #
    # empty scope -> safe defaults
    # --------------------------------------------------------------- #
    async def test_empty_scope_returns_safe_defaults(self, graph):
        resp = await self._compute(graph, now=_NOW - timedelta(days=40), range_value="7d")
        assert resp.has_data is False
        assert resp.sample_size == 0
        assert resp.avg_conversation_rounds == 0.0
        assert resp.intent_accuracy == 0.0
        assert resp.human_handoff_rate == 0.0
        assert resp.satisfaction_rate == 0.0
        assert resp.by_platform == [] and resp.by_agent == [] and resp.by_intent == []

    # --------------------------------------------------------------- #
    # window boundaries: 30d keeps conv1-4 (conv5 is 31d out), 1d keeps none
    # --------------------------------------------------------------- #
    async def test_out_of_window_conversation_excluded(self, graph):
        wide = await self._compute(graph, range_value="30d")
        assert wide.sample_size == 4
        narrow = await self._compute(graph, range_value="1d")
        assert narrow.sample_size == 0
        assert narrow.has_data is False

    # --------------------------------------------------------------- #
    # 对拍: independent raw SQL (subquery, no IN-list / no shared CTE)
    # --------------------------------------------------------------- #
    async def test_raw_sql_crosscheck_counts(self, graph):
        from sqlalchemy import text
        db = graph["db"]
        start = _NOW - timedelta(days=7)

        conv_count = (await db.execute(text(
            "select count(*) from conversation c where c.is_deleted=false "
            "and c.created_at>=:s and c.created_at<:e"
        ), {"s": start, "e": _NOW})).scalar_one()

        user_msgs = (await db.execute(text(
            "select count(*) from message m where m.is_deleted=false and m.role='user' "
            "and exists (select 1 from conversation c where c.id=m.conversation_id "
            "and c.is_deleted=false and c.created_at>=:s and c.created_at<:e)"
        ), {"s": start, "e": _NOW})).scalar_one()

        resp = await self._compute(graph)
        assert conv_count == resp.total_conversations == 4
        assert user_msgs == resp.total_user_messages == 5
