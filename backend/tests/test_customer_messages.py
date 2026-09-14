"""P5MSG-05 tests — customer 360 message timeline + CRM write-back + intent landing.

Layers (mirrors repo conventions in test_message_delivery.py):

* ``TestTimelineMerge`` / ``TestTimelineQueries`` / ``TestTimelineValidation``
  — pure logic: k-way merge, query builders, filter-domain validation
  (no DB).
* ``TestCrmMessageWriteback`` / ``TestIntentLander`` — service layer against
  a mocked AsyncSession: idempotency (dedup key / identical-value no-op),
  bus-safe no-raise, activity shaping.
* ``TestCustomerMessagesAPILive`` — full E2E against the real Postgres test
  DB (skipped automatically when unreachable): timeline query + idempotent
  CRM write-back + intent landing through a real engine.
"""
from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models.conversation import Conversation, Message
from app.db.models.customer import Customer
from app.db.models.intent import Intent
from app.db.models.memory import ActivityLog
from app.db.models.messages import ChannelMessage, MESSAGE_DIRECTIONS, MESSAGE_STATUSES
from app.events.domain_events import DomainEvent

from app.crm.services.customer_messages import (
    CustomerResourceNotFound,
    TimelineParameterError,
    _channel_query,
    _chat_query,
    _merge,
    _validate_filters,
    get_customer_message_timeline,
    TIMELINE_KINDS,
)
from app.crm.services.message_crm_writeback import (
    CrmMessageEventWriteback,
    event_key_for,
)
from app.services.intent_conversation_lander import IntentConversationLander


# ===========================================================================
# helpers
# ===========================================================================


def _mk_db(execute_returns: Optional[List] = None) -> AsyncMock:
    """Build an AsyncSession mock whose db.execute() pops from a queue of
    pre-baked result objects (each produced by ``_mk_result``)."""
    results: List[MagicMock] = list(execute_returns or [])
    db = AsyncMock(spec=AsyncSession)
    if results:
        db.execute = AsyncMock(side_effect=results)
    else:
        db.execute = AsyncMock(return_value=_mk_result())
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    return db


def _mk_result(*, first=None, scalar=None, row=None, count=0, items=None) -> MagicMock:
    """One pre-baked result. ``items`` feeds BOTH ``.all()`` (row tuples, used
    by the chat/channel queries) and ``.scalars().all()`` (entity lists, used
    by the intent query) so a single factory covers all service call sites."""
    r = MagicMock()
    r.first.return_value = first
    r.scalar_one_or_none.return_value = scalar
    r.one_or_none.return_value = row
    r.scalar_one.return_value = count
    all_items = items if items is not None else []
    r.all.return_value = all_items
    scalars = MagicMock()
    scalars.all.return_value = all_items
    r.scalars.return_value = scalars
    return r


def _mk_conv(**overrides) -> MagicMock:
    c = MagicMock(spec=Conversation)
    c.id = overrides.pop("id", uuid4())
    c.customer_id = overrides.pop("customer_id", uuid4())
    c.channel = overrides.pop("channel", "web")
    c.metadata_ = overrides.pop("metadata_", None)
    c.created_at = overrides.pop("created_at", datetime.now(timezone.utc))
    c.is_deleted = overrides.pop("is_deleted", False)
    c.__dict__.update(overrides)
    return c


def _mk_msg(**overrides) -> MagicMock:
    m = MagicMock(spec=Message)
    m.id = overrides.pop("id", uuid4())
    m.conversation_id = overrides.pop("conversation_id", uuid4())
    m.role = overrides.pop("role", "user")
    m.content = overrides.pop("content", "hi")
    m.created_at = overrides.pop("created_at", datetime.now(timezone.utc))
    m.is_deleted = overrides.pop("is_deleted", False)
    m.__dict__.update(overrides)
    return m


