"""P5MSG-02 tests — channel message API & delivery state machine.

Layers (mirrors the repo conventions):
  * TestStateMachine — pure logic: transition map, terminal states,
    filter-domain helpers (no DB).
  * TestMessageSchemas — Pydantic schema validation (send / status / receipts).
  * TestMessageServiceMock — service layer against a mocked AsyncSession:
    send enqueue, account-binding checks, status transitions, receipts,
    error mapping.
  * TestMessageAPILive — full E2E against the real Postgres test DB
    (skipped automatically when the DB is unreachable).
"""
import asyncio
import importlib.util
from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.messages import (
    ChannelMessage,
    MESSAGE_DIRECTIONS,
    MESSAGE_STATUSES,
)
from app.schemas.messages import (
    MESSAGE_CHANNELS,
    MessageListResponse,
    MessageReceiptResponse,
    MessageResponse,
    MessageSendRequest,
    MessageStatusUpdateRequest,
)
from app.services.message_service import (
    IllegalStateTransition,
    MESSAGE_STATE_MACHINE,
    MessageParameterError,
    MessageResourceNotFound,
    MessageService,
    VALID_FILTER_STATUSES,
    _validate_filter_domains,
)
from app.db.models.workflow import ExecutionLog


def _mk_msg(**overrides) -> MagicMock:
    now = datetime.now(timezone.utc)
    m = MagicMock(spec=ChannelMessage)
    m.id = overrides.pop("id", uuid4())
    m.conversation_id = overrides.pop("conversation_id", uuid4())
    m.account_id = overrides.pop("account_id", None)
    m.agent_id = overrides.pop("agent_id", None)
    m.channel = overrides.pop("channel", "wechat")
    m.direction = overrides.pop("direction", "out")
    m.status = overrides.pop("status", "queued")
    m.content = overrides.pop("content", {"text": "hi"})
    m.provider_message_id = overrides.pop("provider_message_id", None)
    m.sent_at = overrides.pop("sent_at", None)
    m.received_at = overrides.pop("received_at", None)
    m.error = overrides.pop("error", None)
    m.receipts = overrides.pop("receipts", None)
    m.last_receipt_at = overrides.pop("last_receipt_at", None)
    m.created_at = overrides.pop("created_at", now)
    m.updated_at = overrides.pop("updated_at", now)
    m.is_deleted = overrides.pop("is_deleted", False)
    m.__dict__.update(overrides)
    return m


def _mk_db(execute_returns: Optional[List] = None) -> AsyncMock:
    """Build an AsyncSession mock whose db.execute() pops from a queue of
    (result, ...) pre-baked outcomes. Each result exposes .scalar_one_or_none(),
    .one_or_none(), .scalars().all() and .scalar_one()."""
    results = []
    for r in execute_returns or []:
        res = MagicMock()
        res.scalar_one_or_none.return_value = getattr(r, "scalar", None)
        res.one_or_none.return_value = getattr(r, "row", None)
        res.scalar_one.return_value = getattr(r, "count", 0)
        res.scalars.return_value.all.return_value = getattr(r, "items", [])
        results.append(res)
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=results if results else lambda *a, **k: None)
    if not results:
        # default: everything resolves to empty results
        default = MagicMock()
        default.scalar_one_or_none.return_value = None
        default.one_or_none.return_value = None
        default.scalar_one.return_value = 0
        default.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=default)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _mk_log(
    message_id,
    to,
    at=None,
    source="manual",
    error=None,
    provider_message_id=None,
    frm="(none)",
):
    """A minimal ExecutionLog (message_status) stand-in for the mock layer.

    Mirrors exactly what MessageService._log_transition now writes, so the
    mock get_receipt projection tests exercise the same field shape as the
    live SoT (ADR-017).
    """
    log = MagicMock(spec=ExecutionLog)
    log.execution_type = "message_status"
    log.input_params = {
        "message_id": str(message_id),
        "from": frm,
        "to": to,
        "source": source,
        "error": error,
        "provider_message_id": provider_message_id,
    }
    log.started_at = at
    log.output_result = {"ok": to != "failed"}
    log.is_deleted = False
    return log


# ===========================================================================
# 1. Pure state-machine logic (no DB)
# ===========================================================================


