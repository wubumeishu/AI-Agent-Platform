"""Channel delivery business service — P5MSG-03.

Business layer that *consumes* the Phase-1 ``BrowserProvider`` abstraction and
the ``ChannelAdapter`` platform interface to actually move a ``queued`` channel
message through delivery, applying the per-channel rate-limit + retry strategy
from the channel config. The platform-specific *how* lives in the adapter; this
service owns the *what* (rate gate, retry, state-machine advance, persistence),
kept out of the router (platform convention: API -> Service -> Data).

Wiring
------
* :class:`ChannelAdapter` (abstraction) via an injectable
  :class:`ChannelAdapterRegistry` — default wires the V1
  ``BitBrowserChannelAdapter``.
* :class:`ChannelRateLimiter` — per-channel hourly gate (injected; default is the
  process-level limiter).
* :class:`~app.services.message_service.MessageService` — P5MSG-02's stable
  delivery state machine (``queued -> sent`` / ``queued -> failed``), reused so
  every accepted transition is recorded exactly once in the ExecutionLog SoT
  (``execution_type='message_status'``), the P5MSG-02 way (ADR-017: the
  deprecated per-row ``receipts`` JSONB is no longer a second writer).

Error mapping mirrors P5MSG-02 business codes (4001 not-found, 4002 parameter,
4003 illegal transition); adapter/rate-limit failures become a ``failed``
transition with a structured ``error`` dict (never secrets).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.channel_adapter import (
    ChannelAdapter,
    ChannelAdapterRegistry,
    ReceivedMessage,
    SendResult,
    UnsupportedChannelError,
)
from app.db.models.messages import ChannelMessage
from app.db.models.channel_config import ChannelConfig
from app.services.channel_rate_limiter import ChannelRateLimiter, get_rate_limiter
from app.services.message_service import (
    IllegalStateTransition,
    MessageParameterError,
    MessageResourceNotFound,
    MessageService,
)

logger = logging.getLogger(__name__)


# Default delivery strategy used when a channel has no config row yet.
_DEFAULT_RATE_LIMIT_PER_HOUR = 60
_DEFAULT_RETRY_MAX_ATTEMPTS = 3
_DEFAULT_RETRY_BACKOFF_SECONDS = 5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChannelDeliveryError(Exception):
    """A delivery attempt could not be made (mapped to 4002 at the router)."""


class ChannelResourceNotFound(Exception):
    """The referenced message/config does not exist (4001 at the router)."""


class RateLimitedDelivery(ChannelDeliveryError):
    """The per-channel rate limit was exceeded for this attempt."""
    def __init__(self, channel: str, limit: int):
        self.channel = channel
        self.limit = limit
        super().__init__(f"channel {channel!r} is rate-limited at {limit}/h")


@dataclass
class DeliveryOutcome:
    """Result of one :meth:`ChannelDeliveryService.deliver_message` run.

    The persisted :class:`ChannelMessage` plus the adapter-level metadata
    (``mock`` / ``provider``) the message row does not carry, so the router can
    render the full ``ChannelDeliverResponse`` without re-inspecting the adapter.
    """
    message: ChannelMessage
    provider_message_id: Optional[str] = None
    error: Optional[Dict[str, object]] = None
    mock: bool = False
    provider: str = "bitbrowser"

    @property
    def delivered(self) -> bool:
        return self.message.status == "sent"


class ChannelDeliveryService:
    """Moves queued channel messages through delivery via a channel adapter."""

    def __init__(
        self,
        db: AsyncSession,
        registry: Optional[ChannelAdapterRegistry] = None,
        rate_limiter: Optional[ChannelRateLimiter] = None,
    ) -> None:
        self.db = db
        self._registry = registry or _default_registry()
        self._rate_limiter = rate_limiter or get_rate_limiter()
        # Reuse P5MSG-02's state machine / receipts / execution-log writer.
        self._messages = MessageService(db)

    # ------------------------------------------------------------------ config
    async def _load_config(
        self, channel: str, account_id: Optional[UUID]
    ) -> Optional[ChannelConfig]:
        """Find the live config for (channel, account). Account-agnostic lookups
        (account_id None) prefer an account-bound config only when one matches;
        otherwise fall back to an account-less config; else None (defaults)."""
        q = select(ChannelConfig).where(
            ChannelConfig.channel == channel,
            ChannelConfig.is_deleted == False,
        )
        if account_id is not None:
            rows = (await self.db.execute(q)).scalars().all()
            for cfg in rows:
                if cfg.account_id == account_id:
                    return cfg
            return rows[0] if rows else None
        q = q.where(ChannelConfig.account_id.is_(None))
        return (await self.db.execute(q)).scalars().first()

    async def _delivery_policy(
        self, channel: str, account_id: Optional[UUID]
    ) -> Dict[str, object]:
        cfg = await self._load_config(channel, account_id)
        if cfg is None:
            return {
                "rate_limit_per_hour": _DEFAULT_RATE_LIMIT_PER_HOUR,
                "retry_max_attempts": _DEFAULT_RETRY_MAX_ATTEMPTS,
                "retry_backoff_seconds": _DEFAULT_RETRY_BACKOFF_SECONDS,
                "enabled": True,
            }
        return {
            "rate_limit_per_hour": cfg.rate_limit_per_hour,
            "retry_max_attempts": cfg.retry_max_attempts,
            "retry_backoff_seconds": cfg.retry_backoff_seconds,
            "enabled": cfg.enabled,
        }

    @staticmethod
    def _rate_key(channel: str, account_id: Optional[UUID]) -> str:
        return f"channel:{channel}:{account_id or 'none'}"

    # ------------------------------------------------------------------ deliver
    async def deliver_message(
        self,
        message_id: UUID,
        *,
        attempt_backoff: Optional[int] = None,
    ) -> DeliveryOutcome:
        """Deliver one *queued* outbound message through its channel adapter.

        Steps: load message (must be queued + outbound) -> load per-channel
        policy -> rate gate -> retry loop calling ``adapter.send`` -> advance the
        P5MSG-02 state machine to ``sent`` (success) or ``failed`` (error
        recorded). ``attempt_backoff`` overrides the config backoff for tests /
        explicit callers; omitted uses the stored policy value.

        Returns a :class:`DeliveryOutcome` (the persisted message plus the
        adapter's ``mock`` / ``provider`` metadata). Rate-limited attempts are
        returned (not raised) as a ``failed`` outcome so the failure stays
        observable.
        """
        message = await self._messages.get_message(message_id)
        if message.status != "queued":
            # Not a delivery-eligible state: surface as a parameter error (4002)
            # rather than an illegal-transition 4003 — the caller targeted a
            # wrong lifecycle stage for auto-delivery.
            raise MessageParameterError(
                f"Message {message_id} is '{message.status}', expected 'queued' for delivery"
            )
        if message.direction != "out":
            raise MessageParameterError(
                f"Message {message_id} is inbound ('in'); only outbound messages are auto-delivered"
            )

        policy = await self._delivery_policy(message.channel, message.account_id)
        if not policy["enabled"]:
            raise ChannelDeliveryError(
                f"channel {message.channel!r} is disabled for delivery"
            )

        adapter = self._registry.adapter_for(message.channel)

        # ---- rate gate (rate limiting "takes effect"): a denied attempt is
        # marked failed with a structured rate-limited error, not retried.
        key = self._rate_key(message.channel, message.account_id)
        limit = int(policy["rate_limit_per_hour"])
        if not self._rate_limiter.allow(key, limit, _utcnow()):
            error = {
                "code": "rate_limited",
                "message": f"channel {message.channel!r} exceeded {limit} sends/hour",
                "limit_per_hour": limit,
            }
            await self._messages.update_status(message_id, _failed_request(error))
            logger.warning("delivery rate-limited message=%s channel=%s limit=%d/h",
                           message_id, message.channel, limit)
            msg = await self._messages.get_message(message_id)
            return DeliveryOutcome(message=msg, error=error, mock=False,
                                   provider=adapter.adapter_name)

        # ---- retry loop
        target = message.content.get("target") if isinstance(message.content, dict) else None
        max_attempts = max(1, int(policy["retry_max_attempts"]))
        backoff = attempt_backoff if attempt_backoff is not None else int(policy["retry_backoff_seconds"])
        backoff = max(0, backoff)

        last_error: Optional[Dict[str, object]] = None
        for attempt in range(1, max_attempts + 1):
            result: SendResult = await adapter.send(message.content, target)
            if result.ok:
                await self._messages.update_status(
                    message_id,
                    _sent_request(result.provider_message_id),
                )
                logger.info(
                    "delivered message=%s channel=%s attempt=%d mock=%s provider_msg=%s",
                    message.id, message.channel, attempt, result.mock,
                    result.provider_message_id,
                )
                msg = await self._messages.get_message(message_id)
                return DeliveryOutcome(
                    message=msg,
                    provider_message_id=result.provider_message_id,
                    mock=result.mock,
                    provider=result.provider or adapter.adapter_name,
                )

            last_error = result.error or {
                "code": "adapter_error",
                "message": "adapter returned a failure without detail",
            }
            # Back off between attempts (not after the last one).
            if attempt < max_attempts and backoff > 0:
                await asyncio.sleep(backoff)

        error = {
            **(last_error or {}),
            "code": (last_error or {}).get("code", "adapter_error"),
            "attempts": max_attempts,
        }
        await self._messages.update_status(message_id, _failed_request(error))
        logger.warning(
            "delivery failed message=%s channel=%s attempts=%d error=%s",
            message.id, message.channel, max_attempts, error.get("message"),
        )
        msg = await self._messages.get_message(message_id)
        return DeliveryOutcome(
            message=msg,
            provider_message_id=msg.provider_message_id,
            error=error,
            mock=False,
            provider=adapter.adapter_name,
        )

    # ------------------------------------------------------------------ inbound
    async def poll_inbound(
        self,
        channel: str,
        *,
        conversation_id: UUID,
        account_id: Optional[UUID] = None,
        limit: int = 20,
        since: Optional[datetime] = None,
    ) -> List[ChannelMessage]:
        """Pull inbound messages via the adapter and persist them as ``in``
        channel records (status ``queued``), mirroring the send path's shape.

        Dedup: an inbound provider message id already present in
        ``conversation_id`` is not inserted twice. Returns the newly created
        records (empty when the adapter has no inbound, e.g. mock mode).
        """
        adapter = self._registry.adapter_for(channel)
        received: List[ReceivedMessage] = await adapter.receive(limit=limit, since=since)
        if not received:
            return []

        # Dedup against already-stored provider ids for this conversation.
        existing = (
            await self.db.execute(
                select(ChannelMessage.provider_message_id).where(
                    ChannelMessage.conversation_id == conversation_id,
                    ChannelMessage.direction == "in",
                    ChannelMessage.provider_message_id.isnot(None),
                )
            )
        ).scalars().all()
        seen: Set[Optional[str]] = set(existing)

        created: List[ChannelMessage] = []
        for item in received:
            if item.provider_message_id in seen:
                continue
            record = ChannelMessage(
                conversation_id=conversation_id,
                account_id=account_id,
                channel=channel,
                direction="in",
                status="queued",
                content=item.content,
                provider_message_id=item.provider_message_id,
                received_at=item.received_at,
            )
            self.db.add(record)
            seen.add(item.provider_message_id)
            created.append(record)

        if created:
            await self.db.commit()
            for rec in created:
                await self.db.refresh(rec)
            logger.info(
                "inbound polled channel=%s conversation=%s new=%d",
                channel, conversation_id, len(created),
            )
        return created

    # ------------------------------------------------------------------ helpers
    def known_adapter_channels(self) -> List[str]:
        return self._registry.known_channels()


# ---------------------------------------------------------------------------
# request-builder helpers (keep the service readable; reuse P5MSG-02 schemas)
# ---------------------------------------------------------------------------
def _sent_request(provider_message_id: Optional[str]):
    from app.schemas.messages import MessageStatusUpdateRequest

    return MessageStatusUpdateRequest(
        status="sent", source="provider", provider_message_id=provider_message_id
    )


def _failed_request(error: Dict[str, object]):
    from app.schemas.messages import MessageStatusUpdateRequest

    return MessageStatusUpdateRequest(
        status="failed", source="provider", error=error
    )


def _default_registry() -> ChannelAdapterRegistry:
    from app.adapters.bitbrowser_channel_adapter import build_default_adapter

    registry = ChannelAdapterRegistry()
    registry.register(build_default_adapter())
    return registry
