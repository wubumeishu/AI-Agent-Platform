"""Channel-message service — P5MSG-02 (delivery state machine + queueing).

Business rules (kept out of the router layer, per platform convention
API -> Service -> Data layer):

* ``send_message``  enqueues an outbound channel message with status
  ``queued``. Before enqueueing it validates the Phase-1 resource layer:
  the conversation exists, and when ``account_id`` is provided the account
  exists and its platform code matches the requested ``channel``.
* ``list_messages`` paginates with channel / direction / status filters.
* ``update_status`` drives the delivery state machine:

      queued -> sent -> delivered -> read
      queued -> failed (error recorded)
      sent   -> failed (error recorded)

  Terminal states (``failed``, ``read``) reject every further transition;
  every *accepted* transition is recorded **once**, in the platform's
  ``execution_log`` (execution_type=``message_status``) — the single source
  of truth for the message state-transition audit trail (ADR-017).
* ``get_receipt`` returns the current delivery state plus the full
  receipt audit trail, *projected* from the ``execution_log`` SoT. The
  per-row ``messages.receipts`` / ``last_receipt_at`` JSONB are deprecated
  audit columns (legacy, read-only, no longer written) — see ADR-017.

Error mapping (PHASE1-API-SPEC envelope, business codes):
  * 4001 — resource not found (conversation / account / message)
  * 4002 — parameter error (bad input, unknown channel/direction)
  * 4003 — illegal state transition
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import Account
from app.db.models.conversation import Conversation
from app.db.models.messages import ChannelMessage
from app.db.models.platform import Platform
from app.db.models.workflow import ExecutionLog
from app.schemas.messages import (
    MESSAGE_CHANNELS,
    MessageReceipt,
    MessageReceiptResponse,
    MessageSendRequest,
    MessageStatusUpdateRequest,
)
from app.services.realtime_events import publish_realtime_event

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Delivery state machine
# ---------------------------------------------------------------------------

# allowed: current_status -> {target_status, ...}
# Canonical path: queued -> sent -> delivered -> read
# Failure path:   queued -> failed, sent -> failed (error details required)
# Terminal:       read, failed (no further transitions)
MESSAGE_STATE_MACHINE: Dict[str, set] = {
    "queued": {"sent", "failed"},
    "sent": {"delivered", "read", "failed"},
    "delivered": {"read"},
    "read": set(),
    "failed": set(),
}

# Allowed inbound values for a status query filter (unknown -> 4002 / 422).
VALID_FILTER_STATUSES = set(MESSAGE_STATE_MACHINE)

# ---------------------------------------------------------------------------


class MessageResourceNotFound(Exception):
    """4001 — a referenced resource does not exist (conversation/account/message)."""


class MessageParameterError(Exception):
    """4002 — input validation failed."""


class IllegalStateTransition(Exception):
    """4003 — the requested status transition is not allowed by the state machine."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_filter_domains(direction: Optional[str], status: Optional[str], channel: Optional[str]) -> None:
    """4002 on out-of-domain filter values (defensive: routers also 422 these)."""
    from app.db.models.messages import MESSAGE_DIRECTIONS

    if direction is not None and direction not in MESSAGE_DIRECTIONS:
        raise MessageParameterError(f"direction must be one of: {', '.join(MESSAGE_DIRECTIONS)}")
    if status is not None and status not in VALID_FILTER_STATUSES:
        raise MessageParameterError(f"status must be one of: {', '.join(sorted(VALID_FILTER_STATUSES))}")
    if channel is not None and channel not in MESSAGE_CHANNELS:
        raise MessageParameterError(f"channel must be one of: {', '.join(MESSAGE_CHANNELS)}")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MessageService:
    """Channel-message service (P5MSG-02)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- helpers ----------

    async def _log_transition(
        self,
        message_id: UUID,
        from_status: str,
        to_status: str,
        extra: Optional[dict] = None,
    ) -> None:
        """Record one ExecutionLog row for a message delivery transition.

        The ExecutionLog (execution_type=``message_status``) is the **single
        source of truth** for the message state-transition audit trail
        (ADR-017). The per-row ``messages.receipts`` JSONB is *not* written
        here anymore — it is a deprecated, read-only legacy column; the full
        receipt entry is projected from these log rows in
        :meth:`get_receipt`.

        Secrets never appear: only ids, statuses, channel, source, the
        provider error dict (on failure) and the provider message id.
        """
        extra = extra or {}
        log = ExecutionLog(
            execution_type="message_status",
            trigger_type="event" if extra.get("source") == "provider" else "manual",
            status="failed" if to_status == "failed" else "success",
            started_at=_utcnow(),
            finished_at=_utcnow(),
            input_params={
                "message_id": str(message_id),
                "from": from_status,
                "to": to_status,
                "source": extra.get("source", "manual"),
                # Full failure dict (lossless) so the SoT projection can
                # rebuild every receipt entry without the per-row JSONB.
                "error": extra.get("error"),
                "provider_message_id": extra.get("provider_message_id"),
                # Optional context carried by the enqueue row.
                "channel": extra.get("channel"),
                "conversation_id": extra.get("conversation_id"),
                "account_id": extra.get("account_id"),
            },
            output_result={"ok": to_status != "failed"},
            error_message=(extra.get("error") or {}).get("message")
            if to_status == "failed"
            else None,
        )
        self.db.add(log)

    async def _project_receipts(self, message: ChannelMessage) -> List[MessageReceipt]:
        """Project the receipt audit trail for *message* from the ExecutionLog
        SoT (ADR-017).

        The authoritative trail is the ``execution_log`` rows with
        ``execution_type='message_status'`` and ``input_params.message_id``
        matching *message*. The initial enqueue row (``to='queued'``) is the
        *creation* of the record, not a delivery/read receipt, so it is
        excluded — ``queued`` is never a transition target (it is only the
        initial state), which makes the filter exact and stable for both
        legacy and post-ADR-017 rows. The deprecated ``messages.receipts``
        JSONB is **not** consulted.
        """
        from sqlalchemy import select as _select

        rows = (
            await self.db.execute(
                _select(ExecutionLog)
                .where(
                    ExecutionLog.execution_type == "message_status",
                    ExecutionLog.input_params["message_id"].as_string() == str(message.id),
                    ExecutionLog.is_deleted == False,  # noqa: E712
                )
                .order_by(ExecutionLog.started_at.asc(), ExecutionLog.id.asc())
            )
        ).scalars().all()

        receipts: List[MessageReceipt] = []
        for log in rows:
            params = log.input_params or {}
            to_status = params.get("to")
            if to_status == "queued":
                continue  # the enqueue row: creation, not a receipt transition
            at_val = log.started_at
            if isinstance(at_val, str):
                try:
                    at_val = datetime.fromisoformat(at_val)
                except ValueError:
                    at_val = None
            receipts.append(
                MessageReceipt(
                    status=to_status,
                    at=at_val,
                    source=params.get("source", "manual"),
                    error=params.get("error"),
                    provider_message_id=params.get("provider_message_id"),
                )
            )
        return receipts

    def _publish_event(
        self,
        kind: str,
        message: ChannelMessage,
        status: str,
        extra: Optional[Dict[str, object]] = None,
    ) -> Optional[int]:
        """P5MSG-D4: push a channel-message event onto the realtime hub.

        Called after a successful commit from ``send_message`` /
        ``update_status`` so live SSE subscribers see new messages and
        delivery-state changes *automatically* — the main user-flow
        "实时接收" step previously had no auto event source (it only worked
        via the manual ``POST /realtime/publish`` seam).

        Payload carries ids / status / channel / source only — never message
        text, PII or credentials (ARCHITECTURE rule #16).

        Dedup identity is ``{kind}:{message_id}:{status}`` so a producer
        that republishes the *same* transition (e.g. an idempotent
        re-flush, or a delivery retry that lands the identical
        ``queued->sent`` hop) is not pushed twice — the hub drops the
        duplicate. Distinct transitions on the same message get distinct
        keys and are all delivered.

        Best-effort: ``publish_realtime_event`` never raises (a hub
        failure is logged, not propagated), so the message operation is
        never lost because the push layer hiccuped.
        """
        payload: Dict[str, object] = {
            "message_id": str(message.id),
            "conversation_id": str(message.conversation_id),
            "channel": message.channel,
            "status": status,
        }
        if extra:
            payload.update(extra)
        dedup_id = f"{kind}:{message.id}:{status}"
        return publish_realtime_event(
            kind,
            conversation_id=str(message.conversation_id),
            payload=payload,
            dedup_id=dedup_id,
        )

    # ---------- read ----------

    async def list_messages(
        self,
        page: int = 1,
        page_size: int = 20,
        conversation_id: Optional[UUID] = None,
        channel: Optional[str] = None,
        direction: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Tuple[List[ChannelMessage], int, int, int]:
        """Paginated message list. Returns (items, total, page, page_size)."""
        _validate_filter_domains(direction, status, channel)

        query = select(ChannelMessage).where(ChannelMessage.is_deleted == False)
        if conversation_id is not None:
            query = query.where(ChannelMessage.conversation_id == conversation_id)
        if channel is not None:
            query = query.where(ChannelMessage.channel == channel)
        if direction is not None:
            query = query.where(ChannelMessage.direction == direction)
        if status is not None:
            query = query.where(ChannelMessage.status == status)
        if start_time is not None:
            query = query.where(ChannelMessage.created_at >= start_time)
        if end_time is not None:
            query = query.where(ChannelMessage.created_at <= end_time)

        total = (
            await self.db.execute(
                select(func.count()).select_from(query.subquery())
            )
        ).scalar_one()

        items = (
            await self.db.execute(
                query.order_by(ChannelMessage.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total, page, page_size

    async def get_message(self, message_id: UUID) -> ChannelMessage:
        result = await self.db.execute(
            select(ChannelMessage).where(
                ChannelMessage.id == message_id,
                ChannelMessage.is_deleted == False
            )
        )
        message = result.scalar_one_or_none()
        if message is None:
            raise MessageResourceNotFound(f"Message not found: {message_id}")
        return message

    async def _lock_message(self, message_id: UUID) -> ChannelMessage:
        """Fetch the message row holding a row-level lock (``FOR UPDATE``).

        P5MSG-D1 (P1 concurrency defect): without a lock, two racing
        transitions on the same row (e.g. ``queued->sent`` vs
        ``queued->failed``) both read ``status=queued``, both pass the
        state-machine check, and the later commit silently overwrites the
        earlier one — a lost update that also drops one receipt and one
        execution_log row. Locking the row forces the second transaction to
        re-read the *post-commit* status (Postgres READ COMMITTED re-evaluates
        a FOR UPDATE read after a conflicting commit), so the transitions
        serialize: exactly one is the first hop and the other either makes the
        legal next hop or is rejected as an illegal transition.

        NOTE: ``populate_existing=True`` is mandatory — without it, a session
        that already holds the row in its identity map (e.g. a long-lived or
        shared session, or reuse of the session that enqueued the message)
        gets the *cached* object back with stale column values, silently
        reproducing the lost update at the ORM layer even though the DB lock
        is held.
        """
        result = await self.db.execute(
            select(ChannelMessage)
            .where(
                ChannelMessage.id == message_id,
                ChannelMessage.is_deleted == False
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        message = result.scalar_one_or_none()
        if message is None:
            raise MessageResourceNotFound(f"Message not found: {message_id}")
        return message

    # ---------- send (enqueue) ----------

    async def _resolve_account_platform_code(self, account_id: UUID) -> Optional[str]:
        """Return the platform code of *account_id*, or None when the
        account does not exist. Used to reject unknown accounts early
        (4001) instead of letting the FK raise a 500."""
        result = await self.db.execute(
            select(Account.id, Platform.code)
            .join(Platform, Account.platform_id == Platform.id)
            .where(Account.id == account_id, Account.is_deleted == False)
        )
        row = result.one_or_none()
        return row[1] if row else None

    async def send_message(self, data: MessageSendRequest) -> ChannelMessage:
        """Enqueue an outbound channel message (status=queued).

        Phase-1 resource-layer validation:
          * conversation must exist (4001);
          * when account_id is given it must exist and its platform code
            must match the requested channel (4002 on mismatch).
        """
        conv = (
            await self.db.execute(
                select(Conversation.id).where(
                    Conversation.id == data.conversation_id,
                    Conversation.is_deleted == False,
                )
            )
        ).scalar_one_or_none()
        if conv is None:
            raise MessageResourceNotFound(f"Conversation not found: {data.conversation_id}")

        if data.account_id is not None:
            platform_code = await self._resolve_account_platform_code(data.account_id)
            if platform_code is None:
                raise MessageResourceNotFound(f"Account not found: {data.account_id}")
            # "web" is the platform channel — no account binding required.
            if data.channel != "web" and platform_code != data.channel:
                raise MessageParameterError(
                    f"Account {data.account_id} is bound to platform '{platform_code}', "
                    f"which does not match requested channel '{data.channel}'"
                )

        now = _utcnow()
        message = ChannelMessage(
            conversation_id=data.conversation_id,
            account_id=data.account_id,
            agent_id=data.agent_id,
            channel=data.channel,
            direction=data.direction,
            status="queued",
            content=data.content,
            provider_message_id=data.provider_message_id,
        )
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)

        await self._log_transition(
            message.id,
            from_status="(none)",
            to_status="queued",
            extra={
                "channel": data.channel,
                "conversation_id": str(data.conversation_id),
                "account_id": str(data.account_id) if data.account_id else None,
            },
        )
        await self.db.commit()
        logger.info(
            "message queued id=%s conversation=%s channel=%s account=%s",
            message.id, data.conversation_id, data.channel, data.account_id,
        )
        # P5MSG-D4: auto-broadcast the enqueue to live SSE subscribers so the
        # main user-flow "实时接收" step receives channel_message.created without
        # a manual /realtime/publish seam. Payload carries ids/status/channel
        # only (no text/PII). Best-effort: never raises.
        self._publish_event(
            "channel_message.created",
            message,
            status="queued",
            extra={
                "direction": message.direction,
                "account_id": str(data.account_id) if data.account_id else None,
            },
        )
        return message

    # ---------- status / receipts ----------

    async def update_status(
        self, message_id: UUID, data: MessageStatusUpdateRequest
    ) -> ChannelMessage:
        """Apply one delivery-state transition.

        * illegal transitions raise IllegalStateTransition (4003);
        * ``failed`` requires ``error`` details (schema-enforced, 422);
        * ``sent`` stamps sent_at, ``delivered``/``read`` stamp received_at;
        * every accepted transition is recorded **once** in the ExecutionLog
          SoT (ADR-017) — the deprecated per-row ``receipts`` JSONB is no
          longer written; ``last_receipt_at`` remains a lightweight
          denormalized "when last acknowledged" scalar.

        Concurrency (P5MSG-D1): the row is fetched under ``FOR UPDATE`` so
        racing transitions serialize instead of silently overwriting each
        other (lost update). The state-machine check therefore runs against
        the *current* committed status, not a stale pre-commit snapshot.
        """
        message = await self._lock_message(message_id)
        current = message.status
        target = data.status

        if target not in MESSAGE_STATE_MACHINE.get(current, set()):
            raise IllegalStateTransition(
                f"Illegal state transition: '{current}' -> '{target}'"
            )

        now = _utcnow()
        message.status = target
        if target == "sent":
            message.sent_at = now
        elif target in ("delivered", "read"):
            message.received_at = now
        if target == "failed":
            message.error = data.error
        if data.provider_message_id is not None:
            message.provider_message_id = data.provider_message_id

        # ADR-017: the ExecutionLog is the sole audit-trail writer. The
        # deprecated per-row ``receipts`` JSONB is no longer appended; only
        # the lightweight denormalized ``last_receipt_at`` scalar is stamped.
        message.last_receipt_at = now

        self.db.add(message)
        await self._log_transition(
            message.id,
            current,
            target,
            extra={
                "source": data.source,
                # Full lossless failure dict + provider id so get_receipt can
                # project the receipt trail from the SoT without the JSONB.
                "error": data.error if target == "failed" else None,
                "provider_message_id": data.provider_message_id,
            },
        )
        await self.db.commit()
        await self.db.refresh(message)

        level = logging.WARNING if target == "failed" else logging.INFO
        logger.log(
            level,
            "message status %s id=%s '%s' -> '%s' source=%s",
            "transitioned", message.id, current, target, data.source,
        )
        # P5MSG-D4: auto-broadcast the delivery-state change to live SSE
        # subscribers. The channel_delivery_service moves queued->sent/failed
        # through the same update_status path, so this single seam covers the
        # API /status endpoint AND the provider delivery loop. Payload carries
        # ids/status/channel/source only (no text/PII). Best-effort: never
        # raises. The dedup key ({kind}:{message_id}:{status}) means a retried,
        # identical transition is not pushed twice.
        self._publish_event(
            "channel_message.status",
            message,
            status=target,
            extra={
                "source": data.source,
                "from_status": current,
                "provider_message_id": message.provider_message_id,
            },
        )
        return message

    async def get_receipt(self, message_id: UUID) -> MessageReceiptResponse:
        message = await self.get_message(message_id)
        # ADR-017: the receipt trail is projected from the ExecutionLog SoT
        # (execution_type='message_status'), not the deprecated per-row
        # ``receipts`` JSONB. ``last_receipt_at`` remains a lightweight
        # denormalized scalar carried on the row for cheap API reads.
        receipts = await self._project_receipts(message)
        return MessageReceiptResponse(
            message_id=message.id,
            status=message.status,
            error=message.error,
            provider_message_id=message.provider_message_id,
            sent_at=message.sent_at,
            received_at=message.received_at,
            last_receipt_at=message.last_receipt_at,
            receipts=receipts,
        )