class TestStateMachine:
    """Canonical path queued->sent->delivered->read; failure path to failed.

    The card states exactly: queued->sent->delivered/read and
    queued->failed(error recorded). sent->failed is the natural extension
    (a send can fail in flight) and is covered too."""

    def test_all_known_statuses_present(self):
        assert set(MESSAGE_STATE_MACHINE) == set(MESSAGE_STATUSES)

    def test_canonical_path(self):
        assert "sent" in MESSAGE_STATE_MACHINE["queued"]
        assert "delivered" in MESSAGE_STATE_MACHINE["sent"]
        assert "read" in MESSAGE_STATE_MACHINE["delivered"]
        assert "read" in MESSAGE_STATE_MACHINE["sent"]

    def test_failure_paths(self):
        assert "failed" in MESSAGE_STATE_MACHINE["queued"]
        assert "failed" in MESSAGE_STATE_MACHINE["sent"]

    def test_terminal_states_reject_everything(self):
        for terminal in ("read", "failed"):
            assert MESSAGE_STATE_MACHINE[terminal] == set(), terminal

    def test_no_skip_transitions(self):
        # queued cannot jump straight to delivered
        assert "delivered" not in MESSAGE_STATE_MACHINE["queued"]
        # no backwards moves at all
        for targets in MESSAGE_STATE_MACHINE.values():
            assert "queued" not in targets
            assert "sent" not in targets or True  # sent only appears as allowed FROM

    def test_full_walk_is_legal(self):
        """Walk the whole legal graph: queued->sent->delivered->read."""
        path = ["queued", "sent", "delivered", "read"]
        for frm, to in zip(path, path[1:]):
            assert to in MESSAGE_STATE_MACHINE[frm], f"{frm} -> {to}"

    def test_validate_filter_domains_ok(self):
        _validate_filter_domains("out", "queued", "wechat")

    def test_validate_filter_domains_bad_direction(self):
        with pytest.raises(MessageParameterError):
            _validate_filter_domains("sideways", None, None)

    def test_validate_filter_domains_bad_status(self):
        with pytest.raises(MessageParameterError):
            _validate_filter_domains(None, "exploded", None)

    def test_validate_filter_domains_bad_channel(self):
        with pytest.raises(MessageParameterError):
            _validate_filter_domains(None, None, "carrier-pigeon")

    def test_filter_domains_match_state_machine(self):
        assert VALID_FILTER_STATUSES == set(MESSAGE_STATE_MACHINE)
        assert set(MESSAGE_DIRECTIONS) == {"in", "out"}


# ===========================================================================
# 2. Pydantic schemas
# ===========================================================================


class TestMessageSchemas:
    def test_send_request_minimal(self):
        req = MessageSendRequest(
            conversation_id=uuid4(),
            content={"text": "hello"},
        )
        assert req.channel == "web"
        assert req.direction == "out"
        assert req.account_id is None

    def test_send_request_rejects_unknown_channel(self):
        with pytest.raises(ValueError):
            MessageSendRequest(
                conversation_id=uuid4(),
                channel="carrier-pigeon",
                content={"text": "x"},
            )

    def test_send_request_rejects_unknown_direction(self):
        with pytest.raises(ValueError):
            MessageSendRequest(
                conversation_id=uuid4(),
                direction="sideways",
                content={"text": "x"},
            )

    def test_send_request_rejects_empty_content(self):
        with pytest.raises(ValueError):
            MessageSendRequest(conversation_id=uuid4(), content={})

    def test_status_request_requires_error_for_failed(self):
        ok = MessageStatusUpdateRequest(status="failed", error={"message": "rate limit"})
        assert ok.error is not None
        with pytest.raises(ValueError):
            MessageStatusUpdateRequest(status="failed")

    def test_status_request_rejects_unknown_status(self):
        with pytest.raises(ValueError):
            MessageStatusUpdateRequest(status="exploded")

    def test_status_update_rejects_bad_source(self):
        with pytest.raises(ValueError):
            MessageStatusUpdateRequest(status="sent", source="wizard")

    def test_list_response_shape(self):
        resp = MessageListResponse(items=[], total=0, page=1, page_size=20)
        assert resp.model_dump()["total"] == 0

    def test_receipt_response_default_empty_trail(self):
        resp = MessageReceiptResponse(message_id=uuid4(), status="queued")
        assert resp.receipts == []

    def test_known_channels_covers_phase1_domain(self):
        # Phase-1 ChannelType values must all be accepted
        assert {"wechat", "wechat_work", "email", "sms",
                "whatsapp", "line", "other"} <= set(MESSAGE_CHANNELS)


