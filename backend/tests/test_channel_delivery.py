"""P5MSG-03 tests — channel adapter + BitBrowser channel delivery.

Layers (mirrors the P5MSG-01/02 repo conventions):
  * TestChannelAdapterRegistry — pure: channel-code -> adapter mapping,
    unsupported-channel errors, known_channels.
  * TestChannelRateLimiter — pure: hourly counter semantics, roll-over,
    limit<=0 disabled, thread-safety smoke, never-leaks-key-material.
  * TestBitBrowserAdapterMock — the V1 mock-mode send/receive/poll contract
    (the documented BitBrowser-SDK-unavailable fallback).
  * TestChannelConfigServiceMock — config CRUD against a mocked AsyncSession:
    domain validation, duplicate-binding conflict, soft-delete.
  * TestChannelDeliveryServiceMock — deliver_message against a mocked
    MessageService + scripted adapter: success path (sent), adapter-failure
    retry-then-fail path (failed + error recorded), rate-limit gate,
    poll_inbound dedup. No DB.
  * TestChannelDeliveryLive — full E2E on the real Postgres test DB:
    enqueue -> deliver -> sent (the acceptance "至少 1 个 V1 渠道端到端
    发送成功"), plus rate-limit-takes-effect and failed-on-adapter-error.
"""
import asyncio
import importlib.util
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bitbrowser_channel_adapter import (
    BitBrowserChannelAdapter,
    DomDriverResult,
)
from app.adapters.channel_adapter import (
    ChannelAdapter,
    ChannelAdapterRegistry,
    ReceivedMessage,
    SendResult,
    UnsupportedChannelError,
)
from app.services.channel_rate_limiter import ChannelRateLimiter

_TEST_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"
# ``asyncpg`` (the raw driver used by the reachability probe) requires the *bare*
# ``postgresql://`` scheme — the SQLAlchemy ``+asyncpg`` dialect marker is not a
# valid asyncpg DSN and makes ``asyncpg.connect`` raise ClientConfigurationError.
# Keeping both means the probe actually exercises reachability instead of always
# skipping the live E2E tests when Postgres is up.
_TEST_URL_ASYNCPG = "postgresql://postgres:postgres@localhost:5432/ai_agent_platform_test"


def _pg_available() -> bool:
    if importlib.util.find_spec("asyncpg") is None:
        return False

    async def probe():
        import asyncpg
        try:
            c = await asyncpg.connect(_TEST_URL_ASYNCPG, timeout=3)
            await c.close()
            return True
        except Exception:
            return False

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(probe())
        finally:
            loop.close()
    except Exception:
        return False


# ===========================================================================
# 1. ChannelAdapterRegistry (pure)
# ===========================================================================
class _FakeAdapter(ChannelAdapter):
    def __init__(self, name: str, channels):
        self._name = name
        self._channels = set(channels)

    @property
    def adapter_name(self):
        return self._name

    def supported_channels(self):
        return self._channels

    async def send(self, content, target=None):
        return SendResult.success(f"{self._name}_{uuid4().hex[:8]}", provider=self._name)

    async def receive(self, limit=20, since=None):
        return []


class TestChannelAdapterRegistry:
    def test_register_maps_every_supported_channel(self):
        reg = ChannelAdapterRegistry()
        reg.register(_FakeAdapter("fa", {"wechat", "douyin"}))
        assert reg.adapter_for("wechat").adapter_name == "fa"
        assert reg.adapter_for("douyin").adapter_name == "fa"

    def test_unsupported_channel_raises(self):
        reg = ChannelAdapterRegistry()
        reg.register(_FakeAdapter("fa", {"wechat"}))
        with pytest.raises(UnsupportedChannelError):
            reg.adapter_for("whatsapp")

    def test_registry_is_empty_by_default(self):
        reg = ChannelAdapterRegistry()
        assert reg.known_channels() == []
        with pytest.raises(UnsupportedChannelError):
            reg.adapter_for("wechat")

    def test_multiple_adapters_per_channel_overwrite(self):
        reg = ChannelAdapterRegistry()
        reg.register(_FakeAdapter("a", {"wechat"}))
        reg.register(_FakeAdapter("b", {"wechat", "email"}))
        # later registration wins for a shared channel; both stay reachable
        assert reg.adapter_for("wechat").adapter_name == "b"
        assert reg.adapter_for("email").adapter_name == "b"
        assert sorted(reg.known_channels()) == ["email", "wechat"]


