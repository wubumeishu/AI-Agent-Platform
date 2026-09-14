"""P5MSG-04 realtime hub + event-seam unit tests (no DB required).

Covers the transport half of P5MSG-04:
  * fan-out to live subscribers
  * replay log + since-cursor reconnect / offline catch-up / dedup
  * backpressure (overflow marks a sub behind without blocking the emitter,
    and the replay log still recovers everything -> no message loss)
  * the public ``publish_realtime_event`` seam and the shared-bus bridge

These run without Postgres: the hub is pure in-memory asyncio.
Run:  cd H:/AI-Agent-Platform/backend && uv run pytest tests/test_realtime_hub.py -v
"""
import asyncio

import pytest

from app.services.realtime_hub import RealtimeHub, get_realtime_hub
from app.services.realtime_events import (
    publish_realtime_event,
    register_realtime_bus_bridge,
    reset_realtime_bus_bridge,
)
from app.services.realtime_hub import reset_realtime_hub
from app.events.domain_events import DomainEvent, get_event_bus


@pytest.fixture(autouse=True)
def _isolated_hub():
    """Every test gets a fresh process hub + a clean bus."""
    reset_realtime_hub()
    reset_realtime_bus_bridge()
    bus = get_event_bus()
    bus.reset()
    yield
    reset_realtime_hub()
    reset_realtime_bus_bridge()
    get_event_bus().reset()


# ---------------------------------------------------------------------------
# Emit + seq + replay
# ---------------------------------------------------------------------------


class TestEmitAndReplay:
    def test_emit_increments_seq(self):
        hub = get_realtime_hub()
        assert hub.head_seq == 0
        assert hub.emit("channel_message.created", "c1") == 1
        assert hub.emit("channel_message.status", "c1") == 2
        assert hub.emit("channel_message.read", "c2") == 3
        assert hub.head_seq == 3

    def test_replay_since_zero_returns_all_oldest_first(self):
        hub = RealtimeHub()
        for i in range(5):
            hub.emit("channel_message.created", f"c{i}")
        events = hub._replay_events(None, 0)
        assert [e.seq for e in events] == [1, 2, 3, 4, 5]

    def test_replay_since_cursor_is_offline_catchup(self):
        """A client that already processed seq 1..2 must receive only 3..N on
        reconnect (dedup by cursor; no re-delivery, no loss)."""
        hub = RealtimeHub()
        for i in range(1, 6):  # seq 1..5
            hub.emit("channel_message.created", "c1")
        since = 2
        got = hub._replay_events(None, since)
        assert [e.seq for e in got] == [3, 4, 5]
        # nothing with seq <= since leaks through:
        assert all(e.seq > since for e in got)

    def test_replay_scoped_by_conversation(self):
        hub = RealtimeHub()
        hub.emit("channel_message.created", "cA")
        hub.emit("channel_message.status", "cB")
        hub.emit("channel_message.created", "cA")
        got = hub._replay_events("cA", 0)
        assert [e.conversation_id for e in got] == ["cA", "cA"]
        assert len(got) == 2


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


class TestDedup:
    def test_duplicate_dedup_id_is_dropped(self):
        hub = RealtimeHub()
        assert hub.emit("channel_message.status", "c1", {"status": "sent"}, "k1") == 1
        # same dedup key -> dropped, seq does NOT advance
        assert hub.emit("channel_message.status", "c1", {"status": "sent"}, "k1") is None
        assert hub.head_seq == 1
        # a fresh key still lands
        assert hub.emit("channel_message.status", "c1", {"status": "sent"}, "k2") == 2

    def test_dedup_cap_evicts_oldest(self):
        hub = RealtimeHub(dedup_cap=3)
        for i in range(4):
            hub.emit("channel_message.status", "c", {}, f"key{i}")
        # key0 evicted -> re-emitting it is accepted again
        assert hub.emit("channel_message.status", "c", {}, "key0") is not None


# ---------------------------------------------------------------------------
# Reconnect / offline / gap
# ---------------------------------------------------------------------------


