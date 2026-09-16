"""AI provider adapters for the unified provider layer (P1-003).

Ported from the P1-001 (t_46a10182) delivery ``provider_adapters.py`` with one
documented adaptation: the original SDK-based transports (``openai`` /
``anthropic`` packages) are **not installed** in this project's venv, and the
task's decision #8 forbids adding dependencies.  Per the task's "interface
mismatch → report, then minimal change" clause, the transports are built on
``httpx`` (already a project dependency), which is exactly the contract
``app/providers/openai_provider.py`` documents ("built on httpx… No OpenAI
SDK and no new dependency").

What is preserved from P1-001:

* the ``ProviderAdapter`` abstract interface — ``chat()`` (non-stream returns a
  dict; stream=True returns an ``AsyncIterator[str]`` of content pieces),
  ``list_models()``, ``test_connection()``, ``provider_name``;
* the three concrete providers — OpenAI-compatible, Anthropic, and local
  (OpenAI-compatible, e.g. Ollama);
* the ``get_provider(name, api_key, base_url)`` factory and its behaviour
  (``local`` needs no key; unknown names raise ``ValueError``);
* the response envelope: non-streaming results are ``{"id", "model",
  "choices" | "content", "usage"}`` where ``usage`` is a dict with
  ``prompt_tokens`` / ``completion_tokens`` / ``total`` when the provider
  reports it.

Transport errors are normalised here (HTTP >= 400 → :class:`RateLimitError`
for 429 / 5xx throttle shapes, :class:`ProviderError` otherwise; network
timeouts → :class:`ProviderTimeoutError`) so callers can rely on the
exceptions from :mod:`app.services.ai.exceptions` uniformly.
"""
from __future__ import annotations

import asyncio
import json
import math
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.services.ai.exceptions import (
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
)

_DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _estimate_tokens(text: str) -> int:
    """Local fallback token estimate: ceil(len(text) / 4)."""
    return math.ceil(len(text or "") / 4)


def _classify_http_error(status_code: int, provider: str, body: str = ""):
    """Map an HTTP error status to the provider exception hierarchy."""
    if status_code == 429:
        return RateLimitError(
            f"rate limited by provider (HTTP 429): {body[:300]}",
            provider=provider,
        )
    detail = f"HTTP {status_code}"
    if body:
        detail += f": {body[:300]}"
    return ProviderError(detail, provider=provider)


