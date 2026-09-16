"""P5MSG-04 realtime channel + conversation-management API tests.

Two layers:

* **DB-backed service tests** (``TestConversationService`` /
  ``TestMarkReadService``): drive the real test Postgres through
  ``RealtimeConversationService`` + ``MessageService`` directly, in one event
  loop (no TestClient portal -> no asyncpg loop mismatch). These verify
  preview / unread / active-filtering and the mark-read receipt flow.

* **Hub endpoint tests** (``TestHubEndpoints``): the pure-hub, no-DB REST
  endpoints (publish / resync / SSE stream) through a TestClient. The hub is
  in-memory and the endpoints never touch ``get_db``, so no session override
  is required and there is no loop mismatch.

Run:  cd H:/AI-Agent-Platform/backend && uv run pytest tests/test_realtime_api.py -v
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

TEST_DB = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"

# P5MSG-FIX-1: the /realtime/publish seam is now gated by a trusted-producer
# Bearer token (app.security). These hub endpoint tests exercise the seam the
# way a trusted producer would: with a configured token.
PUBLISH_TOKEN = "test-trusted-token"


def _publish_auth() -> dict:
    return {"Authorization": f"Bearer {PUBLISH_TOKEN}"}


def _pg_available() -> bool:
    try:
        import asyncpg

        async def _probe():
            dsn = TEST_DB.replace("postgresql+asyncpg://", "postgresql://")
            conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=3)
            await conn.close()
            return True

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_probe())
        finally:
            loop.close()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def sessionmaker():
    """An async sessionmaker on the real test DB, with the schema ensured."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.db.models import Base

    engine = create_async_engine(TEST_DB)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    yield Session
    await engine.dispose()


@pytest.fixture
async def seeded(sessionmaker):
    """Seed one customer, one active conversation and inbound channel
    messages in varied delivery states so preview + unread + mark-read are
    all observable."""
    from app.db.models.customer import Customer
    from app.db.models.conversation import Conversation
    from app.db.models.messages import ChannelMessage

    session = sessionmaker()
    cust = Customer(name=f"rt-{uuid4().hex[:8]}", is_deleted=False)
    session.add(cust)
    await session.commit()
    await session.refresh(cust)

    conv = Conversation(customer_id=cust.id, channel="wechat",
                       subject="rt-conversation", status="active", is_deleted=False)
    session.add(conv)
    await session.commit()
    await session.refresh(conv)

    # P5MSG-FLAKY: seed m1..m4 with an explicitly increasing created_at (1s step)
    # so the seed no longer produces a created_at tie. The "latest preview" query
    # (order_by created_at desc) then has a single decisive key instead of
    # falling back to a random UUID4 id tie-break, which made the preview
    # non-deterministic across reruns. updated_at mirrors created_at so the
    # secondary sort keys stay stable too. The true last message is m4 (the
    # outbound reply), so the preview deterministically resolves to it.
    t = datetime.now(timezone.utc)
    step = timedelta(seconds=1)
    m1 = ChannelMessage(conversation_id=conv.id, direction="in", status="delivered",
                       content={"text": "hi unread 1"},
                       created_at=t, updated_at=t)
    m2 = ChannelMessage(conversation_id=conv.id, direction="in", status="sent",
                       content={"text": "hi unread 2"},
                       created_at=t + step, updated_at=t + step)
    m3 = ChannelMessage(conversation_id=conv.id, direction="in", status="read",
                       content={"text": "already read"},
                       created_at=t + 2 * step, updated_at=t + 2 * step)
    m4 = ChannelMessage(conversation_id=conv.id, direction="out", status="delivered",
                       content={"text": "outbound reply"},
                       created_at=t + 3 * step, updated_at=t + 3 * step)
    session.add_all([m1, m2, m3, m4])
    await session.commit()
    yield {
        "sessionmaker": sessionmaker,
        "customer_id": cust.id,
        "conversation_id": conv.id,
        "conv": conv,
        "msgs": [m1, m2, m3, m4],
    }
    await session.close()