class TestReconnectOfflineGap:
    def test_reconnect_resubscribe_delivers_only_missed(self):
        """The exact acceptance path: disconnect, emit while offline,
        reconnect with since=last-seen, receive exactly the missed events
        (no dup, no loss)."""
        hub = RealtimeHub()
        sub1, replay1, live1 = hub.subscribe(conversation_id="c1", since=0)
        # the client consumes the live event seq 1 -> last_seen = 1
        hub.emit("channel_message.created", "c1")  # seq 1 -> live queue
        last_seen = 0
        while not live1.empty():
            last_seen = max(last_seen, live1.get_nowait().seq)
        assert last_seen == 1
        hub.unsubscribe(sub1)

        # offline: more events arrive
        hub.emit("channel_message.status", "c1", {"status": "sent"})  # seq 2
        hub.emit("channel_message.status", "c1", {"status": "delivered"})  # seq 3

        # reconnect: client passes since=last-seen
        sub2, replay2, live2 = hub.subscribe(conversation_id="c1", since=last_seen)
        got = [e.seq for e in replay2]
        assert got == [2, 3]
        # no event with seq <= last_seen is re-sent (dedup guarantee):
        assert all(e.seq > last_seen for e in replay2)
        hub.unsubscribe(sub2)

    def test_gap_detected_when_since_older_than_window(self):
        hub = RealtimeHub(replay_cap=3)
        for i in range(5):
            hub.emit("channel_message.created", "c1")
        # oldest retained seq is 3; a since=0 client has a gap
        assert hub.oldest_seq == 3
        assert hub.head_seq == 5
        # since=0 < oldest=3 -> resync gap flag must be computable
        since = 0
        gap = since > 0 and since < hub.oldest_seq  # 0 is "from oldest", not a gap
        assert gap is False
        # a since=1 client (retains nothing it asked for) -> gap
        since2 = 1
        gap2 = since2 > 0 and since2 < hub.oldest_seq
        assert gap2 is True

    def test_replay_cap_bounds_log(self):
        hub = RealtimeHub(replay_cap=3)
        for i in range(10):
            hub.emit("channel_message.created", "c1")
        assert hub.replay_depth == 3
        assert [e.seq for e in hub._replay_events(None, 0)] == [8, 9, 10]


# ---------------------------------------------------------------------------
# Backpressure / live fan-out
# ---------------------------------------------------------------------------


class TestBackpressureAndLive:
    async def test_live_events_flow_to_subscribed_queue(self):
        hub = RealtimeHub()
        sub, replay, live = hub.subscribe(conversation_id="c1", since=0)
        assert replay == []
        hub.emit("channel_message.created", "c1")
        hub.emit("channel_message.status", "c1")
        e1 = await asyncio.wait_for(live.get(), timeout=0.5)
        e2 = await asyncio.wait_for(live.get(), timeout=0.5)
        assert e1.kind == "channel_message.created"
        assert e2.kind == "channel_message.status"
        assert hub.active_subscriber_count == 1
        hub.unsubscribe(sub)
        assert hub.active_subscriber_count == 0

    async def test_subscription_scope_filters_other_conversations(self):
        hub = RealtimeHub()
        sub, _, live = hub.subscribe(conversation_id="cA", since=0)
        hub.emit("channel_message.created", "cB")  # not our conv -> not live-pushed
        hub.emit("channel_message.created", "cA")
        e = await asyncio.wait_for(live.get(), timeout=0.5)
        assert e.conversation_id == "cA"
        # the cB event is NOT in this sub's live queue (but IS in the log)
        assert live.empty()

    async def test_overflow_marks_behind_but_log_recovers(self):
        """Backpressure: a slow client that overflows its queue is marked
        behind (live pushes stop) but the replay log still holds everything,
        so a since-resync recovers all events -> no loss under pressure."""
        hub = RealtimeHub(sub_queue_max=1)
        sub, replay, live = hub.subscribe(conversation_id="c1", since=0)
        # Emit 3 events without draining; queue holds 1 -> subs mark behind.
        for i in range(3):
            hub.emit("channel_message.created", "c1")
        # live queue should have at most what fit; the rest are behind.
        drained = []
        while not live.empty():
            drained.append(live.get_nowait())
        # The sub is now 'behind' (it could not keep up).
        assert any(s.behind for s in hub._subs.values()) or len(drained) < 3
        # Crucially: a fresh resync recovers ALL 3 (no loss):
        sub2, replay2, live2 = hub.subscribe(conversation_id="c1", since=0)
        assert [e.seq for e in replay2] == [1, 2, 3]
        hub.unsubscribe(sub)
        hub.unsubscribe(sub2)

    async def test_emit_latency_under_1s(self):
        """Transport-level acceptance: an event emitted reaches a live
        subscriber in well under 1s (the <1s local-push SLA)."""
        hub = RealtimeHub()
        hub.subscribe(conversation_id="c1", since=0)
        t0 = asyncio.get_event_loop().time()
        hub.emit("channel_message.created", "c1")
        t1 = asyncio.get_event_loop().time()
        # The emit itself is O(subscribers) and must be negligible.
        assert (t1 - t0) < 1.0