class ProviderAdapter(ABC):
    """AI provider adapter base class.

    Concrete adapters implement :meth:`chat` (the only mandatory method —
    :meth:`list_models` / :meth:`test_connection` have safe defaults so test
    fakes and lightweight providers can omit them).
    """

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        stream: bool = False,
    ) -> Any:
        """Send a chat request.

        Args:
            messages: ``[{"role": "user|assistant|system", "content": "..."}]``
            model: model id; None → the adapter's default
            temperature: sampling temperature
            max_tokens: max generation length
            stream: when True, return an ``AsyncIterator[str]`` of content
                pieces; otherwise a dict envelope (see module docstring).
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable provider identifier (e.g. ``"openai"``)."""

    async def list_models(self) -> List[str]:
        """Available model ids (best effort; adapters may hardcode)."""
        return []

    async def test_connection(self) -> Dict[str, Any]:
        """Cheap connection check."""
        return {"success": False, "message": "not supported"}

    # -- shared transport helpers -------------------------------------------

    async def _post(self, url: str, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST with uniform error mapping. Returns the parsed JSON body."""
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(
                    f"request timed out: {self.provider_name}",
                    provider=self.provider_name,
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"network error: {exc}",
                    provider=self.provider_name,
                ) from exc
        if resp.status_code >= 400:
            raise _classify_http_error(resp.status_code, self.provider_name, resp.text)
        return resp.json()

    async def _post_stream_lines(
        self, url: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> AsyncIterator[str]:
        """POST a streaming chat request and yield raw SSE ``data:`` lines."""
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            try:
                async with client.stream(
                    "POST", url, json=payload, headers=headers
                ) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", "replace")
                        raise _classify_http_error(
                            resp.status_code, self.provider_name, body
                        )
                    async for line in resp.aiter_lines():
                        if line.strip():
                            yield line
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(
                    f"stream timed out: {self.provider_name}",
                    provider=self.provider_name,
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"stream network error: {exc}",
                    provider=self.provider_name,
                ) from exc


class OpenAIProvider(ProviderAdapter):
    """OpenAI-compatible chat-completions adapter (default: api.openai.com)."""

    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    @property
    def provider_name(self) -> str:
        return "openai"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        stream: bool = False,
    ) -> Any:
        resolved_model = model or self.DEFAULT_MODEL
        payload = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": bool(stream),
        }
        url = f"{self.base_url}/chat/completions"
        if not stream:
            body = await self._post(url, payload, self._headers())
            usage = body.get("usage")
            return {
                "id": body.get("id"),
                "model": body.get("model", resolved_model),
                "choices": [
                    {
                        "role": (c.get("message") or {}).get("role", "assistant"),
                        "content": (c.get("message") or {}).get("content", ""),
                    }
                    for c in body.get("choices", [])
                ],
                "usage": usage,
            }

        payload["stream_options"] = {"include_usage": True}

        async def _gen() -> AsyncIterator[str]:
            async for line in self._post_stream_lines(url, payload, self._headers()):
                yield line

        return _gen()

    async def list_models(self) -> List[str]:
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.get(
                    f"{self.base_url}/models", headers=self._headers()
                )
                if resp.status_code >= 400:
                    raise _classify_http_error(
                        resp.status_code, self.provider_name, resp.text
                    )
                return [m["id"] for m in resp.json().get("data", [])]
        except (ProviderError, httpx.HTTPError):
            return [self.DEFAULT_MODEL]

    async def test_connection(self) -> Dict[str, Any]:
        try:
            await self.list_models()
            return {"success": True, "message": "Connection successful"}
        except Exception as exc:  # noqa: BLE001 - adapter probe boundary
            return {"success": False, "message": str(exc)}


class AnthropicProvider(ProviderAdapter):
    """Anthropic messages API adapter (claude-3-* families)."""

    DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "Content-Type": "application/json",
        }

    def _split_system(
        self, messages: List[Dict[str, str]]
    ) -> tuple:
        """Anthropic takes system as a separate parameter."""
        system = next(
            (m["content"] for m in messages if m.get("role") == "system"), None
        )
        body = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages
            if m.get("role") in ("user", "assistant")
        ]
        return system, body

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        stream: bool = False,
    ) -> Any:
        resolved_model = model or self.DEFAULT_MODEL
        system, body = self._split_system(messages)
        payload: Dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "messages": body,
            "temperature": temperature,
            "stream": bool(stream),
        }
        if system:
            payload["system"] = system
        url = f"{self.base_url}/v1/messages"
        if not stream:
            data = await self._post(url, payload, self._headers())
            usage = data.get("usage")
            return {
                "id": data.get("id"),
                "model": resolved_model,
                "content": "".join(
                    blk.get("text", "") for blk in data.get("content", [])
                ),
                "usage": usage,
            }

        async def _gen() -> AsyncIterator[str]:
            async for line in self._post_stream_lines(url, payload, self._headers()):
                yield line

        return _gen()

    async def list_models(self) -> List[str]:
        # Anthropic has no models-list endpoint; return the known families.
        return [
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
            self.DEFAULT_MODEL,
        ]

    async def test_connection(self) -> Dict[str, Any]:
        try:
            await self.chat(
                [{"role": "user", "content": "hi"}],
                model="claude-3-haiku-20240307",
                max_tokens=8,
            )
            return {"success": True, "message": "Connection successful"}
        except Exception as exc:  # noqa: BLE001 - adapter probe boundary
            return {"success": False, "message": str(exc)}


class LocalProvider(ProviderAdapter):
    """Local OpenAI-compatible endpoint (e.g. Ollama at :11434).

    No API key required (defaults to a placeholder).  Token usage is
    estimated with ceil(len(text)/4) when the endpoint does not report it.
    """

    DEFAULT_MODEL = "llama-3.2-3b"
    KNOWN_MODELS = ["llama-3.2-3b", "qwen-2.5-7b", "mistral-7b", "phi-3-mini"]

    def __init__(self, api_key: str = "not-needed", base_url: Optional[str] = None):
        self.api_key = api_key or "not-needed"
        self.base_url = (base_url or "http://localhost:11434/v1").rstrip("/")

    @property
    def provider_name(self) -> str:
        return "local"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        stream: bool = False,
    ) -> Any:
        resolved_model = model or self.DEFAULT_MODEL
        payload = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": bool(stream),
        }
        url = f"{self.base_url}/chat/completions"
        if not stream:
            body = await self._post(url, payload, self._headers())
            usage = body.get("usage")
            if usage is None:
                text = "".join(
                    (c.get("message") or {}).get("content", "")
                    for c in body.get("choices", [])
                )
                usage = {
                    "prompt_tokens": _estimate_tokens(
                        " ".join(m.get("content", "") for m in messages)
                    ),
                    "completion_tokens": _estimate_tokens(text),
                    "total": 0,
                }
                usage["total"] = usage["prompt_tokens"] + usage["completion_tokens"]
            return {
                "id": body.get("id"),
                "model": body.get("model", resolved_model),
                "choices": [
                    {
                        "role": (c.get("message") or {}).get("role", "assistant"),
                        "content": (c.get("message") or {}).get("content", ""),
                    }
                    for c in body.get("choices", [])
                ],
                "usage": usage,
            }

        payload["stream_options"] = {"include_usage": True}

        async def _gen() -> AsyncIterator[str]:
            async for line in self._post_stream_lines(url, payload, self._headers()):
                yield line

        return _gen()

    async def list_models(self) -> List[str]:
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.get(f"{self.base_url}/models")
                if resp.status_code >= 400:
                    return self.KNOWN_MODELS
                return [m["id"] for m in resp.json().get("data", [])]
        except httpx.HTTPError:
            return self.KNOWN_MODELS

    async def test_connection(self) -> Dict[str, Any]:
        try:
            await self.list_models()
            return {"success": True, "message": "Local model connection successful"}
        except Exception as exc:  # noqa: BLE001 - adapter probe boundary
            return {"success": False, "message": f"Connection failed: {exc}"}


_ADAPTERS = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "local": LocalProvider,
}


def get_provider(
    provider_name: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ProviderAdapter:
    """Factory: build an adapter for the named provider.

    ``local`` does not require an API key.  Unknown names raise ``ValueError``
    (P1-001 contract).
    """
    if provider_name not in _ADAPTERS:
        raise ValueError(f"Unsupported provider: {provider_name}")
    if provider_name == "local":
        return _ADAPTERS[provider_name](api_key="not-needed", base_url=base_url)
    return _ADAPTERS[provider_name](api_key or "", base_url)