def _mk_channel_msg(**overrides) -> MagicMock:
    m = MagicMock(spec=ChannelMessage)
    m.id = overrides.pop("id", uuid4())
    m.conversation_id = overrides.pop("conversation_id", uuid4())
    m.channel = overrides.pop("channel", "wechat")
    m.direction = overrides.pop("direction", "out")
    m.status = overrides.pop("status", "sent")
    m.provider_message_id = overrides.pop("provider_message_id", None)
    m.sent_at = overrides.pop("sent_at", None)
    m.received_at = overrides.pop("received_at", None)
    m.created_at = overrides.pop("created_at", datetime.now(timezone.utc))
    m.is_deleted = overrides.pop("is_deleted", False)
    m.__dict__.update(overrides)
    return m


def _mk_intent(**overrides) -> MagicMock:
    i = MagicMock(spec=Intent)
    i.id = overrides.pop("id", uuid4())
    i.conversation_id = overrides.pop("conversation_id", uuid4())
    i.intent_type = overrides.pop("intent_type", "question")
    i.intent_name = overrides.pop("intent_name", "提问")
    i.confidence = overrides.pop("confidence", 0.8)
    i.created_at = overrides.pop("created_at", datetime.now(timezone.utc))
    i.is_deleted = overrides.pop("is_deleted", False)
    i.__dict__.update(overrides)
    return i


# ===========================================================================
# 1. Pure merge + validation + query-builder logic (no DB)
# ===========================================================================


class TestTimelineMerge:
    """The k-way merge is the heart of the 360 timeline view: two
    desc-sorted source lists must interleave by timestamp, ties break on
    the larger UUID, and None timestamps sort last."""

    def test_interleaves_descending(self):
        t0 = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)

        def e(uid, ts, **extra):
            d = {"id": str(uid), "created_at": ts.isoformat(), "_ts": ts}
            d.update(extra)
            return d

        chat = [e(uuid4(), t0 + timedelta(hours=2), kind="chat")]
        channel = [
            e(uuid4(), t0 + timedelta(hours=3), kind="channel"),
            e(uuid4(), t0 + timedelta(hours=1), kind="channel"),
        ]
        out = _merge(list(chat), list(channel))
        # newest first: +3h channel, +2h chat, +1h channel
        assert [x["kind"] for x in out] == ["channel", "chat", "channel"]
        assert all("_ts" not in x for x in out)  # helper key stripped

    def test_none_timestamps_sort_last(self):
        t0 = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
        chat = [{"id": str(uuid4()), "kind": "chat", "_ts": None, "created_at": None}]
        channel = [{"id": str(uuid4()), "kind": "channel", "_ts": t0, "created_at": t0.isoformat()}]
        out = _merge(chat, channel)
        assert [x["kind"] for x in out] == ["channel", "chat"]

    def test_tie_breaks_on_uuid_desc(self):
        t0 = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
        big, small = uuid4(), UUID(int=0)
        chat = [{"id": str(small), "kind": "chat", "_ts": t0, "created_at": t0.isoformat()}]
        channel = [{"id": str(big), "kind": "channel", "_ts": t0, "created_at": t0.isoformat()}]
        out = _merge(chat, channel)
        assert [x["id"] for x in out] == [str(big), str(small)]

    def test_one_sided(self):
        t0 = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
        chat = [{"id": str(uuid4()), "kind": "chat", "_ts": t0}]
        out = _merge(chat, [])
        assert len(out) == 1 and "_ts" not in out[0]


class TestTimelineValidation:
    def test_accepts_full_domain(self):
        _validate_filters("chat", "wechat", "in", "sent")
        _validate_filters(None, None, None, None)

    @pytest.mark.parametrize("kind", ["chat", "channel"])
    def test_kind_domain(self, kind):
        assert kind in TIMELINE_KINDS

    def test_rejects_bad_kind(self):
        with pytest.raises(TimelineParameterError):
            _validate_filters("sms", None, None, None)

    def test_rejects_bad_channel(self):
        with pytest.raises(TimelineParameterError):
            _validate_filters(None, "carrier-pigeon", None, None)

    def test_rejects_bad_direction(self):
        with pytest.raises(TimelineParameterError):
            _validate_filters(None, None, "sideways", None)

    def test_rejects_bad_status(self):
        with pytest.raises(TimelineParameterError):
            _validate_filters(None, None, None, "exploded")


