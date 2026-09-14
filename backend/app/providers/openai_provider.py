"""OpenAI LLM provider for the intent / AI layer.

Lands the concrete ``OpenAIProvider`` consumed by
:mod:`app.services.intent_service` through a single, provider-agnostic
call contract::

    provider = OpenAIProvider()                     # env-configured
    resp = await provider.chat_completion(
        model="gpt-4o-mini",
        messages=[{"role": "system", ...}, {"role": "user", ...}],
        temperature=0.1,
    )
    text = resp.content

Transport is stdlib-adjacent ``httpx`` (already a project dependency, used
by the browser providers) — no new dependency is added and no OpenAI SDK.

Configuration (environment):
    OPENAI_API_KEY        enables the provider when set (any truthy value)
    OPENAI_BASE_URL       optional; defaults to https://api.openai.com/v1
                          (any OpenAI-compatible endpoint works)
    OPENAI_DEFAULT_MODEL  optional; default model for chat_completion()

Unavailability is a *first-class* state: when no API key is configured,
:meth:`OpenAIProvider.is_available` returns ``False`` and callers fall back
to their rule-based path instead of raising ``ModuleNotFoundError`` or
spamming an error log line on every request. This keeps the AI layer
provider-agnostic, testable, and quiet.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.providers.exceptions import (
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)

logger = logging.getLogger(__name__)


@dataclass
class LLMCompletion:
    """Result of a non-streaming chat completion.

    ``content`` is the model's text (the intent layer parses it as JSON);
    ``model`` is the resolved model id; ``raw`` is the full response dict
    (including ``usage``) for token accounting when needed.
    """

    content: str
    model: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None

    @property
    def usage(self) -> Optional[Dict[str, int]]:
        """Normalised usage block from the underlying response, or None."""
        return (self.raw or {}).get("usage")


class OpenAIProvider:
    """OpenAI-compatible LLM provider used by the intent layer.

    Wraps a plain HTTP ``chat/completions`` call so the intent service
    depends on a single :meth:`chat_completion` contract. Pass ``client``
    to inject a custom httpx-compatible transport (tests, custom local
    endpoints); otherwise an ``httpx.AsyncClient`` is created per call.
    """

    # Fast, cheap default model for classification; overridable per call.
    DEFAULT_MODEL = "gpt-4o-mini"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_TIMEOUT = 30.0

    def __init__(
        self,
        client: Optional[Any] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self._client = client
        self._model = model or os.environ.get("OPENAI_DEFAULT_MODEL") or None
        # Explicit constructor args win over the environment.
        self._api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        self._base_url = (
            base_url
            or os.environ.get("OPENAI_BASE_URL")
            or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self._timeout = timeout or self.DEFAULT_TIMEOUT

    # -- provider resolution -------------------------------------------------
    def is_available(self) -> bool:
        """Cheap, network-free check: is a usable LLM provider configured?

        True iff an API key is configured. Callers use this to skip the LLM
        path entirely in keyless deployments and stay on the rule-based
        fallback without raising.
        """
        return bool(self._api_key)

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def configured_model(self) -> str:
        return self._model or self.DEFAULT_MODEL

    # -- call contract ---------------------------------------------------------
    async def chat_completion(
        self,
        model: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMCompletion:
        """Run a non-streaming completion and return an :class:`LLMCompletion`.

        Raises :class:`ProviderUnavailableError` when no API key is
        configured, :class:`RateLimitError` on HTTP 429,
        :class:`ProviderTimeoutError` on timeout, and
        :class:`ProviderError` for any other transport/HTTP failure. The
        caller decides to fall back to rules and log at most once.
        """
        if not self._api_key:
            raise ProviderUnavailableError(
                "no LLM provider configured (OPENAI_API_KEY missing)"
            )

        resolved_model = model or self._model or self.DEFAULT_MODEL
        payload = {
            "model": resolved_model,
            "messages": messages or [],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"

        import httpx

        if self._client is not None:
            client = self._client
            close = False
        else:
            client = httpx.AsyncClient(timeout=self._timeout)
            close = True

        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"LLM request timed out after {self._timeout}s: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"LLM transport error: {exc}") from exc
        finally:
            if close:
                await client.aclose()

        if response.status_code == 429:
            raise RateLimitError(
                f"LLM rate limited (HTTP 429): {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"LLM HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        choices = data.get("choices") or [{}]
        content = (choices[0] or {}).get("content") or ""
        return LLMCompletion(
            content=content,
            model=data.get("model", resolved_model),
            raw=data,
        )
