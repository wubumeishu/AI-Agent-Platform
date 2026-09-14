"""AI provider layer (P1-003 deliverable).

Exposes the unified provider surface consumed by the conversations router::

    from app.services.ai import AIAgentService, TokenUsage
    from app.services.ai import ProviderAdapter, get_provider
    from app.services.ai.exceptions import ProviderError, ...

``provider_adapters`` is the P1-001 delivery ported verbatim-ish onto
``httpx`` (no OpenAI/Anthropic SDKs in the venv, decision #8).  ``config``
is the read-only configuration side (decision #3).  ``agent_service`` wraps
provider selection, model choice, token accounting, rate-limit backoff and
provider degradation for the SSE + non-stream chat endpoints (decisions
#4-#6).
"""
from app.services.ai.agent_service import AIAgentService, AgentResult, TokenUsage
from app.services.ai.exceptions import (
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.services.ai.provider_adapters import (
    AnthropicProvider,
    LocalProvider,
    OpenAIProvider,
    ProviderAdapter,
    get_provider,
)

__all__ = [
    # agent service
    "AIAgentService",
    "AgentResult",
    "TokenUsage",
    # exceptions (kept re-exported so ``app.providers`` import chain holds)
    "ProviderError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RateLimitError",
    # adapters
    "ProviderAdapter",
    "OpenAIProvider",
    "AnthropicProvider",
    "LocalProvider",
    "get_provider",
    # submodules
    "exceptions",
    "config",
    "provider_adapters",
    "agent_service",
]