class TestTimelineQueries:
    """Query builders apply exactly the filters the caller passed.

    Compiled to the (version-stable) SQL string and asserted on the column
    / table fragments, rather than reaching into SQLAlchemy internals.
    """

    @staticmethod
    def _sql(query) -> str:
        from sqlalchemy.dialects import postgresql

        return str(query.compile(compile_kwargs={"literal_binds": True}, dialect=postgresql.dialect()))

    def test_chat_query_base_filters(self):
        q = _chat_query(uuid4(), None, None, None, None)
        sql = self._sql(q)
        assert "customer_id" in sql
        assert "message" in sql

    def test_chat_query_all_filters(self):
        now = datetime.now(timezone.utc)
        q = _chat_query(uuid4(), uuid4(), "wechat", now, now)
        sql = self._sql(q)
        assert "conversation_id" in sql  # conversation narrowing
        assert "channel" in sql           # conversation-level channel
        assert "wechat" in sql

    def test_channel_query_all_filters(self):
        now = datetime.now(timezone.utc)
        q = _channel_query(uuid4(), None, "wechat", "in", "sent", now, now)
        sql = self._sql(q)
        assert "customer_id" in sql
        assert "channel" in sql
        assert "direction" in sql
        assert "status" in sql
        assert "created_at" in sql


# ===========================================================================
# 2. Timeline service against a mocked session
# ===========================================================================


class TestTimelineServiceMock:
    async def test_unknown_customer_raises_404(self):
        db = _mk_db([_mk_result(first=None)])  # customer lookup -> None
        with pytest.raises(CustomerResourceNotFound):
            await get_customer_message_timeline(db, uuid4())

    async def test_full_timeline_merge_and_shapes(self):
        cust = uuid4()
        conv = _mk_conv(id=uuid4(), customer_id=cust, channel="wechat")
        chat_rows = [
            (_mk_msg(id=uuid4(), conversation_id=conv.id, role="user", content="c1"), "wechat"),
        ]
        chan_rows = [_mk_channel_msg(conversation_id=conv.id, status="delivered", direction="out")]
        intent_rows = [_mk_intent(conversation_id=conv.id)]

        # db.execute sequence: customer check, chat rows, channel rows, intents
        db = _mk_db([
            _mk_result(first=(cust,)),
            _mk_result(items=chat_rows),
            _mk_result(items=chan_rows),
            _mk_result(items=intent_rows),
        ])
        data = await get_customer_message_timeline(db, cust)
        assert data["customer_id"] == str(cust)
        assert data["total"] == 2
        kinds = {m["kind"] for m in data["messages"]}
        assert kinds == {"chat", "channel"}
        assert data["recent_intents"][0]["intent_type"] == "question"
        # helper keys stripped
        assert all("_ts" not in m for m in data["messages"])

    async def test_kind_filter_limits_sources(self):
        cust = uuid4()
        conv = _mk_conv(id=uuid4(), customer_id=cust)
        db = _mk_db([
            _mk_result(first=(cust,)),
            _mk_result(items=[(_mk_msg(conversation_id=conv.id), "web")]),  # chat only fetched
            _mk_result(items=[]),  # channel still queried (kind==None path) — replaced below
        ])
        # kind="chat": no channel rows queried; total == chat rows only
        db = _mk_db([
            _mk_result(first=(cust,)),
            _mk_result(items=[(_mk_msg(conversation_id=conv.id), "web")]),
            _mk_result(items=[]),
        ])
        data = await get_customer_message_timeline(db, cust, kind="chat")
        assert data["total"] == 1
        assert all(m["kind"] == "chat" for m in data["messages"])

    async def test_skip_limit_window(self):
        cust = uuid4()
        conv = _mk_conv(id=uuid4(), customer_id=cust)
        msgs = [(_mk_msg(conversation_id=conv.id, content=f"m{i}"), "web") for i in range(5)]
        db = _mk_db([
            _mk_result(first=(cust,)),
            _mk_result(items=msgs),
            _mk_result(items=[]),
            _mk_result(items=[]),
        ])
        data = await get_customer_message_timeline(db, cust, skip=2, limit=2)
        assert len(data["messages"]) == 2
        assert data["skip"] == 2 and data["limit"] == 2