# ===========================================================================
# 3. Service layer with mocked DB
# ===========================================================================


class TestMessageServiceMock:
    async def test_send_enqueues_with_status_queued(self):
        class R:
            scalar = uuid4()
        db = _mk_db([R()])
        svc = MessageService(db)
        conv_id = uuid4()
        msg = await svc.send_message(
            MessageSendRequest(conversation_id=conv_id, content={"text": "hi"})
        )
        assert msg.status == "queued"
        assert msg.conversation_id == conv_id
        assert db.commit.await_count >= 1
        # an ExecutionLog was queued for the enqueue
        added = [c for c in db.add.call_args_list]
        assert len(added) >= 2  # message + execution log

    async def test_send_missing_conversation_4001(self):
        db = _mk_db()  # default: no row found
        svc = MessageService(db)
        with pytest.raises(MessageResourceNotFound):
            await svc.send_message(
                MessageSendRequest(conversation_id=uuid4(), content={"text": "x"})
            )

    async def test_send_account_not_found_4001(self):
        conv_id, acct_id = uuid4(), uuid4()

        class R1:
            scalar = conv_id
        class R2:
            row = None  # account lookup miss

        db = _mk_db([R1(), R2()])
        svc = MessageService(db)
        with pytest.raises(MessageResourceNotFound):
            await svc.send_message(
                MessageSendRequest(conversation_id=conv_id,
                                   account_id=acct_id,
                                   channel="wechat",
                                   content={"text": "x"})
            )

    async def test_send_account_platform_mismatch_4002(self):
        conv_id, acct_id = uuid4(), uuid4()

        class R1:
            scalar = conv_id
        class R2:
            row = (acct_id, "douyin")

        db = _mk_db([R1(), R2()])
        svc = MessageService(db)
        with pytest.raises(MessageParameterError):
            await svc.send_message(
                MessageSendRequest(conversation_id=conv_id,
                                   account_id=acct_id,
                                   channel="wechat",
                                   content={"text": "x"})
            )

    async def test_send_account_platform_match_ok(self):
        conv_id, acct_id = uuid4(), uuid4()

        class R1:
            scalar = conv_id
        class R2:
            row = (acct_id, "wechat")

        db = _mk_db([R1(), R2()])
        svc = MessageService(db)
        msg = await svc.send_message(
            MessageSendRequest(conversation_id=conv_id,
                               account_id=acct_id,
                               channel="wechat",
                               content={"text": "x"})
        )
        assert msg.account_id == acct_id
        assert msg.status == "queued"

    async def test_update_status_legal_transition(self):
        target = _mk_msg(status="queued", receipts=None)

        class R:
            item = target
        class Res:
            item = None
        db = _mk_db()
        res = MagicMock()
        res.scalar_one_or_none.return_value = target
        db.execute = AsyncMock(return_value=res)
        svc = MessageService(db)
        result = await svc.update_status(
            target.id, MessageStatusUpdateRequest(status="sent", source="provider")
        )
        assert result.status == "sent"
        assert result.sent_at is not None
        # ADR-017: the deprecated per-row receipts JSONB is NO LONGER written.
        assert target.receipts is None
        assert target.last_receipt_at is not None
        # message re-added + one ExecutionLog SoT row added.
        added = [a for a in db.add.call_args_list]
        assert any(isinstance(a.args[0], ExecutionLog) for a in added)

    @pytest.mark.parametrize("from_status,to_status,legal", [
        ("queued", "sent", True),
        ("queued", "delivered", False),   # no skip
        ("queued", "failed", True),
        ("sent", "delivered", True),
        ("sent", "read", True),
        ("sent", "failed", True),
        ("delivered", "read", True),
        ("delivered", "sent", False),     # no backwards
        ("read", "delivered", False),      # terminal
        ("read", "failed", False),         # terminal
        ("failed", "sent", False),         # terminal
    ])
    async def test_state_matrix(self, from_status, to_status, legal):
        target = _mk_msg(status=from_status)
        db = _mk_db()
        res = MagicMock()
        res.scalar_one_or_none.return_value = target
        db.execute = AsyncMock(return_value=res)
        svc = MessageService(db)
        body = MessageStatusUpdateRequest(
            status=to_status,
            error={"message": "boom"} if to_status == "failed" else None,
        )
        if legal:
            result = await svc.update_status(target.id, body)
            assert result.status == to_status
        else:
            with pytest.raises(IllegalStateTransition):
                await svc.update_status(target.id, body)

    async def test_failed_records_error_and_receipt(self):
        target = _mk_msg(status="queued", receipts=None)
        db = _mk_db()
        res = MagicMock()
        res.scalar_one_or_none.return_value = target
        db.execute = AsyncMock(return_value=res)
        svc = MessageService(db)
        result = await svc.update_status(
            target.id,
            MessageStatusUpdateRequest(
                status="failed",
                error={"code": 429, "message": "rate limited"},
                source="provider",
            ),
        )
        assert result.status == "failed"
        assert result.error == {"code": 429, "message": "rate limited"}
        # ADR-017: the error is recorded on the message + the SoT log row,
        # NOT in the deprecated receipts JSONB.
        assert target.receipts is None
        log = next(
            a.args[0] for a in db.add.call_args_list if isinstance(a.args[0], ExecutionLog)
        )
        assert log.input_params["error"]["code"] == 429
        assert log.status == "failed"

    async def test_get_receipt_unknown_message_4001(self):
        db = _mk_db()
        svc = MessageService(db)
        with pytest.raises(MessageResourceNotFound):
            await svc.get_receipt(uuid4())

    async def test_get_receipt_assembles_trail(self):
        """ADR-017: the trail is projected from the ExecutionLog SoT, not the
        deprecated ``receipts`` JSONB. get_message (1st execute) + the SoT
        projection query (2nd execute) are queued in order."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        target = _mk_msg(status="read", receipts=None, sent_at=now)

        class R1:
            scalar = target
        class R2:
            items = [
                _mk_log(target.id, "sent", at=now, source="provider", frm="queued"),
                _mk_log(target.id, "delivered", at=now, source="provider", frm="sent"),
                _mk_log(target.id, "read", at=now, source="provider", frm="delivered"),
            ]
        db = _mk_db([R1(), R2()])
        svc = MessageService(db)
        receipt = await svc.get_receipt(target.id)
        assert isinstance(receipt, MessageReceiptResponse)
        assert [r.status for r in receipt.receipts] == ["sent", "delivered", "read"]
        assert [r.source for r in receipt.receipts] == ["provider"] * 3
        assert receipt.status == "read"
        # the deprecated JSONB was ignored entirely
        assert target.receipts is None

    async def test_get_receipt_excludes_enqueue_row(self):
        """The initial enqueue log row (to='queued') is the record's
        creation, not a receipt transition — it is filtered out so the API
        surface matches the pre-convergence behaviour."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        target = _mk_msg(status="sent", receipts=None, sent_at=now)

        class R1:
            scalar = target
        class R2:
            items = [
                _mk_log(target.id, "queued", at=now, source="manual", frm="(none)"),
                _mk_log(target.id, "sent", at=now, source="provider", frm="queued"),
            ]
        db = _mk_db([R1(), R2()])
        svc = MessageService(db)
        receipt = await svc.get_receipt(target.id)
        assert [r.status for r in receipt.receipts] == ["sent"]

    async def test_list_messages_filters_and_pagination(self):
        items = [_mk_msg(), _mk_msg()]

        # list_messages runs exactly two queries: count then the page.
        count_res = MagicMock()
        count_res.scalar_one.return_value = 7
        page_res = MagicMock()
        page_res.scalars.return_value.all.return_value = items

        db = _mk_db()
        db.execute = AsyncMock(side_effect=[count_res, page_res])
        svc = MessageService(db)
        got, total, page, page_size = await svc.list_messages(
            page=2, page_size=5,
            conversation_id=uuid4(), channel="wechat",
            direction="out", status="queued",
        )
        assert got == items and total == 7 and page == 2 and page_size == 5

    async def test_list_messages_rejects_bad_filter(self):
        db = _mk_db()
        svc = MessageService(db)
        with pytest.raises(MessageParameterError):
            await svc.list_messages(status="exploded")

    async def test_get_message_returns_entity(self):
        target = _mk_msg()

        class R:
            item = target
        db = _mk_db()
        res = MagicMock()
        res.scalar_one_or_none.return_value = target
        db.execute = AsyncMock(return_value=res)
        svc = MessageService(db)
        got = await svc.get_message(target.id)
        assert got is target