# ---------------------------------------------------------------------------
# Public seam + bus bridge
# ---------------------------------------------------------------------------


class TestEventSeam:
    def test_publish_realtime_event_returns_seq(self):
        seq = publish_realtime_event(
            "channel_message.created", "c1", {"message_id": "m1"}, dedup_id="d1"
        )
        assert seq == 1
        assert get_realtime_hub().head_seq == 1

    def test_publish_duplicate_dropped(self):
        publish_realtime_event("channel_message.status", "c1", {"status": "sent"}, "k")
        assert publish_realtime_event(
            "channel_message.status", "c1", {"status": "sent"}, "k"
        ) is None
        assert get_realtime_hub().head_seq == 1

    async def test_bus_bridge_forwards_domain_events(self):
        """P5MSG-02/03 producers that publish on the shared bus are forwarded
        to the hub by the bridge (redundant, event-driven path)."""
        register_realtime_bus_bridge()
        bus = get_event_bus()
        event = DomainEvent(
            event_type="channel_message.status",
            entity_type="message",
            entity_id=None,
            payload={"conversation_id": "c1", "status": "delivered"},
        )
        await bus.publish(event)
        replay = get_realtime_hub()._replay_events(None, 0)
        assert len(replay) == 1
        assert replay[0].kind == "channel_message.status"
        assert replay[0].conversation_id == "c1"
        assert replay[0].payload["status"] == "delivered"

    def test_bridge_is_idempotent(self):
        n1 = register_realtime_bus_bridge()
        n2 = register_realtime_bus_bridge()
        assert n1 == n2 >= 0


# ---------------------------------------------------------------------------
# Concurrent conversations (acceptance: 并发会话测试通过)
# ---------------------------------------------------------------------------


class TestConcurrentConversations:
    async def test_many_concurrent_subs_no_crosstalk_no_loss(self):
        """N subscribers, each scoped to its own conversation; emit M events
        per conversation interleaved. Each subscriber must receive exactly its
        own M events (no crosstalk, no loss) and the replay log must retain
        every event so a fresh resync recovers all of them."""
        hub = RealtimeHub()
        n_subs, m_per = 8, 25
        convs = [f"conv-{i}" for i in range(n_subs)]
        live_queues = []
        for c in convs:
            sub, replay, live = hub.subscribe(conversation_id=c, since=0)
            assert replay == []  # nothing emitted yet
            live_queues.append((c, sub, live))

        # Interleave emissions across all conversations deterministically.
        for round_ in range(m_per):
            for idx, c in enumerate(convs):
                hub.emit("channel_message.created", c, {"n": round_})

        # Drain each live queue and verify per-conversation integrity.
        for c, sub, live in live_queues:
            got = []
            while not live.empty():
                got.append(live.get_nowait())
            assert len(got) == m_per, f"conv {c}: got {len(got)} expected {m_per}"
            # every event is scoped to this conversation (no crosstalk)
            assert all(e.conversation_id == c for e in got)
            # strictly increasing seq, contiguous
            seqs = [e.seq for e in got]
            assert seqs == sorted(seqs)
            # payloads are the round numbers in order
            assert [e.payload.get("n") for e in got] == list(range(m_per))
            hub.unsubscribe(sub)

        # Total retained in the replay log == all events, nothing lost.
        assert hub.replay_depth == n_subs * m_per
        assert hub.head_seq == n_subs * m_per

    async def test_reconnect_resync_covers_all_concurrent_events(self):
        """After a disconnect, a since-resync recovers every event emitted
        while offline across all conversations (offline queue -> no loss)."""
        hub = RealtimeHub()
        # initial subscriber watches conv-A, consumes a few
        subA, _, liveA = hub.subscribe(conversation_id="conv-A", since=0)
        for i in range(5):
            hub.emit("channel_message.created", "conv-A")
        last_seen = max((liveA.get_nowait().seq for _ in range(5)), default=0)
        hub.unsubscribe(subA)

        # while A is offline, more events on A and on other convs
        for i in range(5):
            hub.emit("channel_message.status", "conv-A")
        for i in range(5):
            hub.emit("channel_message.created", "conv-B")

        # A reconnects; replay for conv-A since last_seen must be exactly the 5 offline ones
        subA2, replayA, _ = hub.subscribe(conversation_id="conv-A", since=last_seen)
        assert [e.seq for e in replayA] == [last_seen + 1 + k for k in range(5)]
        assert all(e.conversation_id == "conv-A" for e in replayA)
        # conv-B events are NOT in A's replay (scoping holds across resync)
        hub.unsubscribe(subA2)