# ===========================================================================
# 3. CRM message-event write-back (idempotent, bus-safe)
# ===========================================================================


class TestCrmMessageWriteback:
    def _event(self, message_id=None, conv_id=None, role="user"):
        return DomainEvent(
            event_type="message.created",
            entity_type="message",
            entity_id=message_id or uuid4(),
            payload={
                "conversation_id": str(conv_id or uuid4()),
                "message_id": str(message_id or uuid4()),
                "role": role,
            },
        )

    def test_event_key_is_stable(self):
        mid, cid = uuid4(), uuid4()
        e1 = self._event(message_id=mid, conv_id=cid)
        e2 = self._event(message_id=mid, conv_id=cid)
        assert event_key_for(e1) == event_key_for(e2)
        assert event_key_for(e1).startswith("message.created:")

    async def test_non_matching_event_type_is_noop(self):
        svc = CrmMessageEventWriteback(_mk_db())
        ev = DomainEvent("conversation.created", "conversation", uuid4())
        out = await svc.handle_domain_event(ev)
        assert out is None

    async def test_missing_conversation_id_is_noop(self):
        svc = CrmMessageEventWriteback(_mk_db())
        ev = DomainEvent("message.created", "message", uuid4(), payload={})
        out = await svc.handle_domain_event(ev)
        assert out is None

    async def test_gone_conversation_is_noop(self):
        conv = uuid4()
        db = _mk_db([_mk_result(scalar=None)])  # conversation lookup -> None
        svc = CrmMessageEventWriteback(db)
        out = await svc.handle_domain_event(self._event(conv_id=conv))
        assert out is None

    async def test_duplicate_event_is_noop(self):
        cust = uuid4()
        conv = _mk_conv(id=uuid4(), customer_id=cust, channel="wechat")
        db = _mk_db([
            _mk_result(scalar=conv),        # conversation exists
            _mk_result(first=(str(uuid4()),)),  # an activity with this key already exists
        ])
        svc = CrmMessageEventWriteback(db)
        out = await svc.handle_domain_event(self._event(conv_id=conv.id))
        assert out is None
        db.add.assert_not_called()  # no duplicate row written
        db.commit.assert_not_awaited()

    async def test_fresh_event_writes_activity(self):
        cust = uuid4()
        conv = _mk_conv(id=uuid4(), customer_id=cust, channel="wechat")
        db = _mk_db([
            _mk_result(scalar=conv),       # conversation exists
            _mk_result(first=None),        # no existing dedup row
        ])
        svc = CrmMessageEventWriteback(db)
        out = await svc.handle_domain_event(self._event(conv_id=conv.id, role="user"))
        assert out is not None
        assert out["event_key"].startswith("message.created:")
        added = [c.args[0] for c in db.add.call_args_list if c.args]
        assert any(isinstance(a, ActivityLog) for a in added)
        activity = next(a for a in added if isinstance(a, ActivityLog))
        assert activity.activity_type == "chat_message"
        assert activity.metadata_["event_key"] == out["event_key"]
        db.commit.assert_awaited()

    async def test_direction_derived_from_role(self):
        cust = uuid4()
        conv = _mk_conv(id=uuid4(), customer_id=cust)

        class FakeDB:
            def __init__(self):
                self.added = []
                self.commit_called = 0
                self.rollback_called = 0

            async def execute(self, q):
                r = MagicMock()
                r.scalar_one_or_none.return_value = conv
                r.first.return_value = None  # no dedup row
                return r

            def add(self, obj):
                self.added.append(obj)

            async def commit(self):
                self.commit_called += 1

            async def rollback(self):
                self.rollback_called += 1

        db = FakeDB()
        svc = CrmMessageEventWriteback(db)
        await svc.handle_domain_event(self._event(conv_id=conv.id, role="user"))
        inbound = db.added[0]
        assert "收到" in inbound.title  # inbound phrasing

        db.added = []
        await svc.handle_domain_event(self._event(conv_id=conv.id, role="assistant"))
        outbound = db.added[0]
        assert "发出" in outbound.title