def _new_client():
    """A TestClient bound to the (hub-only, no-DB) realtime endpoints.

    No ``get_db`` override: these endpoints use the in-memory hub only.
    """
    import app.main as m
    from app.services.realtime_hub import reset_realtime_hub

    reset_realtime_hub()
    client = TestClient(m.app)
    return client


# ---------------------------------------------------------------------------
# DB-backed service tests (one event loop, no TestClient)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _pg_available(), reason="Postgres test DB unreachable")
class TestConversationService:
    async def test_active_list_preview_and_unread(self, seeded):
        from app.services.realtime_conversation_service import RealtimeConversationService

        svc = RealtimeConversationService(seeded["sessionmaker"]())
        rows = await svc.list_active_conversations(page=1, page_size=50)
        mine = [r for r in rows if r.conversation_id == seeded["conversation_id"]]
        assert len(mine) == 1
        it = mine[0]
        assert it.status == "active"
        assert it.channel == "wechat"
        # 2 inbound not-read messages are unread
        assert it.unread_count == 2
        # preview is the most-recent (last) message — deterministically m4, the
        # outbound reply, since the seed assigns it the greatest created_at.
        # P5MSG-FLAKY: no longer a set-membership guess over "hi unread"/
        # "already read" that flaked on a random UUID4 tie-break.
        assert it.last_message_preview == "outbound reply"

    async def test_unread_total_scoped_to_customer(self, seeded):
        from app.services.realtime_conversation_service import RealtimeConversationService

        svc = RealtimeConversationService(seeded["sessionmaker"]())
        total = await svc.unread_total(customer_id=seeded["customer_id"])
        assert total >= 2

    async def test_closed_conversation_excluded(self, seeded):
        from app.db.models.conversation import Conversation
        from app.services.realtime_conversation_service import RealtimeConversationService

        sm = seeded["sessionmaker"]
        s = sm()
        closed = Conversation(customer_id=seeded["customer_id"], channel="email",
                              status="closed", is_deleted=False)
        s.add(closed)
        await s.commit()
        await s.refresh(closed)

        svc = RealtimeConversationService(s)
        rows = await svc.list_active_conversations(page=1, page_size=100)
        ids = {r.conversation_id for r in rows}
        assert closed.id not in ids
        assert seeded["conversation_id"] in ids
        await s.close()


@pytest.mark.skipif(not _pg_available(), reason="Postgres test DB unreachable")
class TestMarkReadService:
    async def test_mark_read_drives_receipts_and_clears_unread(self, seeded):
        from app.db.models.messages import ChannelMessage
        from app.schemas.messages import MessageStatusUpdateRequest
        from app.services.message_service import MessageService
        from app.services.realtime_conversation_service import RealtimeConversationService
        from sqlalchemy import and_, select

        sm = seeded["sessionmaker"]
        s = sm()
        service = MessageService(s)

        conv = seeded["conversation_id"]
        base_filter = and_(
            ChannelMessage.conversation_id == conv,
            ChannelMessage.is_deleted == False,  # noqa: E712
            ChannelMessage.direction == "in",
            ChannelMessage.status != "read",
        )
        rows = (await s.execute(select(ChannelMessage.id).where(base_filter))).scalars().all()
        marked = []
        for msg_id in rows:
            await service.update_status(msg_id, MessageStatusUpdateRequest(status="read", source="manual"))
            marked.append(msg_id)
        assert len(marked) == 2  # delivered + sent -> read; the read one already terminal

        # unread is now zero: recompute via the list view
        from app.services.realtime_conversation_service import RealtimeConversationService
        svc = RealtimeConversationService(s)
        rows = await svc.list_active_conversations(page=1, page_size=100)
        mine = [r for r in rows if r.conversation_id == conv]
        assert len(mine) == 1 and mine[0].unread_count == 0
        await s.close()


# ---------------------------------------------------------------------------
# Hub-only endpoint tests (TestClient, no DB)
# ---------------------------------------------------------------------------


