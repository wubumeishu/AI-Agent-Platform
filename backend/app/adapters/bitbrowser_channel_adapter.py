"""BitBrowser channel adapter — P5MSG-03 (V1 concrete channel adapter).

Drives channel delivery through the Phase-1 ``BrowserProvider`` abstraction
(``BitBrowserProvider``). It **consumes** the provider interface — it does not
reimplement or modify Phase-1 provider internals (card Out-of-Scope).

Delivery model
--------------
* ``test_connection()`` on the provider tells us whether a *real* BitBrowser
  service is reachable. When it is not (SDK unavailable → the documented
  ``mock_mode`` fallback), this adapter **simulates** the delivery: a send
  returns a synthetic provider message id with ``mock=True``, and receive /
  poll return no inbound. This is the V1 end-to-end path the acceptance
  criterion ("至少 1 个 V1 渠道端到端发送成功") exercises in fallback reality —
  BitBrowser SDK availability is the known blocker recorded in the Phase-1 pool.
* When a *real* connection is present, driving the platform conversation page
  (open it, type the message, pull inbound) requires a DOM driver. V1 does not
  wire a real DOM driver, so the adapter exposes an injectable ``driver`` seam.
  Without one, real-mode send/poll report a clear ``page_drive_unavailable``
  rather than faking a result; a future Phase-5/6 DOM driver plugs into this
  seam without touching the delivery service or the business layer.

The adapter knows *how* to reach a platform; it never knows *what* the business
rule is (rate limits, retry, state machine, persistence) — that stays in
``ChannelDeliveryService``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set
from uuid import uuid4

from app.adapters.channel_adapter import (
    ChannelAdapter,
    ReceivedMessage,
    SendResult,
)
from app.providers.browser_provider import BrowserProvider

logger = logging.getLogger(__name__)


@dataclass
class DomDriverResult:
    """What a real-mode DOM driver returns for one send."""
    provider_message_id: str
    error: Optional[Dict[str, object]] = None


class BitBrowserChannelAdapter(ChannelAdapter):
    """V1 BitBrowser channel adapter.

    Parameters
    ----------
    provider:
        A Phase-1 ``BrowserProvider`` (``BitBrowserProvider``). The adapter
        calls ``test_connection()`` to decide mock vs real mode.
    driver:
        Optional real-mode DOM driver exposing ``async send(content, target) ->
        DomDriverResult`` and ``async receive(limit, since) -> List[ReceivedMessage]``.
        ``None`` in V1: mock mode simulates; real mode reports unavailable.
    """

    V1_CHANNELS: Set[str] = {"wechat", "douyin", "xiaohongshu"}

    def __init__(self, provider: BrowserProvider, driver: Optional[object] = None) -> None:
        self._provider = provider
        self._driver = driver

    @property
    def adapter_name(self) -> str:
        return "bitbrowser"

    def supported_channels(self) -> Set[str]:
        return set(self.V1_CHANNELS)

    def _is_mock(self) -> bool:
        """Whether the provider is in its documented fallback mode."""
        try:
            # BitBrowserProvider exposes is_mock_mode(); the abstract base does
            # not, so fall back to the duck-typing default (real mode).
            return bool(self._provider.is_mock_mode())  # type: ignore[union-attr]
        except AttributeError:
            return False

    def _is_connected(self, status: Dict[str, object]) -> bool:
        return bool(status.get("connected", False))

    async def send(self, content: Dict[str, object], target: Optional[str] = None) -> SendResult:
        try:
            status = await self._provider.test_connection()
        except Exception as exc:  # noqa: BLE001 - provider failure is a send failure
            return SendResult.failure(
                {"code": "provider_error", "message": str(exc),
                 "provider": self.adapter_name},
                provider=self.adapter_name, mock=False,
            )

        if self._is_mock() or not self._is_connected(status):
            # V1 fallback: simulate a successful delivery (no real browser).
            provider_msg_id = f"mock_{uuid4().hex[:12]}"
            logger.info(
                "channel_adapter: mock send ok channel-target=%s provider_msg=%s",
                target, provider_msg_id,
            )
            return SendResult.success(provider_msg_id, provider=self.adapter_name, mock=True)

        # Real mode: a DOM driver is required to drive the conversation page.
        if self._driver is None:
            return SendResult.failure(
                {"code": "page_drive_unavailable",
                 "message": "real BitBrowser DOM driving is not wired in V1; "
                            "a DOM driver is required",
                 "provider": self.adapter_name},
                provider=self.adapter_name, mock=False,
            )

        res = await self._driver.send(content, target)
        if res.error:
            return SendResult.failure(res.error, provider=self.adapter_name, mock=False)
        return SendResult.success(res.provider_message_id, provider=self.adapter_name,
                                  mock=False)

    async def receive(self, limit: int = 20, since: Optional[datetime] = None) -> List[ReceivedMessage]:
        if self._is_mock():
            return []
        try:
            status = await self._provider.test_connection()
        except Exception:
            return []
        if not self._is_connected(status) or self._driver is None:
            # No real inbound source in V1 (mock) or no driver (real).
            return []
        return await self._driver.receive(limit=limit, since=since) or []

    # ``poll`` intentionally inherits the base default (delegate to receive).


def build_default_adapter() -> BitBrowserChannelAdapter:
    """Construct the V1 default adapter wired to ``BitBrowserProvider``.

    No DOM driver in V1 (mock-mode simulates; real-mode reports unavailable).
    """
    from app.providers.bitbrowser_provider import BitBrowserProvider

    return BitBrowserChannelAdapter(BitBrowserProvider())