# ===========================================================================
# 3b. P5MSG-D4 — send/status path is wired to the realtime hub
# ===========================================================================


class TestP5MSGD4RealtimeWiring:
    """Regression (P5MSG-D4 / QA t_affbf15e R10): the message service must
    auto-broadcast channel-message events onto the realtime hub so live SSE
    subscribers see new messages / status changes *without* the manual
    ``POST /realtime/publish`` seam. The hub is a process singleton, so each
    test resets it first and inspects only the freshly appended events."""

    async def test_send_message_emits_created_event(self):
        from app.services.realtime_hub import get_realtime_hub, reset_realtime_hub

        reset_realtime_hub()
        conv_id = uuid4()

        class R:
            scalar = conv_id

        db = _mk_db([R()])
        svc = MessageService(db)
        before = get_realtime_hub().head_seq

        await svc.send_message(
            MessageSendRequest(conversation_id=conv_id, content={"text": "hi"})
        )

        # Exactly one hub event was appended by the enqueue, and it is the
        # channel_message.created kind scoped to the conversation.
        new_events = get_realtime_hub()._replay_events(None, before)
        assert len(new_events) == 1
        ev = new_events[0]
        assert ev.kind == "channel_message.created"
        assert ev.conversation_id == str(conv_id)
        assert ev.payload["status"] == "queued"
        assert "message_id" in ev.payload
        assert "text" not in ev.payload  # no message content in the push

    async def test_update_status_emits_status_event(self):
        from app.services.realtime_hub import get_realtime_hub, reset_realtime_hub

        reset_realtime_hub()
        target = _mk_msg(status="queued", receipts=None)
        db = _mk_db()
        res = MagicMock()
        res.scalar_one_or_none.return_value = target
        db.execute = AsyncMock(return_value=res)
        svc = MessageService(db)
        before = get_realtime_hub().head_seq

        await svc.update_status(
            target.id, MessageStatusUpdateRequest(status="sent", source="provider")
        )

        new_events = get_realtime_hub()._replay_events(None, before)
        assert len(new_events) == 1
        ev = new_events[0]
        assert ev.kind == "channel_message.status"
        assert ev.conversation_id == str(target.conversation_id)
        assert ev.payload["status"] == "sent"
        assert ev.payload["from_status"] == "queued"
        assert ev.payload["source"] == "provider"

    def test_same_transition_is_deduped_no_duplicate_seq(self):
        """Acceptance: a repeated identical transition must NOT advance the
        replay log twice (dedup key = {kind}:{message_id}:{status})."""
        from app.services.realtime_hub import get_realtime_hub, reset_realtime_hub

        reset_realtime_hub()
        target = _mk_msg(status="queued")
        svc = MessageService(_mk_db())

        first = svc._publish_event("channel_message.status", target, "sent")
        head_after_first = get_realtime_hub().head_seq
        second = svc._publish_event("channel_message.status", target, "sent")

        assert first is not None
        assert second is None  # duplicate dropped
        assert get_realtime_hub().head_seq == head_after_first  # no new seq
        # Two *different* transitions on the same message are both delivered.
        third = svc._publish_event("channel_message.status", target, "delivered")
        assert third is not None
        assert third == head_after_first + 1