# ===========================================================================
# 4. AI-intent data landing on the conversation (idempotent upsert)
# ===========================================================================


class TestIntentLander:
    def _event(self, conv_id=None, intent_type="question", confidence=0.9):
        return DomainEvent(
            event_type="intent.classified",
            entity_type="intent",
            entity_id=uuid4(),
            payload={
                "conversation_id": str(conv_id or uuid4()),
                "intent_type": intent_type,
                "intent_name": "提问",
                "confidence": confidence,
            },
        )

    async def test_non_matching_event_is_noop(self):
        svc = IntentConversationLander(_mk_db())
        out = await svc.handle_domain_event(DomainEvent("message.created", "message", uuid4()))
        assert out is None

    async def test_identical_classification_is_noop(self):
        cust = uuid4()
        existing = {"last_intent": {"intent_type": "question", "confidence": 0.9,
                                    "intent_name": "提问", "classified_at": "x"}}
        conv = _mk_conv(id=uuid4(), customer_id=cust, metadata_=None)
        conv.metadata_ = dict(existing)

        db = _mk_db([_mk_result(scalar=conv)])
        svc = IntentConversationLander(db)
        out = await svc.handle_domain_event(self._event(conv_id=conv.id))
        # A fully-equal stored value must be a no-op (idempotency).
        assert out is None
        db.commit.assert_not_awaited()

    async def test_new_classification_overwrites(self):
        cust = uuid4()
        conv = _mk_conv(id=uuid4(), customer_id=cust, metadata_=None)

        db = _mk_db([_mk_result(scalar=conv)])
        svc = IntentConversationLander(db)
        out = await svc.handle_domain_event(
            self._event(conv_id=conv.id, intent_type="callback_request", confidence=0.85)
        )
        assert out is not None
        assert out["intent_type"] == "callback_request"
        assert "last_intent" in conv.metadata_
        assert conv.metadata_["last_intent"]["intent_type"] == "callback_request"
        db.commit.assert_awaited()

    async def test_missing_conversation_id_is_noop(self):
        svc = IntentConversationLander(_mk_db())
        out = await svc.handle_domain_event(DomainEvent(
            "intent.classified", "intent", uuid4(), payload={}))
        assert out is None


# ===========================================================================
# 5. Live Postgres E2E (skipped when the test DB is unreachable)
# ===========================================================================


