"""Exception types for the unified AI provider layer (P1-003).

Hierarchy::

    Exception
     +-- ProviderError               # generic provider-layer failure
          +-- ProviderUnavailableError   # nothing usable is configured
          +-- ProviderConfigError        # explicitly requested but unknown
          +-- RateLimitError             # 429-style throttling
          +-- ProviderTimeoutError       # network/adapter timeout

All carry a plain-string ``message`` attribute (``str(exc)`` is stable and
user-facing-safe) plus the offending provider name when known.
"""
from __future__ import annotations

from typing import Optional


class ProviderError(Exception):
    """Base error for the AI provider layer."""

    def __init__(self, message: str, provider: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.provider = provider

    def __str__(self) -> str:
        if self.provider:
            return f"[{self.provider}] {self.message}"
        return self.message


class ProviderUnavailableError(ProviderError):
    """No usable AI provider is configured (or none could be resolved)."""

    def __init__(self, message: str = "no AI provider available"):
        super().__init__(message)


class ProviderConfigError(ProviderError):
    """An explicitly requested provider name is not in the configuration."""

    def __init__(self, provider: str):
        super().__init__(f"provider '{provider}' is not configured", provider=provider)


class RateLimitError(ProviderError):
    """The provider throttled the request; exponential backoff is advised."""


class ProviderTimeoutError(ProviderError):
    """The provider request timed out (partial stream content may exist)."""