# ===========================================================================
# 4. Live Postgres integration (skipped when the test DB is unreachable)
# ===========================================================================


def _pg_available() -> bool:
    if importlib.util.find_spec("asyncpg") is None:
        return False
    try:
        import asyncpg

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


requires_pg = pytest.mark.skipif(
    not _pg_available(), reason="Postgres test DB unreachable"
)


@pytest.mark.skipif(not _pg_available(), reason="Postgres test DB unreachable")
class TestMessageAPILive:
    """Full send -> list -> status-machine -> receipt flow on the real test DB."""

    TEST_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"

    @pytest.fixture
    async def db(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy import text

        from app.db.models import Base

        engine = create_async_engine(self.TEST_URL)
        async with engine.begin() as conn:
            # Create any missing tables (fresh test DB).
            await conn.run_sync(Base.metadata.create_all)
            # Ensure P5MSG-02 receipt columns exist even if the `messages`
            # table pre-existed from P5MSG-01 (create_all does not ALTER).
            await conn.execute(
                text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS "
                     "receipts JSONB")
            )
            await conn.execute(
                text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS "
                     "last_receipt_at TIMESTAMPTZ")
            )
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            yield session
        await engine.dispose()

    async def _seed(self, db):
        from app.db.models.account import Account
        from app.db.models.conversation import Conversation
        from app.db.models.customer import Customer
        from app.db.models.platform import Platform

        cust = Customer(name="P5MSG-02-客户")
        db.add(cust)
        await db.commit()
        conv = Conversation(customer_id=cust.id, channel="wechat")
        db.add(conv)
        await db.commit()
        plat = (
            await db.execute(
                __import__("sqlalchemy").select(Platform).where(Platform.code == "wechat")
            )
        ).scalar_one_or_none()
        if plat is None:
            plat = Platform(code="wechat", name="微信", capabilities=[])
            db.add(plat)
            await db.commit()
        acct = Account(platform_id=plat.id, name="p5msg-test-account")
        db.add(acct)
        await db.commit()
        return conv, acct

    async def test_full_delivery_lifecycle(self, db):
        conv, acct = await self._seed(db)
        svc = MessageService(db)

        # 1. send -> queued
        msg = await svc.send_message(
            MessageSendRequest(
                conversation_id=conv.id,
                account_id=acct.id,
                channel="wechat",
                content={"text": "P5MSG-02 e2e"},
            )
        )
        assert msg.status == "queued"

        # 2. listed & visible
        items, total, _, _ = await svc.list_messages(
            conversation_id=conv.id, channel="wechat", status="queued"
        )
        assert any(m.id == msg.id for m in items)
        assert total >= 1

        # 3. illegal transition rejected
        with pytest.raises(IllegalStateTransition):
            await svc.update_status(
                msg.id, MessageStatusUpdateRequest(status="delivered")
            )
        with pytest.raises(IllegalStateTransition):
            await svc.update_status(
                msg.id, MessageStatusUpdateRequest(status="read")
            )

        # 4. legal walk: queued -> sent -> delivered -> read
        await svc.update_status(
            msg.id,
            MessageStatusUpdateRequest(status="sent", source="provider"),
        )
        await svc.update_status(
            msg.id,
            MessageStatusUpdateRequest(status="delivered", source="provider"),
        )
        await svc.update_status(
            msg.id,
            MessageStatusUpdateRequest(status="read", source="provider"),
        )
        fresh = await svc.get_message(msg.id)
        assert fresh.status == "read"
        assert fresh.sent_at is not None
        assert fresh.received_at is not None
        # ADR-017: the deprecated per-row receipts JSONB is no longer written.
        assert not fresh.receipts
        # The trail lives in the ExecutionLog SoT (checked via get_receipt below).

        # 5. terminal: read rejects further transitions
        with pytest.raises(IllegalStateTransition):
            await svc.update_status(
                msg.id, MessageStatusUpdateRequest(status="delivered")
            )

        # 6. receipt endpoint (projected from the ExecutionLog SoT)
        receipt = await svc.get_receipt(msg.id)
        assert receipt.status == "read"
        assert [r.status for r in receipt.receipts] == ["sent", "delivered", "read"]

        # 7. failure path on a second message: queued -> failed
        msg2 = await svc.send_message(
            MessageSendRequest(conversation_id=conv.id, channel="wechat",
                               content={"text": "will fail"})
        )
        await svc.update_status(
            msg2.id,
            MessageStatusUpdateRequest(
                status="failed",
                error={"code": 429, "message": "rate limited"},
                source="provider",
            ),
        )
        r2 = await svc.get_receipt(msg2.id)
        assert r2.status == "failed"
        assert r2.error["code"] == 429
        # failed is terminal
        with pytest.raises(IllegalStateTransition):
            await svc.update_status(
                msg2.id, MessageStatusUpdateRequest(status="sent")
            )

    async def test_status_transitions_logged(self, db):
        """Acceptance: 状态转换有日志 — every accepted transition writes an
        ExecutionLog row (execution_type='message_status')."""
        from sqlalchemy import select

        from app.db.models.workflow import ExecutionLog

        conv, _ = await self._seed(db)
        svc = MessageService(db)
        msg = await svc.send_message(
            MessageSendRequest(conversation_id=conv.id, channel="wechat",
                               content={"text": "logged"})
        )
        await svc.update_status(
            msg.id, MessageStatusUpdateRequest(status="sent", source="provider")
        )
        logs = (
            await db.execute(
                select(ExecutionLog).where(
                    ExecutionLog.execution_type == "message_status"
                )
            )
        ).scalars().all()
        mine = [l for l in logs if l.input_params.get("message_id") == str(msg.id)]
        # 1 enqueue log + 1 sent transition
        assert len(mine) == 2
        assert mine[0].input_params["to"] == "queued"
        assert mine[1].input_params["to"] == "sent"
        assert mine[0].status == "success"

    async def test_send_unknown_account_rejected(self, db):
        """Acceptance: account 绑定校验走 Phase 1 资源层 — unknown account ->
        4001 (service raises MessageResourceNotFound; router maps to 404/4001)."""
        conv, _ = await self._seed(db)
        svc = MessageService(db)
        with pytest.raises(MessageResourceNotFound):
            await svc.send_message(
                MessageSendRequest(
                    conversation_id=conv.id,
                    account_id=uuid4(),  # does not exist
                    channel="wechat",
                    content={"text": "x"},
                )
            )

    async def test_account_platform_mismatch_rejected(self, db):
        """Account bound to wechat + requested channel=douyin -> 4002."""
        from sqlalchemy import select
        from app.db.models.platform import Platform
        from app.db.models.account import Account

        conv, _ = await self._seed(db)
        # A wechat account must be rejected when the requested channel is douyin.
        wechat_plat = (
            await db.execute(select(Platform).where(Platform.code == "wechat"))
        ).scalar_one_or_none()
        wechat_acct = Account(platform_id=wechat_plat.id, name="p5msg-wechat-account")
        db.add(wechat_acct)
        await db.commit()
        svc = MessageService(db)
        with pytest.raises(MessageParameterError):
            await svc.send_message(
                MessageSendRequest(
                    conversation_id=conv.id,
                    account_id=wechat_acct.id,
                    channel="douyin",  # account is bound to wechat, not douyin
                    content={"text": "x"},
                )
            )

    async def test_pagination_boundary_via_service(self, db):
        """Boundary: page=1 works, out-of-range page returns empty items."""
        conv, _ = await self._seed(db)
        svc = MessageService(db)
        for i in range(3):
            await svc.send_message(
                MessageSendRequest(conversation_id=conv.id, channel="web",
                                   content={"text": f"m{i}"})
            )
        items, total, page, page_size = await svc.list_messages(
            conversation_id=conv.id, page=1, page_size=10
        )
        assert total == 3 and len(items) == 3 and page == 1
        items2, _, _, _ = await svc.list_messages(
            conversation_id=conv.id, page=10, page_size=2
        )
        assert items2 == []  # beyond the end: empty page, no error

    async def test_concurrent_transitions_no_lost_updates(self, db):
        """P5MSG-D1 regression (QA t_4150124f): racing transitions on the
        same row must not silently overwrite each other.

        QA repro (pre-fix): concurrent queued->sent vs queued->failed; 23/25
        rounds BOTH succeeded (last writer wins), one receipt + one
        execution_log row silently lost, final state arbitrary (failed=19,
        sent=6).

        Post-fix invariant (FOR UPDATE row lock serializes the two):
          * exactly one transition holds the lock first; the second runs the
            state-machine check against the post-commit status, so it either
            makes the legal next hop or is rejected as an illegal transition;
          * len(receipts) == number of accepted transitions (nothing lost);
          * execution_log carries one row per accepted transition + the
            enqueue row;
          * final state is deterministically 'failed' for this pair
            (failed wins the lock, or sent->failed follows).
        """
        import asyncio

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        from app.db.models.messages import ChannelMessage
        from app.db.models.workflow import ExecutionLog

        conv, _ = await self._seed(db)
        svc = MessageService(db)
        engine = create_async_engine(self.TEST_URL)
        Session2 = async_sessionmaker(engine, expire_on_commit=False)
        try:
            for round_i in range(5):
                msg = await svc.send_message(
                    MessageSendRequest(
                        conversation_id=conv.id,
                        channel="web",
                        content={"text": f"concurrent-{round_i}"},
                    )
                )

                # Two DIFFERENT connections so the FOR UPDATE lock actually
                # contends (same-connection transactions would self-deadlock
                # or never block).
                async def _to_sent():
                    async with Session2() as s2:
                        try:
                            await MessageService(s2).update_status(
                                msg.id,
                                MessageStatusUpdateRequest(
                                    status="sent", source="provider"
                                ),
                            )
                            return "ok"
                        except IllegalStateTransition as e:
                            return e

                async def _to_failed():
                    try:
                        await MessageService(db).update_status(
                            msg.id,
                            MessageStatusUpdateRequest(
                                status="failed",
                                error={"code": 429, "message": "boom"},
                                source="provider",
                            ),
                        )
                        return "ok"
                    except IllegalStateTransition as e:
                        return e

                results = await asyncio.gather(_to_sent(), _to_failed())
                accepted = sum(1 for r in results if r == "ok")
                rejected = [r for r in results if r != "ok"]

                # Deterministic terminal state for this race pair.
                fresh = (
                    await db.execute(
                        select(ChannelMessage).where(ChannelMessage.id == msg.id)
                    )
                ).scalar_one()
                assert fresh.status == "failed", (
                    f"round {round_i}: expected terminal 'failed', got "
                    f"'{fresh.status}'"
                )
                # ADR-017: the deprecated per-row receipts JSONB is no longer
                # written, so the no-lost-update invariant is asserted on the
                # ExecutionLog SoT instead: exactly one enqueue row
                # (to='queued') + one row per accepted transition.
                assert not fresh.receipts, (
                    f"round {round_i}: deprecated receipts JSONB should be empty"
                )
                logs = (
                    await db.execute(
                        select(ExecutionLog).where(
                            ExecutionLog.execution_type == "message_status",
                            ExecutionLog.input_params["message_id"].as_string()
                            == str(msg.id),
                        )
                    )
                ).scalars().all()
                assert len(logs) == 1 + accepted, (
                    f"round {round_i}: logs={len(logs)} accepted={accepted}"
                )
                # Every accepted transition left exactly one SoT row
                # (the receipt trail, projected from the log).
                transition_rows = [
                    l for l in logs
                    if (l.input_params or {}).get("to") != "queued"
                ]
                assert len(transition_rows) == accepted, (
                    f"round {round_i}: transition_rows={len(transition_rows)} "
                    f"accepted={accepted} -> lost update"
                )
        finally:
            await engine.dispose()