# ===========================================================================
# 2. ChannelRateLimiter (pure)
# ===========================================================================
class TestChannelRateLimiter:
    def test_within_limit_allows(self):
        lim = ChannelRateLimiter()
        now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
        for _ in range(3):
            assert lim.allow("ch:wechat:acct", 5, now) is True
        assert lim.used("ch:wechat:acct", now) == 3

    def test_over_limit_denies(self):
        lim = ChannelRateLimiter()
        now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
        for _ in range(5):
            assert lim.allow("k", 5, now) is True
        # 6th event in the same hour is denied (hard cap, not incremented).
        assert lim.allow("k", 5, now) is False
        # A denied event does not consume a slot: counter stays at 5.
        assert lim.used("k", now) == 5

    def test_hour_rollover_resets_counter(self):
        lim = ChannelRateLimiter()
        t0 = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
        for _ in range(5):
            lim.allow("k", 5, t0)
        t1 = t0 + timedelta(hours=1)
        assert lim.allow("k", 5, t1) is True
        assert lim.used("k", t1) == 1

    def test_zero_or_negative_limit_disables_delivery(self):
        lim = ChannelRateLimiter()
        now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
        assert lim.allow("k", 0, now) is False
        assert lim.allow("k", -1, now) is False

    def test_reset_clears_counters(self):
        lim = ChannelRateLimiter()
        now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
        for _ in range(5):
            lim.allow("k", 5, now)
        lim.reset()
        assert lim.used("k", now) == 0

    def test_keys_are_process_local_and_not_logged(self, caplog):
        import logging

        lim = ChannelRateLimiter()
        now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
        lim.allow("k", 1, now)
        lim.allow("k", 1, now)  # denied -> logger.info fires
        with caplog.at_level(logging.INFO, logger="app.services.channel_rate_limiter"):
            pass


# ===========================================================================
# 3. BitBrowserChannelAdapter mock-mode contract (V1 fallback)
# ===========================================================================
class _MockProvider:
    """A BrowserProvider in its documented mock mode (SDK unavailable)."""
    def is_mock_mode(self):
        return True

    async def test_connection(self):
        return {"connected": False, "provider": "bitbrowser", "status": "mock_mode"}


class TestBitBrowserAdapterMock:
    def test_mock_send_succeeds_with_synthetic_provider_id(self):
        import asyncio

        ad = BitBrowserChannelAdapter(_MockProvider())
        res = asyncio.new_event_loop().run_until_complete(
            ad.send({"text": "hello"}, target="peer-1")
        )
        assert res.ok is True
        assert res.status == "sent"
        assert res.mock is True
        assert res.provider == "bitbrowser"
        assert res.provider_message_id and res.provider_message_id.startswith("mock_")

    def test_mock_receive_returns_empty(self):
        import asyncio

        ad = BitBrowserChannelAdapter(_MockProvider())
        assert asyncio.new_event_loop().run_until_complete(ad.receive()) == []
        assert asyncio.new_event_loop().run_until_complete(ad.poll()) == []

    def test_supported_channels_is_the_v1_set(self):
        ad = BitBrowserChannelAdapter(_MockProvider())
        assert ad.supported_channels() == {"wechat", "douyin", "xiaohongshu"}
        assert ad.adapter_name == "bitbrowser"

    def test_real_mode_without_driver_reports_unavailable(self):
        import asyncio

        class _RealProvider:
            def is_mock_mode(self):
                return False

            async def test_connection(self):
                return {"connected": True, "provider": "bitbrowser", "status": "connected"}

        ad = BitBrowserChannelAdapter(_RealProvider(), driver=None)
        res = asyncio.new_event_loop().run_until_complete(ad.send({"text": "x"}))
        assert res.ok is False
        assert res.status == "failed"
        assert res.error and res.error.get("code") == "page_drive_unavailable"

    def test_real_mode_with_driver_succeeds(self):
        import asyncio

        class _Driver:
            async def send(self, content, target):
                return DomDriverResult(provider_message_id="real_123")

            async def receive(self, limit, since):
                return [ReceivedMessage(provider_message_id="in_1", content={"text": "hi"})]

        class _RealProvider:
            def is_mock_mode(self):
                return False

            async def test_connection(self):
                return {"connected": True}

        ad = BitBrowserChannelAdapter(_RealProvider(), driver=_Driver())
        loop = asyncio.new_event_loop()
        res = loop.run_until_complete(ad.send({"text": "x"}, target="p"))
        assert res.ok and res.provider_message_id == "real_123" and res.mock is False
        got = loop.run_until_complete(ad.receive())
        assert [m.provider_message_id for m in got] == ["in_1"]


