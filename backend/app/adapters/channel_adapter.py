"""Channel adapter abstraction — P5MSG-03 (platform adapters, not business logic).

``ChannelAdapter`` is the platform-level abstraction the delivery service
consumes. Business logic lives in ``ChannelDeliveryService``; a specific
platform's *how* (open the conversation page in a browser profile, type the
message, pull inbound) lives behind this interface. This keeps platform-specific
code (X / wechat / douyin / xiaohongshu ...) isolated from the CRM/message
business services, per the platform-integration rule.

The V1 concrete implementation (``BitBrowserChannelAdapter``) drives delivery
through the Phase-1 ``BrowserProvider`` (``BitBrowserProvider``) — it *consumes*
the provider's interface, it does not reimplement it (Out-of-Scope: modifying
Phase-1 provider internals).

Result / inbound types are framework-agnostic dataclasses so the business layer
and any future adapter share one vocabulary.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class SendResult:
    """Outcome of one outbound delivery attempt."""
    ok: bool
    status: str  # "sent" on success, "failed" on error
    provider_message_id: Optional[str] = None
    error: Optional[Dict[str, object]] = None
    mock: bool = False  # True when the delivery was simulated (provider mock mode)
    provider: str = "bitbrowser"

    @classmethod
    def success(cls, provider_message_id: str, provider: str = "bitbrowser",
                mock: bool = False) -> "SendResult":
        return cls(ok=True, status="sent", provider_message_id=provider_message_id,
                   mock=mock, provider=provider)

    @classmethod
    def failure(cls, error: Dict[str, object], provider: str = "bitbrowser",
                mock: bool = False) -> "SendResult":
        return cls(ok=False, status="failed", error=error, mock=mock, provider=provider)


@dataclass
class ReceivedMessage:
    """One inbound message pulled from a platform via an adapter."""
    provider_message_id: str
    content: Dict[str, object]
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    provider: str = "bitbrowser"
    mock: bool = False


class ChannelAdapter(ABC):
    """Abstract channel adapter (send / receive / poll)."""

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Stable identifier (e.g. ``bitbrowser``)."""

    @abstractmethod
    def supported_channels(self) -> Set[str]:
        """Channel codes this adapter can deliver / poll for."""

    @abstractmethod
    async def send(self, content: Dict[str, object], target: Optional[str] = None) -> SendResult:
        """Deliver one outbound message on a platform conversation page.

        ``target`` is the peer/conversation identifier on the platform side
        (optional; the adapter may resolve it from the channel config).
        """

    @abstractmethod
    async def receive(self, limit: int = 20, since: Optional[datetime] = None) -> List[ReceivedMessage]:
        """Pull the most recent inbound messages (short poll)."""

    async def poll(self, limit: int = 20, since: Optional[datetime] = None) -> List[ReceivedMessage]:
        """Long-poll / repeated receive. Default: delegate to :meth:`receive`."""
        return await self.receive(limit=limit, since=since)


class ChannelAdapterRegistry:
    """Maps channel codes -> adapters. V1 registers only BitBrowserChannelAdapter.

    A channel with no registered adapter raises :class:`UnsupportedChannelError`
    (4002 in the delivery service) rather than silently no-op'ing.
    """

    def __init__(self) -> None:
        self._adapters: Dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        for ch in adapter.supported_channels():
            self._adapters[ch] = adapter

    def adapter_for(self, channel: str) -> ChannelAdapter:
        adapter = self._adapters.get(channel)
        if adapter is None:
            raise UnsupportedChannelError(
                f"No channel adapter registered for channel {channel!r}; "
                f"known: {sorted(self._adapters)}"
            )
        return adapter

    def known_channels(self) -> List[str]:
        return sorted(self._adapters)


class UnsupportedChannelError(Exception):
    """The channel has no registered adapter (4002 in the delivery service)."""