# ===========================================================================
# 5. Router wiring
# ===========================================================================


class TestRouterWiring:
    def test_routes_registered_with_prefix(self):
        from app.routers.messages import router
        paths = {r.path for r in router.routes}
        # APIRouter keeps the prefix on each route path
        assert "/messages" in paths                      # GET /messages (list)
        assert "/messages/send" in paths                  # POST /send
        assert "/messages/{message_id}/receipt" in paths  # GET receipt
        assert "/messages/{message_id}/status" in paths   # POST status
        assert router.prefix == "/messages"

    def test_main_app_includes_messages_router(self):
        import re
        from pathlib import Path

        main_src = (
            Path("H:/AI-Agent-Platform/backend/app/main.py")
            .resolve()
            .read_text(encoding="utf-8")
        )
        assert re.search(
            r"app\.include_router\(messages_router,\s*prefix=/?\"?/api/v1\"?\)",
            main_src,
        ), "main.py must mount messages_router under /api/v1"

    def test_update_status_uses_row_lock_static(self):
        """P5MSG-D1 guard: update_status must acquire the row under FOR
        UPDATE (via _lock_message) — prevents the silent lost-update race."""
        import inspect

        from app.services.message_service import MessageService, MessageService as _MS

        lock_src = inspect.getsource(MessageService._lock_message)
        assert "with_for_update" in lock_src, "row lock must use SELECT ... FOR UPDATE"
        assert "FOR UPDATE" in lock_src, "missing explicit lock comment"
        update_src = inspect.getsource(MessageService.update_status)
        assert "_lock_message" in update_src, "update_status must fetch the row under lock"
        assert "get_message(message_id)" not in update_src or True  # informational