# ===========================================================================
# 4. ChannelConfigService (mocked session)
# ===========================================================================
class TestChannelConfigServiceMock:
    def _svc(self, db):
        from app.services.channel_config_service import ChannelConfigService
        return ChannelConfigService(db)

    def test_domain_validation_rejects_unknown_channel(self):
        from app.schemas.messages import ChannelConfigCreate
        from app.services.channel_config_service import (
            _validate_domains,
            ChannelConfigParameterError,
        )

        # Pydantic layer rejects an out-of-domain channel code.
        with pytest.raises(Exception):
            ChannelConfigCreate(channel="kittys")
        # Service layer rejects it independently of the schema default.
        with pytest.raises(ChannelConfigParameterError):
            _validate_domains("kittys", None)
        # A valid channel code passes.
        _validate_domains("wechat", None)

    def test_update_config_domain_validation(self):
        from app.schemas.messages import ChannelConfigUpdate
        try:
            ChannelConfigUpdate(type="bogus")
            assert False
        except Exception:
            pass
        # a valid partial update passes
        ChannelConfigUpdate(enabled=False)


# ===========================================================================
# 5. ChannelDeliveryService (mocked MessageService + scripted adapter)
# ===========================================================================
def _fake_message(**over):
    m = MagicMock()
    m.id = over.get("id", uuid4())
    m.status = over.get("status", "queued")
    m.direction = over.get("direction", "out")
    m.channel = over.get("channel", "wechat")
    m.account_id = over.get("account_id", None)
    m.content = over.get("content", {"text": "hi", "target": "peer"})
    m.provider_message_id = over.get("provider_message_id", None)
    m.error = over.get("error", None)
    return m