def _pg_available() -> bool:
    if importlib.util.find_spec("asyncpg") is None:
        return False
    try:
        import asyncpg  # noqa: F401

        async def _probe():
            conn = await asyncpg.connect(
                "postgresql://postgres:***@localhost:5432/ai_agent_platform_test",
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


requires_pg = pytest.mark.skipif(not _pg_available(), reason="Postgres test DB unreachable")


@requires_pg
class TestCustomerMessagesAPILive:
    TEST_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"

    @pytest.fixture
    async def db(self):
        from app.db.models import Base

        engine = create_async_engine(self.TEST_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            yield session
        await engine.dispose()

    async def _seed(self, db):
        """Seed a customer + conversation + one chat msg + one channel msg."""
        cust = Customer(name="P5MSG-05-客户")
        db.add(cust)
        await db.commit()
        conv = Conversation(customer_id=cust.id, channel="wechat", subject="e2e")
        db.add(conv)
        await db.commit()

        chat = Message(conversation_id=conv.id, role="user", content="请问多少钱？")
        db.add(chat)
        await db.commit()

        chan = ChannelMessage(
            conversation_id=conv.id, channel="wechat", direction="out",
            status="sent", content={"text": "您好，报价单已发送"},
        )
        db.add(chan)
        await db.commit()

        it = Intent(
            conversation_id=conv.id, intent_type="question", intent_name="提问",
            confidence=0.82, raw_input="请问多少钱？", extracted_entities={}, context={},
        )
        db.add(it)
        await db.commit()
        return cust, conv, chat, chan, it

    async def test_timeline_merge_desc_order(self, db):
        cust, conv, chat, chan, _ = await self._seed(db)

        data = await get_customer_message_timeline(db, cust.id, limit=50)
        assert data["total"] >= 2
        kinds = [m["kind"] for m in data["messages"]]
        assert "chat" in kinds and "channel" in kinds
        # time-descending: verify created_at is monotonically non-increasing
        stamps = [m["created_at"] for m in data["messages"]]
        assert stamps == sorted(stamps, reverse=True)

    async def test_timeline_kind_filter(self, db):
        cust, conv, chat, chan, _ = await self._seed(db)
        only_channel = await get_customer_message_timeline(db, cust.id, kind="channel", limit=50)
        assert all(m["kind"] == "channel" for m in only_channel["messages"])
        assert only_channel["total"] == 1

    async def test_timeline_unknown_customer_raises(self, db):
        with pytest.raises(CustomerResourceNotFound):
            await get_customer_message_timeline(db, uuid4())

    async def test_writeback_idempotent(self, db):
        cust, conv, chat, chan, _ = await self._seed(db)
        svc = CrmMessageEventWriteback(db)
        ev = DomainEvent(
            "message.created", "message", chat.id,
            payload={"conversation_id": str(conv.id), "message_id": str(chat.id), "role": "user"},
        )
        first = await svc.handle_domain_event(ev)
        assert first is not None

        # duplicate delivery -> no-op, no second row
        second = await CrmMessageEventWriteback(db).handle_domain_event(ev)
        assert second is None

        rows = (await db.execute(
            select(ActivityLog.id).where(
                ActivityLog.customer_id == cust.id,
                ActivityLog.activity_type == "chat_message",
            )
        )).scalars().all()
        assert len(rows) == 1

    async def test_intent_landing_idempotent(self, db):
        cust, conv, chat, chan, it = await self._seed(db)
        svc = IntentConversationLander(db)
        ev = DomainEvent(
            "intent.classified", "intent", uuid4(),
            payload={
                "conversation_id": str(conv.id),
                "intent_type": it.intent_type,
                "intent_name": it.intent_name,
                "confidence": it.confidence,
            },
        )
        first = await svc.handle_domain_event(ev)
        assert first is not None
        fresh = (await db.execute(select(Conversation).where(Conversation.id == conv.id))).scalar_one()
        assert fresh.metadata_["last_intent"]["intent_type"] == it.intent_type

        # identical re-delivery -> no-op (committed row unchanged)
        noop = await IntentConversationLander(db).handle_domain_event(
            DomainEvent("intent.classified", "intent", uuid4(), payload=ev.payload)
        )
        assert noop is None

    async def test_intent_landing_overwrites_newer(self, db):
        cust, conv, chat, chan, it = await self._seed(db)
        svc = IntentConversationLander(db)
        await svc.handle_domain_event(DomainEvent(
            "intent.classified", "intent", uuid4(),
            payload={"conversation_id": str(conv.id), "intent_type": "question",
                     "confidence": 0.5},
        ))
        newer = await IntentConversationLander(db).handle_domain_event(DomainEvent(
            "intent.classified", "intent", uuid4(),
            payload={"conversation_id": str(conv.id), "intent_type": "callback_request",
                     "intent_name": "请求回电", "confidence": 0.95},
        ))
        assert newer is not None
        fresh = (await db.execute(select(Conversation).where(Conversation.id == conv.id))).scalar_one()
        assert fresh.metadata_["last_intent"]["intent_type"] == "callback_request"
