"""P1-003 unified AI agent service — provider-call wrapper for conversations.

Wires the existing conversations SSE endpoint to the P1-001 provider layer:
provider selection, model choice, token accounting, rate-limit backoff and
provider degradation, per the orchestrator's P1-003-AI key decisions (#4-#6).
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

from app.services.ai import config as ai_config
from app.services.ai.exceptions import (
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)

__all__ = ["AIAgentService", "AgentResult", "TokenUsage"]


@dataclass
class TokenUsage:
    """Token accounting for one provider exchange."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def as_dict(self) -> Dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total": self.total,
        }


@dataclass
class AgentResult:
    """Outcome of one non-streaming :meth:`AIAgentService.generate_response`.

    Attribute access (not dict) so the router's non-stream handler can read
    ``result.content`` / ``result.usage`` / ``result.error`` directly.
    """

    content: str = ""
    provider: Optional[str] = None
    model: Optional[str] = None
    usage: Optional[TokenUsage] = None
    latency_ms: int = 0
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "provider": self.provider,
            "model": self.model,
            "usage": self.usage.as_dict() if self.usage else {},
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


# --------------------------------------------------------------------------- #
# adapter response envelope helpers
# --------------------------------------------------------------------------- #
def _envelope_content(envelope: Dict[str, Any]) -> str:
    """Assistant text from an adapter's non-streaming envelope."""
    choices = envelope.get("choices")
    if choices:
        return "".join((c.get("content") or "") for c in choices)
    return envelope.get("content") or ""


def _envelope_usage(envelope: Dict[str, Any]) -> Optional[TokenUsage]:
    """Provider-reported usage, or None when the provider does not report it."""
    usage = envelope.get("usage")
    if not usage:
        return None
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    if not (prompt or completion):
        return None
    return TokenUsage(prompt_tokens=prompt, completion_tokens=completion)


def _usage_from_lines(lines: List[str]) -> Optional[TokenUsage]:
    """Extract usage from SSE data lines (OpenAI stream_options / Anthropic)."""
    for line in reversed(lines):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            payload = json.loads(line[5:].strip())
        except (json.JSONDecodeError, ValueError):
            continue
        usage = payload.get("usage")
        if usage:
            prompt = int(usage.get("prompt_tokens") or 0)
            completion = int(usage.get("completion_tokens") or 0)
            if prompt or completion:
                return TokenUsage(
                    prompt_tokens=prompt, completion_tokens=completion
                )
    return None


def _estimate_tokens(text: str) -> int:
    """Local fallback estimate when the provider does not report usage."""
    return math.ceil(len(text or "") / 4)


# --------------------------------------------------------------------------- #
# SSE event builders — keep the pre-P1-003 event-shape contract
# --------------------------------------------------------------------------- #
def _event_chunk(content: str, index: int) -> Dict[str, Any]:
    return {"type": "chunk", "content": content, "index": index}


def _event_result(
    *,
    content: str,
    provider: Optional[str],
    model: Optional[str],
    usage: Optional[TokenUsage],
    latency_ms: int,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "type": "result",
        "accumulated_content": content,
        "provider": provider,
        "model": model,
        "usage": usage.as_dict() if usage else {},
        "latency_ms": latency_ms,
        "error": error,
    }