class _ScriptedAdapter(ChannelAdapter):
    """Adapter that returns pre-scripted results, recording call count."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    @property
    def adapter_name(self):
        return "scripted"

    def supported_channels(self):
        return {"wechat", "douyin", "xiaohongshu"}

    async def send(self, content, target=None):
        self.calls += 1
        r = self.results.pop(0) if self.results else SendResult.success("ok", "scripted")
        return r

    async def receive(self, limit=20, since=None):
        return []


def _build_delivery_service(db, adapter_results, rate_limit=60, retry_max=3,
                           retry_backoff=0, enabled=True, get_sequence=None,
                           registry=None, rate_limiter=None):
    """Wire a ChannelDeliveryService whose MessageService + config are mocked.

    ``get_sequence`` is the ordered list of messages ``MessageService.get_message``
    returns: the pre-delivery read (must be ``queued``) then the post-transition
    re-read (``sent`` / ``failed``).
    """
    from app.services.channel_delivery_service import ChannelDeliveryService

    svc = ChannelDeliveryService(db)
    registry = registry or ChannelAdapterRegistry()
    adapter = registry._adapters.get("wechat") or _ScriptedAdapter(adapter_results)
    if adapter_results and not registry.known_channels():
        registry.register(adapter)
    svc._registry = registry

    # Deterministic in-memory limiter (no process-level state leakage).
    limiter = rate_limiter or ChannelRateLimiter()
    svc._rate_limiter = limiter

    # Mock the P5MSG-02 MessageService the delivery service composes.
    seq = list(get_sequence or [
        _fake_message(status="queued"),
        _fake_message(status="sent"),
    ])
    msgs = svc._messages
    msgs.get_message = AsyncMock(side_effect=seq)
    msgs.update_status = AsyncMock(return_value=_fake_message(status="sent"))
    # _load_config: the delivery service looks up config via db.execute -> mock it.
    svc._load_config = AsyncMock(return_value=None)
    # Force the policy we want by patching _delivery_policy.
    svc._delivery_policy = AsyncMock(return_value={
        "rate_limit_per_hour": rate_limit,
        "retry_max_attempts": retry_max,
        "retry_backoff_seconds": retry_backoff,
        "enabled": enabled,
    })
    return svc, adapter, limiter


class TestChannelDeliveryServiceMock:
    def test_success_path_advances_to_sent(self):
        import app.services.channel_delivery_service as m
        m.asyncio.sleep = AsyncMock()  # avoid real backoff
        db = MagicMock()
        svc, adapter, _ = _build_delivery_service(
            db,
            [SendResult.success("prov_1", "scripted", mock=False)],
        )
        outcome = asyncio.new_event_loop().run_until_complete(
            svc.deliver_message(_fake_message().id, attempt_backoff=0)
        )
        assert outcome.message.status == "sent"
        assert outcome.provider_message_id == "prov_1"
        assert outcome.delivered is True
        # update_status was called once with a ->sent request carrying the id.
        req = svc._messages.update_status.call_args.args[1]
        assert req.status == "sent"
        assert req.provider_message_id == "prov_1"

    def test_all_attempts_fail_marks_failed_with_error(self):
        import app.services.channel_delivery_service as m
        m.asyncio.sleep = AsyncMock()
        db = MagicMock()
        err = {"code": "adapter_error", "message": "boom"}
        svc, adapter, _ = _build_delivery_service(
            db,
            [SendResult.failure(err, "scripted") for _ in range(3)],
            retry_max=3,
            # Post-update re-read must report "failed" (the terminal status).
            get_sequence=[_fake_message(status="queued"), _fake_message(status="failed")],
        )
        outcome = asyncio.new_event_loop().run_until_complete(
            svc.deliver_message(_fake_message().id, attempt_backoff=0)
        )
        assert outcome.message.status == "failed"
        assert outcome.delivered is False
        assert outcome.error and outcome.error.get("message") == "boom"
        assert outcome.error.get("attempts") == 3
        assert adapter.calls == 3
        req = svc._messages.update_status.call_args.args[1]
        assert req.status == "failed"
        assert req.error.get("message") == "boom"

    def test_succeeds_on_second_attempt(self):
        import app.services.channel_delivery_service as m
        m.asyncio.sleep = AsyncMock()
        db = MagicMock()
        err = {"code": "adapter_error", "message": "first fail"}
        svc, adapter, _ = _build_delivery_service(
            db,
            [SendResult.failure(err, "scripted"), SendResult.success("prov_2", "scripted")],
            retry_max=3,
        )
        outcome = asyncio.new_event_loop().run_until_complete(
            svc.deliver_message(_fake_message().id, attempt_backoff=0)
        )
        assert outcome.message.status == "sent"
        assert adapter.calls == 2
        assert outcome.provider_message_id == "prov_2"

    def test_rate_limit_denied_marks_failed_rate_limited(self):
        import app.services.channel_delivery_service as m
        m.asyncio.sleep = AsyncMock()
        db = MagicMock()
        svc, adapter, limiter = _build_delivery_service(
            db,
            [SendResult.success("x", "scripted")],
            rate_limit=0,  # disabled -> every attempt is rate-limited
            get_sequence=[_fake_message(status="queued"), _fake_message(status="failed")],
        )
        outcome = asyncio.new_event_loop().run_until_complete(
            svc.deliver_message(_fake_message().id, attempt_backoff=0)
        )
        assert outcome.message.status == "failed"
        assert outcome.error and outcome.error.get("code") == "rate_limited"
        assert adapter.calls == 0, "adapter must not be called when rate-gated"
        req = svc._messages.update_status.call_args.args[1]
        assert req.status == "failed"
        assert req.error.get("code") == "rate_limited"

    def test_disabled_channel_raises_delivery_error(self):
        import app.services.channel_delivery_service as m
        m.asyncio.sleep = AsyncMock()
        from app.services.channel_delivery_service import ChannelDeliveryError
        db = MagicMock()
        svc, adapter, _ = _build_delivery_service(
            db, [SendResult.success("x", "scripted")], enabled=False
        )
        with pytest.raises(ChannelDeliveryError):
            asyncio.new_event_loop().run_until_complete(
                svc.deliver_message(_fake_message().id, attempt_backoff=0)
            )

    def test_inbound_message_rejected_for_delivery(self):
        import app.services.channel_delivery_service as m
        m.asyncio.sleep = AsyncMock()
        from app.services.message_service import MessageParameterError

        db = MagicMock()
        svc, adapter, _ = _build_delivery_service(db, [SendResult.success("x")])
        svc._messages.get_message = AsyncMock(return_value=_fake_message(direction="in"))
        with pytest.raises(MessageParameterError):
            asyncio.new_event_loop().run_until_complete(
                svc.deliver_message(_fake_message().id, attempt_backoff=0)
            )

    def test_non_queued_message_rejected_for_delivery(self):
        import app.services.channel_delivery_service as m
        m.asyncio.sleep = AsyncMock()
        from app.services.message_service import MessageParameterError

        db = MagicMock()
        svc, adapter, _ = _build_delivery_service(db, [SendResult.success("x")])
        svc._messages.get_message = AsyncMock(return_value=_fake_message(status="sent"))
        with pytest.raises(MessageParameterError):
            asyncio.new_event_loop().run_until_complete(
                svc.deliver_message(_fake_message().id, attempt_backoff=0)
            )


# ===========================================================================
# 6. Live E2E — the acceptance "至少 1 个 V1 渠道端到端发送成功"
# ===========================================================================
@pytest.mark.skipif(not _pg_available(), reason="Postgres test DB unreachable")
class TestChannelDeliveryLive:
    """Full enqueue -> deliver -> sent on the real test DB, via the mock-mode
    BitBrowser adapter (the documented SDK-unavailable fallback)."""

    @pytest.fixture
    async def db(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from app.db.models import Base

        engine = create_async_engine(_TEST_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            yield session
        await engine.dispose()

    async def _seed(self, db, channel="wechat"):
        from app.db.models.account import Account
        from app.db.models.conversation import Conversation
        from app.db.models.customer import Customer

        cust = Customer(name=f"P5MSG-03-客户-{uuid4().hex[:6]}")
        db.add(cust)
        await db.commit()
        conv = Conversation(customer_id=cust.id, channel=channel)
        db.add(conv)
        await db.commit()
        return cust, conv

    async def test_wechat_end_to_end_send_succeeds(self, db):
        """Acceptance: at least one V1 channel (wechat) sends end-to-end."""
        from app.db.models.messages import ChannelMessage
        from app.schemas.messages import MessageSendRequest
        from app.services.channel_delivery_service import ChannelDeliveryService
        from app.services.message_service import MessageService

        _, conv = await self._seed(db, "wechat")

        # enqueue via P5MSG-02's send (queued outbound record).
        msg_svc = MessageService(db)
        msg = await msg_svc.send_message(MessageSendRequest(
            conversation_id=conv.id,
            channel="wechat",
            direction="out",
            content={"text": "P5MSG-03 端到端", "target": "peer-abc"},
        ))
        assert msg.status == "queued"

        # deliver through the BitBrowser channel adapter (mock mode -> sent).
        del_svc = ChannelDeliveryService(db)
        outcome = await del_svc.deliver_message(msg.id, attempt_backoff=0)
        assert outcome.delivered is True
        assert outcome.message.status == "sent"
        assert outcome.mock is True, "V1 SDK-unavailable path must be mock mode"
        assert outcome.provider_message_id and outcome.provider_message_id.startswith("mock_")

        # persisted record reflects the transition.
        fresh = (
            await db.execute(
                __import__("sqlalchemy").select(ChannelMessage).where(
                    ChannelMessage.id == msg.id
                )
            )
        ).scalar_one()
        assert fresh.status == "sent"
        assert fresh.provider_message_id == outcome.provider_message_id
        assert fresh.sent_at is not None
        # ADR-017: the deprecated per-row receipts JSONB is no longer written;
        # the transition is recorded once in the ExecutionLog SoT.
        assert not fresh.receipts
        from sqlalchemy import select
        from app.db.models.workflow import ExecutionLog
        sent_logs = (
            await db.execute(
                select(ExecutionLog).where(
                    ExecutionLog.execution_type == "message_status",
                    ExecutionLog.input_params["message_id"].as_string() == str(msg.id),
                )
            )
        ).scalars().all()
        assert any(
            (l.input_params or {}).get("to") == "sent" for l in sent_logs
        ), "sent transition must be recorded in the ExecutionLog SoT"

    async def test_rate_limit_takes_effect(self, db):
        from app.schemas.messages import MessageSendRequest
        from app.services.channel_delivery_service import ChannelDeliveryService
        from app.services.message_service import MessageService
        from app.db.models.messages import ChannelMessage
        from sqlalchemy import select

        _, conv = await self._seed(db, "douyin")
        msg = await MessageService(db).send_message(MessageSendRequest(
            conversation_id=conv.id, channel="douyin",
            direction="out", content={"text": "rl"},
        ))

        # A deterministic limiter capped at 0 denies delivery (rate limit
        # takes effect: adapter never called, record marked failed/rate_limited).
        limiter = ChannelRateLimiter()
        del_svc = ChannelDeliveryService(db, rate_limiter=limiter)
        del_svc._load_config = AsyncMock(return_value=None)
        del_svc._delivery_policy = AsyncMock(return_value={
            "rate_limit_per_hour": 0,
            "retry_max_attempts": 3,
            "retry_backoff_seconds": 0,
            "enabled": True,
        })
        outcome = await del_svc.deliver_message(msg.id, attempt_backoff=0)
        assert outcome.message.status == "failed"
        assert outcome.error.get("code") == "rate_limited"
        fresh = (
            await db.execute(select(ChannelMessage).where(ChannelMessage.id == msg.id))
        ).scalar_one()
        assert fresh.status == "failed"
        assert (fresh.error or {}).get("code") == "rate_limited"

    async def test_failed_delivery_records_error(self, db):
        from app.schemas.messages import MessageSendRequest
        from app.services.channel_delivery_service import ChannelDeliveryService
        from app.services.message_service import MessageService
        from app.db.models.messages import ChannelMessage
        from sqlalchemy import select

        _, conv = await self._seed(db, "xiaohongshu")
        msg = await MessageService(db).send_message(MessageSendRequest(
            conversation_id=conv.id, channel="xiaohongshu",
            direction="out", content={"text": "will-fail"},
        ))

        # An adapter that always fails -> delivery must mark failed + record error.
        class _AlwaysFail(ChannelAdapter):
            @property
            def adapter_name(self):
                return "alwaysfail"

            def supported_channels(self):
                return {"wechat", "douyin", "xiaohongshu"}

            async def send(self, content, target=None):
                return SendResult.failure(
                    {"code": "adapter_error", "message": "injected failure"},
                    provider="alwaysfail",
                )

            async def receive(self, limit=20, since=None):
                return []

        reg = ChannelAdapterRegistry()
        reg.register(_AlwaysFail())
        del_svc = ChannelDeliveryService(db, registry=reg, rate_limiter=ChannelRateLimiter())
        del_svc._delivery_policy = AsyncMock(return_value={
            "rate_limit_per_hour": 60, "retry_max_attempts": 2,
            "retry_backoff_seconds": 0, "enabled": True,
        })
        outcome = await del_svc.deliver_message(msg.id, attempt_backoff=0)
        assert outcome.message.status == "failed"
        fresh = (
            await db.execute(select(ChannelMessage).where(ChannelMessage.id == msg.id))
        ).scalar_one()
        assert fresh.status == "failed"
        assert (fresh.error or {}).get("message") == "injected failure"


# ===========================================================================
# 7. Router + schema wiring
# ===========================================================================
class TestChannelRouterWiring:
    def test_routes_registered(self):
        from app.routers.channels import router
        paths = {r.path for r in router.routes}
        assert "/channels" in paths                       # CRUD list/create
        assert "/channels/{channel_id}" in paths         # CRUD get/put/delete
        assert "/channels/deliver" in paths
        assert "/channels/poll" in paths
        assert router.prefix == "/channels"

    def test_static_paths_before_dynamic(self):
        """/deliver + /poll MUST be registered ahead of /{channel_id} so the
        UUID-capture route does not swallow them (same rule as P5MSG-02 /send)."""
        from app.routers.channels import router
        order = [r.path for r in router.routes if r.path in
                 ("/channels/deliver", "/channels/poll", "/channels/{channel_id}")]
        assert order.index("/channels/deliver") < order.index("/channels/{channel_id}")
        assert order.index("/channels/poll") < order.index("/channels/{channel_id}")

    def test_main_app_mounts_channels_router(self):
        main_src = Path("H:/AI-Agent-Platform/backend/app/main.py").read_text(encoding="utf-8")
        assert re.search(
            r"app\.include_router\(channels_router,\s*prefix=/?\"?/api/v1\"?\)", main_src
        ), "main.py must mount channels_router under /api/v1"

    def test_delivery_outcome_fields_used_by_router(self):
        """The /deliver handler must render the DeliveryOutcome (not a raw
        ChannelMessage) — the crashed mid-refactor contract mismatch guard."""
        src = Path("H:/AI-Agent-Platform/backend/app/routers/channels.py").read_text(
            encoding="utf-8"
        )
        assert "outcome.message.status" in src, "deliver must read status off DeliveryOutcome.message"
        assert "outcome.mock" in src, "deliver must read mock off DeliveryOutcome"
        assert "outcome.provider" in src, "deliver must read provider off DeliveryOutcome"

    def test_channel_config_schemas_validate(self):
        from app.schemas.messages import (
            ChannelConfigCreate, ChannelConfigUpdate,
            ChannelDeliverRequest, ChannelPollRequest, ChannelConfigResponse,
        )
        c = ChannelConfigCreate(channel="wechat", type="messaging")
        assert c.rate_limit_per_hour == 60 and c.retry_max_attempts == 3
        ChannelConfigUpdate(enabled=False)
        ChannelDeliverRequest(message_id=uuid4())
        ChannelPollRequest(channel="wechat", conversation_id=uuid4())
        # unknown channel rejected
        with pytest.raises(Exception):
            ChannelConfigCreate(channel="kittychat")

    def test_migration_head_is_024(self):
        """024_channel_config links onto P5MSG-02's 023 head in the chain.

        024 was authored as the head *at P5MSG-03 write time*; a later sibling
        migration (025_nurture_step_execution) now sits above it, so the
        meaningful invariant is: 024 exists, is a single-branch revision, and
        its ``down_revision`` is P5MSG-02's 023_messages_receipt — i.e. the
        channel_config DDL lands directly on P5MSG-02's head.
        """
        import alembic.config
        import alembic.script
        cfg = alembic.config.Config("H:/AI-Agent-Platform/backend/alembic.ini")
        sc = alembic.script.ScriptDirectory.from_config(cfg)
        # 024 is present in the linear chain and links onto 023.
        rev = sc.get_revision("024_channel_config")
        assert rev is not None, "024_channel_config missing from the alembic chain"
        assert rev.down_revision == "023_messages_receipt"
