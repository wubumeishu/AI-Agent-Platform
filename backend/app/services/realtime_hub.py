"""Realtime push hub — P5MSG-04 (in-process fan-out + replay log).

This module owns the *transport* half of P5MSG-04: a per-process realtime
hub that (1) fans a message event out to every live subscriber and
(2) keeps a bounded replay log so a client that drops and reconnects can
resync from its last-seen sequence number (``since``) and recover any
events it missed while offline — without losing or duplicating messages.

Design notes (matches the platform's in-process V1 conventions):

* **In-memory, single event loop.** V1 is a single deployment; the hub is
  an asyncio-native fan-out (``dict[sub_id, Queue]``) with no Redis/queue
  dependency, mirroring ``app.events.domain_events``. The surface is small
  so it can be swapped for a Redis-pub/sub backend later without touching
  publishers or the router.
* **Bounded replay log** (``REPLAY_CAP``). Every emitted event is appended
  to the log with a monotonically increasing ``seq``. A reconnecting
  client passes the last ``seq`` it processed as ``since``; the hub replays
  every log entry with ``seq > since``. This is the "断线重连 + 离线队列 +
  重连补发(去重)" requirement: the replay log IS the offline queue, and the
  per-event ``seq`` is the dedup cursor — a client never sees an event twice
  (events it already consumed have ``seq <= since``) and never loses one
  (events emitted while it was offline are in the log).
* **Backpressure without loss.** Live queues are bounded; if a slow client
  overflows, we mark it *behind* and skip its live push rather than block
  the emitter (one lagging client must not stall everyone). The client
  recovers via a ``since``-resync, which is authoritative, so nothing is
  lost. The replay log is the source of truth; the live queue is best-effort.
* **No secrets, no message text required.** Events carry ids, a kind and a
  small structured payload (ids / status / channel) — consistent with the
  ARCHITECTURE rule that bus payloads keep PII and credentials out.

Public seam:
    ``get_realtime_hub().emit(kind, conversation_id, payload, dedup_id)``
is what the P5MSG-02 message-event source (and P5MSG-04's router/tests)
call to push an event. See ``app.services.realtime_events`` for the
thin public ``publish_realtime_event`` wrapper + the shared-bus bridge.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)

# Replay log capacity. Every event lands here; a client that reconnects
# with a ``since`` older than the oldest retained entry is told to do a
# full REST resync (gap detection) — see the router.
REPLAY_CAP = 5000
# Per-subscriber live queue capacity. A bounded queue gives us a clean
# backpressure signal instead of unbounded memory growth for a stalled client.
SUB_QUEUE_MAX = 1000
# How many recent dedup ids to remember so a double-published event
# (e.g. P5MSG-02 retries) is not pushed twice.
DEDUP_CAP = 4096


@dataclass
class RealtimeEvent:
    """One realtime message event flowing through the hub.

    ``seq`` is the global, monotonically increasing delivery sequence
    number that doubles as the reconnect/dedup cursor.
    """

    seq: int
    kind: str
    conversation_id: Optional[str]
    payload: Dict[str, Any]
    ts: float = field(default_factory=time.time)

    def to_sse_dict(self) -> Dict[str, Any]:
        """JSON-safe dict for the SSE ``data:`` line."""
        return {
            "type": "event",
            "seq": self.seq,
            "kind": self.kind,
            "conversation_id": self.conversation_id,
            "ts": self.ts,
            "payload": self.payload,
        }


@dataclass
class _Subscription:
    sub_id: str
    conversation_id: Optional[str]  # None = global (all conversations)
    queue: "asyncio.Queue[RealtimeEvent]"
    behind: bool = False


class RealtimeHub:
    """In-process realtime fan-out + bounded replay log.

    All state is mutated only on the process's event loop, so a plain
    ``dict`` / ``deque`` is safe under asyncio (no locks needed).
    """

    def __init__(
        self,
        replay_cap: int = REPLAY_CAP,
        sub_queue_max: int = SUB_QUEUE_MAX,
        dedup_cap: int = DEDUP_CAP,
    ) -> None:
        self._replay: Deque[RealtimeEvent] = deque(maxlen=replay_cap)
        self._subs: Dict[str, _Subscription] = {}
        self._seq = 0
        self._sub_queue_max = sub_queue_max
        # Recent dedup ids (insertion-ordered; oldest evicted when full).
        self._dedup: Dict[str, None] = {}
        self._dedup_cap = dedup_cap

    # ---------------- emit ----------------

    def emit(
        self,
        kind: str,
        conversation_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        dedup_id: Optional[str] = None,
    ) -> Optional[int]:
        """Append one event to the replay log and fan out to live subs.

        Returns the event ``seq`` on success, or ``None`` when the event
        was dropped as a duplicate (``dedup_id`` already seen).
        """
        if dedup_id is not None:
            if dedup_id in self._dedup:
                logger.debug("realtime: duplicate emit dropped id=%s", dedup_id)
                return None
            self._dedup[dedup_id] = None
            if len(self._dedup) > self._dedup_cap:
                # Evict the oldest (dict preserves insertion order).
                oldest = next(iter(self._dedup))
                self._dedup.pop(oldest, None)

        self._seq += 1
        event = RealtimeEvent(
            seq=self._seq,
            kind=kind,
            conversation_id=conversation_id,
            payload=payload or {},
        )
        self._replay.append(event)

        for sub in list(self._subs.values()):
            if sub.behind:
                # This subscriber overflowed; it recovers via since-resync.
                continue
            if sub.conversation_id is not None and conversation_id not in (
                None,
                sub.conversation_id,
            ):
                # Global sub (filter None) or matching-conversation sub only.
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # Backpressure: mark behind, never block the emitter.
                sub.behind = True
                logger.warning(
                    "realtime: sub %s overflowed (behind); rely on since-resync",
                    sub.sub_id,
                )
        return event.seq

    # ---------------- subscribe ----------------

    def subscribe(
        self,
        conversation_id: Optional[str] = None,
        since: int = 0,
    ) -> Tuple[str, List[RealtimeEvent], "asyncio.Queue[RealtimeEvent]"]:
        """Create a live subscription.

        Returns ``(sub_id, replay_events, live_queue)``:
          * ``sub_id`` — pass to :meth:`unsubscribe` when the client disconnects.
          * ``replay_events`` — every log entry with ``seq > since`` (the
            offline catch-up), oldest first, INCLUDING any events that
            were already waiting in the live queue. The client should
            remember the last ``seq`` it processes and pass it back as
            ``since`` on the next reconnect.
          * ``live_queue`` — an asyncio queue fed with NEW events as they
            are emitted (events after the replay window).

        ``since`` is the dedup/replay cursor: pass the highest ``seq`` you
        already have to receive exactly the events you missed.
        """
        sub_id = uuid4().hex
        queue: "asyncio.Queue[RealtimeEvent]" = asyncio.Queue(maxsize=self._sub_queue_max)
        self._subs[sub_id] = _Subscription(
            sub_id=sub_id,
            conversation_id=conversation_id,
            queue=queue,
        )
        replay = self._replay_events(conversation_id, since)
        logger.info(
            "realtime: sub %s (conv=%s since=%d) replaying %d event(s)",
            sub_id[:8], conversation_id, since, len(replay),
        )
        return sub_id, replay, queue

    def unsubscribe(self, sub_id: str) -> None:
        """Drop a subscription (client disconnected). Idempotent."""
        self._subs.pop(sub_id, None)

    # ---------------- queries ----------------

    def _replay_events(
        self, conversation_id: Optional[str], since: int
    ) -> List[RealtimeEvent]:
        out: List[RealtimeEvent] = []
        for e in self._replay:
            if e.seq <= since:
                continue
            if conversation_id is not None and e.conversation_id not in (
                None,
                conversation_id,
            ):
                continue
            out.append(e)
        return out

    @property
    def head_seq(self) -> int:
        """The most recent ``seq`` (0 when nothing has been emitted)."""
        return self._seq

    @property
    def oldest_seq(self) -> int:
        """Oldest ``seq`` still retained in the replay log (0 if empty).

        A client whose ``since`` is older than this has a *gap* and must
        fall back to a full REST resync — surfaced by the router.
        """
        return self._replay[0].seq if self._replay else 0

    @property
    def active_subscriber_count(self) -> int:
        return len(self._subs)

    @property
    def replay_depth(self) -> int:
        return len(self._replay)

    def reset(self) -> None:
        """Test helper: drop all state."""
        self._replay.clear()
        self._subs.clear()
        self._seq = 0
        self._dedup.clear()


# ---------------------------------------------------------------------------
# Module-level default hub (process singleton)
# ---------------------------------------------------------------------------
_default_hub: Optional[RealtimeHub] = None


def get_realtime_hub() -> RealtimeHub:
    """Return the process-default realtime hub (share one wiring point)."""
    global _default_hub
    if _default_hub is None:
        _default_hub = RealtimeHub()
    return _default_hub


def reset_realtime_hub() -> None:
    """Test helper: drop the singleton so a fresh hub is created on next use."""
    global _default_hub
    _default_hub = None
