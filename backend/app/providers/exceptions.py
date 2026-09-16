"""Provider-layer exceptions.

A small, dependency-free hierarchy shared by all LLM / AI providers in
``app/providers`` so callers (intent service, decision engine, routers)
can catch a *single* family of errors instead of provider-specific ones::

    ProviderError                 base for all provider failures
      ├─ ProviderUnavailableError  provider not configured / no API key
      ├─ ProviderTimeoutError      upstream call timed out
      └─ RateLimitError            upstream HTTP 429

Callers that want to fall back gracefully should catch ``ProviderError``
(the base class) — this covers every provider failure mode.
"""
from __future__ import annotations

from typing import Optional


class ProviderError(Exception):
    """Base class for all provider-layer errors.

    Carries an optional ``message`` so routers can surface a concise
    detail (e.g. 502 ``AI provider error: {exc.message}``) without
    re-parsing the exception string.
    """

    def __init__(self, message: str = "", *, detail: Optional[str] = None):
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__
        self.detail = detail


class ProviderUnavailableError(ProviderError):
    """The provider is not configured or cannot be reached at all.

    Typical cause: no API key in the environment / config. This is a
    *first-class* degraded state — callers fall back to their rule-based
    path instead of crashing or spamming an error log line.
    """


class ProviderTimeoutError(ProviderError):
    """The upstream provider call timed out."""


class RateLimitError(ProviderError):
    """The upstream provider returned HTTP 429 (rate limited)."""


__all__ = [
    "ProviderError",
    "ProviderUnavailableError",
    "ProviderTimeoutError",
    "RateLimitError",
]