class TestHubEndpoints:
    def setup_method(self):
        # Make this test process a "trusted producer" for the publish seam.
        os.environ["REALTIME_PUBLISH_TOKENS"] = PUBLISH_TOKEN
        self.client = _new_client()

    def teardown_method(self):
        os.environ.pop("REALTIME_PUBLISH_TOKENS", None)

    def test_root_health_and_route_exist(self):
        # /api/v1/realtime resync is registered and reachable with no events
        r = self.client.get("/api/v1/realtime/resync", params={"since": 0})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 0
        assert body["events"] == []

    def test_publish_then_resync_since_zero(self):
        r = self.client.post(
            "/api/v1/realtime/publish",
            json={"kind": "channel_message.created",
                  "conversation_id": str(uuid4()),
                  "payload": {"message_id": "abc", "status": "queued"}},
            headers=_publish_auth(),
        )
        assert r.status_code == 202, r.text
        seq = r.json()["data"]["emitted_seq"]
        assert seq is not None

        rr = self.client.get("/api/v1/realtime/resync", params={"since": 0})
        assert rr.status_code == 200
        events = rr.json()["events"]
        assert any(e["seq"] == seq and e["kind"] == "channel_message.created" for e in events)

    def test_resync_since_cursor_excludes_consumed(self):
        a = self.client.post("/api/v1/realtime/publish",
                            json={"kind": "channel_message.status", "payload": {"status": "sent"}},
                            headers=_publish_auth())
        sa = a.json()["data"]["emitted_seq"]
        b = self.client.post("/api/v1/realtime/publish",
                            json={"kind": "channel_message.status", "payload": {"status": "delivered"}},
                            headers=_publish_auth())
        sb = b.json()["data"]["emitted_seq"]
        rr = self.client.get("/api/v1/realtime/resync", params={"since": sa})
        seqs = [e["seq"] for e in rr.json()["events"]]
        assert sb in seqs
        assert sa not in seqs

    def test_publish_rejects_unknown_kind(self):
        r = self.client.post("/api/v1/realtime/publish",
                            json={"kind": "not_a_real_kind", "payload": {}},
                            headers=_publish_auth())
        assert r.status_code == 422, r.text

    def test_publish_duplicate_dedup(self):
        payload = {"kind": "channel_message.status", "dedup_id": "dedup-x", "payload": {"status": "sent"}}
        r1 = self.client.post("/api/v1/realtime/publish", json=payload, headers=_publish_auth())
        r2 = self.client.post("/api/v1/realtime/publish", json=payload, headers=_publish_auth())
        assert r1.status_code == 202
        assert r1.json()["message"] == "accepted"
        assert r2.json()["message"] == "duplicate_dropped"
        assert r2.json()["data"]["emitted_seq"] is None

    async def test_sse_stream_frames_directly(self):
        """Drive the SSE streaming generator directly (bounded), asserting the
        hello + replay frames. Avoids the TestClient portal deadlocking on an
        infinite stream — we pull a fixed number of frames from the
        generator, then stop. Verifies the stream emits well-formed SSE and
        replays retained events to a fresh subscriber."""
        from app.routers.realtime import realtime_stream

        reset = __import__("app.services.realtime_hub", fromlist=["reset_realtime_hub"]).reset_realtime_hub
        reset()

        # Seed one retained event on the shared hub first.
        from app.services.realtime_events import publish_realtime_event
        publish_realtime_event("channel_message.created", "c1", {"message_id": "s1"})

        response = await realtime_stream(conversation_id=None, since=0)
        body = response.body_iterator
        frames = []
        async for chunk in body:
            # Each yield is a fully-formed SSE frame string.
            frames.append(chunk)
            joined = "".join(frames)
            if "event: replay" in joined or "event: message" in joined:
                break
            if len(frames) > 20:
                break

        joined = "".join(frames)
        assert "event: hello" in joined
        # The hello frame is parseable JSON.
        hello_block = joined.split("event: hello\n", 1)[1].split("\n\n", 1)[0]
        hello = json.loads(hello_block.split("data: ", 1)[1])
        assert hello["type"] == "hello"
        assert hello["head_seq"] >= 1
        # And the seeded event was replayed (offline catch-up) to the fresh sub.
        assert "event: replay" in joined


