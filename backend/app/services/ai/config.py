"""Read side of the AI provider configuration (P1-003 decision #3).

This module ONLY reads; the write/manage REST endpoints live in the P1-001
standalone ``provider_manager.py`` app and are deliberately NOT ported here
(decision #3: keep that app standalone, don't merge into the main app).

Files (identical locations to P1-001 ``provider_manager.load_config`` /
``get_api_key``):

* ``~/.hermes/ai_providers.yaml`` —::

      default: openai            # optional top-level default provider name
      providers:
        openai:
          model: gpt-4o-mini
          base_url: https://api.openai.com/v1
        local:
          base_url: http://localhost:11434/v1

* ``~/.hermes/.env`` — one ``<PROVIDER>_API_KEY=...`` line per provider
  (uppercase provider name), same parsing rules as P1-001.

Environment overrides (for tests / CI):

* ``HERMES_CONFIG_DIR`` — base directory holding ``ai_providers.yaml`` and
  ``.env`` (defaults to ``~/.hermes``).
* ``HERMES_AI_DEFAULT_PROVIDER`` — override the configured default name.

Missing files are not an error: every lookup returns ``None`` (or ``[]``) so
callers degrade gracefully.  An unknown provider name requested via
:func:`get_provider` raises :class:`ProviderConfigError` (it is an explicit
request, not discovery).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.services.ai.exceptions import ProviderConfigError
from app.services.ai.provider_adapters import ProviderAdapter, get_provider

__all__ = [
    "config_path",
    "env_path",
    "load_config",
    "get_api_key",
    "configured_provider_names",
    "get_provider",
    "get_default_provider",
]


def config_path() -> Path:
    """Path of ``ai_providers.yaml`` (honours ``HERMES_CONFIG_DIR``)."""
    base = Path(os.environ.get("HERMES_CONFIG_DIR", Path.home() / ".hermes"))
    return base / "ai_providers.yaml"


def env_path() -> Path:
    """Path of the provider API-key ``.env`` file (honours ``HERMES_CONFIG_DIR``)."""
    base = Path(os.environ.get("HERMES_CONFIG_DIR", Path.home() / ".hermes"))
    return base / ".env"


def load_config() -> Dict[str, Any]:
    """Load ``ai_providers.yaml``; missing/unreadable file → empty config.

    Shape: ``{"providers": {name: {model?, base_url?}}, "default": name?}``.
    """
    path = config_path()
    if not path.exists():
        return {"providers": {}, "default": None}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (yaml.YAMLError, OSError):
        return {"providers": {}, "default": None}
    data.setdefault("providers", {})
    data.setdefault("default", None)
    return data


def get_api_key(provider: str) -> Optional[str]:
    """Read ``<PROVIDER>_API_KEY`` from the provider ``.env`` file.

    Mirrors P1-001 ``provider_manager.get_api_key``: first matching line wins,
    surrounding quotes stripped, value trimmed.
    """
    path = env_path()
    if not path.exists():
        return None
    prefix = f"{provider.upper()}_API_KEY="
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(prefix):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def configured_provider_names() -> List[str]:
    """Provider names present in the configuration, in file order."""
    return list((load_config().get("providers") or {}).keys())


def _build(provider: str, spec: Dict[str, Any]) -> ProviderAdapter:
    """Instantiate the adapter for one configured provider entry."""
    api_key = get_api_key(provider)
    # local needs no key; openai/anthropic work with an empty key too but
    # requests will fail auth — that surfaces as ProviderError, not here.
    return get_provider(
        provider,
        api_key=api_key,
        base_url=(spec or {}).get("base_url") or None,
    )


def get_provider(name: str) -> Optional[ProviderAdapter]:
    """Adapter for the named provider, or None when not configured.

    An explicitly requested *unknown* name is a configuration error — the
    distinction keeps accidental typos loud at the request layer while
    discovery-style lookups (default resolution, degradation chains) stay
    quiet.
    """
    providers = load_config().get("providers") or {}
    spec = providers.get(name)
    if spec is None:
        # Unknown name: only loud when it is neither a configured entry nor a
        # known adapter type (a supported type with no config is a legitimate
        # "nothing configured" discovery miss and stays quiet -> None).
        if name not in configured_provider_names() and not _known_types(name):
            raise ProviderConfigError(name)
        return None
    return _build(name, spec or {})


def _known_types(name: str) -> bool:
    """True when ``name`` is a supported adapter type (P1-001 factory)."""
    try:
        import app.services.ai.provider_adapters as pa  # noqa: F401

        from app.services.ai import provider_adapters

        return name in ("openai", "anthropic", "local")
    except Exception:
        return name in ("openai", "anthropic", "local")


def get_default_provider() -> Optional[ProviderAdapter]:
    """Adapter for the configured default provider, or None.

    Resolution order: ``HERMES_AI_DEFAULT_PROVIDER`` env override → top-level
    ``default`` in the YAML → first configured provider → None.
    """
    cfg = load_config()
    providers = cfg.get("providers") or {}
    if not providers:
        return None

    default_name = (
        os.environ.get("HERMES_AI_DEFAULT_PROVIDER")
        or cfg.get("default")
        or next(iter(providers))
    )
    if default_name not in providers:
        # The configured default is stale/unknown — fall back to the first
        # configured provider rather than failing the whole request.
        default_name = next(iter(providers))
    return _build(default_name, providers[default_name] or {})