# --------------------------------------------------------------------------- #
# The agent service
# --------------------------------------------------------------------------- #
class AIAgentService:
    """Unified AI agent service for conversation responses.

    Selects a provider (explicit > configured chain > default), invokes it
    with the requested model, accounts for tokens (provider usage first,
    local estimate fallback) and handles errors per P1-003 decision #4:

    * ``ProviderError`` -> degrade to the next configured provider (at most
      2 switches);
    * ``RateLimitError`` -> exponential backoff retry (1s/2s/4s, max 3);
    * ``ProviderTimeoutError`` -> return what was received so far, flagged.

    No provider is configured -> :class:`ProviderUnavailableError`
    (never a silent mock).
    """

    MAX_PROVIDER_SWITCHES = 2
    MAX_RATE_RETRIES = 3

    def __init__(self, provider_names: Optional[List[str]] = None):
        # The router constructs ``AIAgentService()`` (no args); tests may pass
        # provider_names to pin the degradation chain without touching config.
        self._provider_names = provider_names

    # ------------------------------------------------------------------ #
    # provider resolution
    # ------------------------------------------------------------------ #
    def _providers_chain(self, requested: Optional[str]) -> List[Any]:
        """Ordered provider list to try:

        * requested provider first (explicit ``provider=`` override);
        * the configured default provider next (auto-selected, decision #4);
        * remaining configured providers in config order.

        Returns [] when nothing is configured.
        """
        chain: List[Any] = []
        if requested:
            try:
                chosen = ai_config.get_provider(requested)
            except Exception:
                chosen = None
            if chosen is not None:
                chain.append(chosen)
        else:
            default = self._default_provider()
            if default is not None:
                chain.append(default)
        names = (
            self._provider_names
            if self._provider_names is not None
            else ai_config.configured_provider_names()
        )
        for name in names:
            try:
                adapter = ai_config.get_provider(name)
            except Exception:
                adapter = None
            if adapter is not None and adapter.provider_name not in (
                p.provider_name for p in chain
            ):
                chain.append(adapter)
        return chain

    def _default_provider(self) -> Optional[Any]:
        return ai_config.get_default_provider()

    # ------------------------------------------------------------------ #
    # non-streaming generation
    # ------------------------------------------------------------------ #
    async def generate_response(
        self,
        conversation: Any,
        messages: List[Dict[str, str]],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        stream: bool = False,
    ) -> AgentResult:
        """Generate a response. Returns an :class:`AgentResult` with attributes
        ``content``, ``provider``, ``model``, ``usage`` (TokenUsage|None),
        ``latency_ms``, ``error`` (str|None).

        Raises :class:`ProviderUnavailableError` when no provider is usable,
        or after every provider in the chain has failed.
        """
        chain = self._providers_chain(provider)
        if not chain:
            fallback = self._default_provider()
            chain = [fallback] if fallback else []
        if not chain:
            raise ProviderUnavailableError("no AI provider available")

        last_error: Optional[ProviderError] = None
        switches = 0
        for adapter in chain:
            try:
                result = await self._call_non_stream(adapter, messages, model)
                usage = _envelope_usage(result)
                if usage is None:
                    usage = TokenUsage(
                        completion_tokens=_estimate_tokens(
                            _envelope_content(result)
                        )
                    )
                return AgentResult(
                    content=_envelope_content(result),
                    provider=adapter.provider_name,
                    model=model or result.get("model"),
                    usage=usage,
                    latency_ms=result.get("_latency_ms", 0),
                    error=None,
                )
            except RateLimitError as exc:
                last_error = exc
                recovered = await self._retry_rate_limited(
                    adapter, messages, model
                )
                if recovered:
                    result = await self._call_non_stream(adapter, messages, model)
                    usage = _envelope_usage(result) or TokenUsage(
                        completion_tokens=_estimate_tokens(
                            _envelope_content(result)
                        )
                    )
                    return AgentResult(
                        content=_envelope_content(result),
                        provider=adapter.provider_name,
                        model=model or result.get("model"),
                        usage=usage,
                        latency_ms=result.get("_latency_ms", 0),
                        error=None,
                    )
                # rate-limit not recovered -> fall through to next provider
            except ProviderTimeoutError as exc:
                return AgentResult(
                    content="",
                    provider=adapter.provider_name,
                    model=model,
                    usage=None,
                    latency_ms=0,
                    error=f"provider timeout: {exc.message}",
                )
            except ProviderError as exc:
                last_error = exc
                switches += 1
                if switches > self.MAX_PROVIDER_SWITCHES:
                    break
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = ProviderError(str(exc), provider=adapter.provider_name)
                switches += 1
                if switches > self.MAX_PROVIDER_SWITCHES:
                    break
                continue
        raise ProviderUnavailableError(
            f"all providers failed: {last_error.message if last_error else 'none configured'}"
        )

    async def _retry_rate_limited(
        self, adapter: Any, messages: List[Dict[str, str]], model: Optional[str]
    ) -> bool:
        """Exponential backoff (1s/2s/4s, max 3 attempts). Returns True when a
        later probe succeeds; the caller re-invokes the full call."""
        delay = 1.0
        for _ in range(self.MAX_RATE_RETRIES):
            await asyncio.sleep(delay)
            try:
                await self._call_non_stream(adapter, messages, model, _probe=True)
                return True
            except RateLimitError:
                delay *= 2
                continue
            except ProviderError:
                return False
        return False

    async def _call_non_stream(
        self,
        adapter: Any,
        messages: List[Dict[str, str]],
        model: Optional[str],
        _probe: bool = False,
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        result = await adapter.chat(messages, model=model, stream=False)
        if not _probe:
            result = dict(result)
            result["_latency_ms"] = int((time.monotonic() - t0) * 1000)
        return result

    # ------------------------------------------------------------------ #
    # streaming generation
    # ------------------------------------------------------------------ #
    async def generate_stream(
        self,
        conversation: Any,
        messages: List[Dict[str, str]],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        timeout_s: float = 60.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chunks as ``chunk`` events, then a terminal ``result`` event.

        Yields: one ``chunk`` event per content piece, then exactly one
        ``result`` event carrying accumulated content, usage, provider, model,
        latency and (on failure) an ``error`` string.
        """
        chain = self._providers_chain(provider)
        if not chain:
            fallback = self._default_provider()
            chain = [fallback] if fallback else []
        if not chain:
            yield _event_result(
                content="",
                provider=None,
                model=model,
                usage=None,
                latency_ms=0,
                error="no AI provider available",
            )
            return

        last_error: Optional[str] = None
        switches = 0
        i = 0
        rate_recovered_at: int = -1  # provider index that already used a rate-limit recovery
        while i < len(chain):
            adapter = chain[i]
            try:
                async for ev in self._stream_adapter(adapter, messages, model, timeout_s):
                    yield ev
                return
            except RateLimitError as exc:
                last_error = f"rate limited ({exc.message})"
                # Bounded: at most ONE backoff recovery per provider, so a
                # flapping provider cannot loop forever (spec: backoff max 3,
                # degradation max 2).
                if i != rate_recovered_at and await self._retry_rate_limited(
                    adapter, messages, model
                ):
                    rate_recovered_at = i
                    continue  # retry the SAME provider once
                switches += 1
                if switches > self.MAX_PROVIDER_SWITCHES:
                    break
                i += 1
                continue
            except ProviderTimeoutError as exc:
                yield _event_result(
                    content="",
                    provider=adapter.provider_name,
                    model=model,
                    usage=None,
                    latency_ms=0,
                    error=f"provider timeout: {exc.message}",
                )
                return
            except ProviderError as exc:
                last_error = f"provider error ({exc.message})"
                switches += 1
                if switches > self.MAX_PROVIDER_SWITCHES:
                    break
                i += 1
        if last_error:
            yield _event_result(
                content="",
                provider=provider,
                model=model,
                usage=None,
                latency_ms=0,
                error=last_error,
            )

    async def _stream_adapter(
        self,
        adapter: Any,
        messages: List[Dict[str, str]],
        model: Optional[str],
        timeout_s: float,
    ) -> AsyncIterator[Dict[str, Any]]:
        t0 = time.monotonic()
        stream = await adapter.chat(messages, model=model, stream=True)
        accumulated: List[str] = []
        index = 0
        raw_lines: List[str] = []
        async for piece in stream:
            # Pieces may be raw SSE data lines (httpx adapters) or plain text.
            if isinstance(piece, str) and piece.strip().startswith("data:"):
                raw_lines.append(piece)
                try:
                    payload = json.loads(piece[5:].strip())
                except (json.JSONDecodeError, ValueError):
                    continue
                if payload.get("choices"):
                    delta = payload["choices"][0].get("delta", {})
                    text = delta.get("content") or ""
                    if text:
                        accumulated.append(text)
                        yield _event_chunk(text, index)
                        index += 1
                # usage lines carry no delta -> nothing to yield
            else:
                # Plain-text pieces (fakes / SDK-style adapters).
                accumulated.append(piece)
                yield _event_chunk(piece, index)
                index += 1

        text = "".join(accumulated)
        usage = _usage_from_lines(raw_lines)
        if usage is None:
            # Provider did not report usage -> estimate from content.
            usage = TokenUsage(completion_tokens=_estimate_tokens(text))
        latency_ms = int((time.monotonic() - t0) * 1000)
        yield _event_result(
            content=text,
            provider=adapter.provider_name,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            error=None,
        )

    # ------------------------------------------------------------------ #
    # message-metadata builder (P1-003 decision #5)
    # ------------------------------------------------------------------ #
    @staticmethod
    def build_message_metadata(
        *,
        status: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        usage: Optional[TokenUsage] = None,
        latency_ms: int = 0,
        stream: bool = False,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build the ``metadata_`` payload persisted on a Message.

        Shape: ``{"status": "pending|success|error", "provider", "model",
        "usage": {prompt_tokens, completion_tokens, total},
        "latency_ms", "stream", "error"?}``.
        """
        meta: Dict[str, Any] = {
            "status": status,
            "provider": provider,
            "model": model,
            "stream": stream,
            "latency_ms": latency_ms,
            "usage": usage.as_dict() if isinstance(usage, TokenUsage)
            else (dict(usage) if usage else {
                "prompt_tokens": 0, "completion_tokens": 0, "total": 0}),
        }
        # Card decision #5: ``token_count`` is the flat key alongside usage.
        usage_block = meta["usage"]
        meta["token_count"] = int(usage_block.get("total") or 0)
        if error:
            meta["error"] = error
        return meta