# ---------------------------------------------------------------------------
# P5MSG-FIX-1 (P0-3 + P0-2) — trusted-producer auth gates + payload injection
# ---------------------------------------------------------------------------


class TestPublishAuth:
    """POST /api/v1/realtime/publish now requires a trusted producer Bearer.

    Verifies the P0-3 fix: unauthenticated / 异主 callers are rejected, a
    trusted caller can publish, and a trusted caller still cannot inject a
    PII / secret-bearing or unbounded payload (strong schema -> 422).
    """

    def setup_method(self):
        os.environ["REALTIME_PUBLISH_TOKENS"] = PUBLISH_TOKEN
        self.client = _new_client()

    def teardown_method(self):
        os.environ.pop("REALTIME_PUBLISH_TOKENS", None)

    def _publish(self, payload, headers):
        return self.client.post(
            "/api/v1/realtime/publish",
            json={"kind": "channel_message.status", "payload": payload},
            headers=headers,
        )

    def test_publish_no_token_is_401(self):
        r = self._publish({"status": "sent"}, {})
        assert r.status_code == 401, r.text

    def test_publish_untrusted_token_is_403(self):
        r = self._publish({"status": "sent"}, {"Authorization": "Bearer not-a-trusted-token"})
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == 403

    def test_publish_trusted_token_succeeds(self):
        r = self._publish({"status": "sent", "conversation_id": str(uuid4())}, _publish_auth())
        assert r.status_code == 202, r.text
        assert r.json()["data"]["emitted_seq"] is not None

    def test_publish_trusted_but_pii_payload_is_422(self):
        # Trusted producer, but the payload carries a PII/secret key -> blocked.
        r = self._publish({"status": "sent", "content_text": "hello world"}, _publish_auth())
        assert r.status_code == 422, r.text

    def test_publish_trusted_but_secret_key_is_422(self):
        r = self._publish({"status": "sent", "api_key": "abc"}, _publish_auth())
        assert r.status_code == 422, r.text

    def test_publish_trusted_but_nested_payload_is_422(self):
        r = self._publish({"status": "sent", "meta": {"a": 1}}, _publish_auth())
        assert r.status_code == 422, r.text

    def test_publish_closed_posture_no_tokens_configured(self):
        # Empty trusted set (default) == no one is trusted: even a Bearer fails.
        os.environ["REALTIME_PUBLISH_TOKENS"] = ""
        r = self._publish({"status": "sent"}, {"Authorization": "Bearer anything"})
        assert r.status_code == 403, r.text


class TestOverAuth:
    """P0-2 — the cross-owner write primitives are now auth-gated.

    Driving the delivery state machine (``POST /messages/{id}/status``) and
    marking a conversation read (``POST /realtime/read``) are write
    primitives that previously accepted *any* caller. 异主 (unauthenticated /
    untrusted) callers are now rejected; these HTTP-level checks need no DB
    because the auth dependency short-circuits before the request body.
    """

    def setup_method(self):
        os.environ["REALTIME_PUBLISH_TOKENS"] = PUBLISH_TOKEN
        self.client = _new_client()

    def teardown_method(self):
        os.environ.pop("REALTIME_PUBLISH_TOKENS", None)

    def test_message_status_no_token_is_401(self):
        r = self.client.post(
            f"/api/v1/messages/{uuid4()}/status", json={"status": "read"}
        )
        assert r.status_code == 401, r.text

    def test_message_status_untrusted_token_is_403(self):
        r = self.client.post(
            f"/api/v1/messages/{uuid4()}/status",
            json={"status": "read"},
            headers={"Authorization": "Bearer not-a-trusted-token"},
        )
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == 403

    def test_realtime_read_no_token_is_401(self):
        r = self.client.post(
            "/api/v1/realtime/read", json={"conversation_id": str(uuid4())}
        )
        assert r.status_code == 401, r.text

    def test_realtime_read_untrusted_token_is_403(self):
        r = self.client.post(
            "/api/v1/realtime/read",
            json={"conversation_id": str(uuid4())},
            headers={"Authorization": "Bearer not-a-trusted-token"},
        )
        assert r.status_code == 403, r.text
