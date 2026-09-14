"""P5MSG security — trusted-producer Bearer auth + realtime payload validation.

Implements P5MSG-FIX-1 (security review P5MSG-11 findings P0-3 + P0-2).

V1 auth model
-------------
PHASE1-API-SPEC.md reserves an ``Authorization: Bearer ***`` header but never
implemented it. This module provides the *trusted-producer* control that the
P5MSG-11 security review requires to close:

* **P0-3** — the unauthenticated ``POST /api/v1/realtime/publish`` event-injection
  seam: anyone could push any known-kind event into every live SSE subscriber
  **and** the persistent replay log.
* **P0-2** — the cross-owner delivery-state / mark-read write primitive: any
  caller could drive *any* message's state machine (failed / read) and mark
  *any* conversation read (a cross-tenant write primitive).

A trusted producer presents a shared static Bearer token. The set of trusted
tokens is supplied by the environment (``REALTIME_PUBLISH_TOKENS``), never
hard-coded. Outcomes are mapped to standard HTTP:

* **no token**        -> 401 UNAUTHORIZED (unauthenticated);
* **present + untrusted** -> 403 FORBIDDEN (异主 — the caller is not the owner);
* **present + trusted**   -> allowed.

Default posture is *closed*: when no trusted tokens are configured, every
caller is rejected (empty set == no one is trusted). A deployment that wants
a producer to publish / drive delivery must configure ``REALTIME_PUBLISH_TOKENS``
(comma-separated). Internal code paths (the P5MSG-02/03 channel adapters, the
mark-read router's own ``publish_realtime_event`` call, the shared-bus bridge)
invoke the service seam directly and are unaffected by the HTTP auth layer —
only the *public* write endpoints require the token.

Payload validation
------------------
``validate_publish_payload`` enforces the strong schema the review demands of
the publish seam: a bounded key set, per-value / total length caps, scalar-only
values (no nested dicts), a PII/secret key blocklist, and a UUID check on
``conversation_id``. Violations raise :class:`PayloadValidationError`
(mapped to 422 by the schema validator).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# ---------------------------------------------------------------------------
# Trusted-producer token resolution (environment supplied; never hard-coded)
# ---------------------------------------------------------------------------

#: Env var holding the comma-separated set of trusted Bearer tokens.
PUBLISH_TOKENS_ENV = "REALTIME_PUBLISH_TOKENS"

# Dedicated HTTP-level auth business codes (distinct from the message module's
# 4001/4002/4003/4004 envelope codes so an auth failure is never mistaken for
# a not-found / illegal-transition).
CODE_UNAUTHENTICATED = 401
CODE_FORBIDDEN = 403


def trusted_tokens() -> frozenset:
    """The current set of trusted Bearer tokens (re-read each call).

    Re-reading (rather than caching at import) keeps the running service
    correct when the environment changes and lets tests set the var per-test.
    """
    raw = os.getenv(PUBLISH_TOKENS_ENV, "")
    return frozenset(t.strip() for t in raw.split(",") if t.strip())


@dataclass(frozen=True)
class ProducerPrincipal:
    """The authenticated trusted producer (identified by its Bearer token)."""

    token: str
    trusted: bool = True


_bearer = HTTPBearer(auto_error=False)


def require_trusted_producer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> ProducerPrincipal:
    """FastAPI dependency: require a *trusted producer* Bearer token.

    401 when no token is present; 403 when the token is present but not in
    the configured trusted set (异主). Returns the principal when trusted.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": CODE_UNAUTHENTICATED,
                "message": "trusted producer Bearer token required",
                "data": None,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    if token not in trusted_tokens():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": CODE_FORBIDDEN,
                "message": "caller is not a trusted producer",
                "data": None,
            },
        )
    return ProducerPrincipal(token=token, trusted=True)


# ---------------------------------------------------------------------------
# Realtime publish payload strong schema (P0-3)
# ---------------------------------------------------------------------------

#: Maximum number of top-level payload keys a publish event may carry.
MAX_PAYLOAD_KEYS = 24
#: Maximum serialized payload size (bytes).
MAX_PAYLOAD_BYTES = 4096
#: Maximum length of a single string value.
MAX_VALUE_STR_LEN = 512
#: Maximum number of scalar items in a list value.
MAX_LIST_ITEMS = 32
#: Maximum length of a single payload key.
MAX_KEY_LEN = 64

#: Keys must be a boring JSON-safe identifier (no spaces / control chars).
_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")

# PII / secret markers — any key containing one of these (case-insensitive) is
# rejected. This blocks the "no secrets / no PII" contract at the seam.
_PII_SECRET_MARKERS = (
    "password", "passwd", "pwd", "secret", "token", "apikey", "api_key",
    "key", "cookie", "credential", "proxy_password", "proxyuser", "username",
    "phone", "mobile", "email", "mail", "address", "content", "text",
    "body", "payload", "pii", "private", "card", "bank", "account_no",
    "id_card", "passport",
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
# A value that embeds a bearer / long random secret must be rejected.
_EMBEDDED_SECRET_RE = re.compile(r"^(?:\s*(?:bearer\s+)?[A-Za-z0-9+/=_-]{40,})\s*$")


class PayloadValidationError(ValueError):
    """The publish payload violates the realtime strong schema (-> 422)."""


def _value_is_scalar(value: Any) -> bool:
    return isinstance(value, (bool, int, float, str)) or value is None


def _reject_key(key: Any) -> None:
    if not isinstance(key, str):
        raise PayloadValidationError(
            f"payload key {key!r} must be a string"
        )
    if len(key) > MAX_KEY_LEN:
        raise PayloadValidationError(
            f"payload key too long (> {MAX_KEY_LEN}): {key!r}"
        )
    if not _KEY_RE.match(key):
        raise PayloadValidationError(f"payload key has an invalid charset: {key!r}")
    lowered = key.lower()
    for marker in _PII_SECRET_MARKERS:
        if marker in lowered:
            raise PayloadValidationError(
                f"payload key {key!r} carries a PII/secret marker '{marker}' "
                f"(realtime payloads carry ids/status only)"
            )


def _reject_value(key: str, value: Any) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not (value == value):  # NaN guard
            raise PayloadValidationError(f"payload[{key!r}] is not finite")
        return
    if isinstance(value, str):
        if len(value) > MAX_VALUE_STR_LEN:
            raise PayloadValidationError(
                f"payload[{key!r}] string too long (> {MAX_VALUE_STR_LEN})"
            )
        stripped = value.strip()
        # "conversation_id" must be a UUID when present.
        if key == "conversation_id" and not _UUID_RE.match(stripped):
            raise PayloadValidationError(
                f"payload[{key!r}] must be a UUID string, got {value!r}"
            )
        # Reject values that look like an embedded token / bearer secret.
        if len(stripped) >= 40 and _EMBEDDED_SECRET_RE.match(stripped):
            raise PayloadValidationError(
                f"payload[{key!r}] looks like a secret/token and is not allowed"
            )
        return
    if isinstance(value, list):
        if len(value) > MAX_LIST_ITEMS:
            raise PayloadValidationError(
                f"payload[{key!r}] list too long (> {MAX_LIST_ITEMS})"
            )
        for item in value:
            if not _value_is_scalar(item):
                raise PayloadValidationError(
                    f"payload[{key!r}] list may only hold scalar items"
                )
            if isinstance(item, str) and len(item) > MAX_VALUE_STR_LEN:
                raise PayloadValidationError(
                    f"payload[{key!r}] list item too long (> {MAX_VALUE_STR_LEN})"
                )
        return
    raise PayloadValidationError(
        f"payload[{key!r}] must be a scalar or a flat list of scalars, "
        f"got {type(value).__name__} (nested objects are not allowed)"
    )


def validate_publish_payload(payload: Any) -> Dict[str, Any]:
    """Validate a ``/realtime/publish`` payload against the strong schema.

    Returns the payload unchanged when it passes; raises
    :class:`PayloadValidationError` when it does not (the schema validator
    maps that to a 422). The hub is only ever fed *validated* payloads, so
    neither live SSE frames nor the persistent replay log can be polluted
    with unbounded / PII / secret-bearing payloads.
    """
    if not isinstance(payload, dict):
        raise PayloadValidationError("payload must be a JSON object")
    if len(payload) > MAX_PAYLOAD_KEYS:
        raise PayloadValidationError(
            f"payload carries too many keys (> {MAX_PAYLOAD_KEYS})"
        )
    serialized = json.dumps(payload, ensure_ascii=False)
    if len(serialized) > MAX_PAYLOAD_BYTES:
        raise PayloadValidationError(
            f"payload exceeds the {MAX_PAYLOAD_BYTES}-byte cap"
        )
    for key, value in payload.items():
        _reject_key(key)
        _reject_value(str(key), value)
    return payload


def validate_and_sanitize_publish_payload(payload: Any) -> Dict[str, Any]:
    """Alias kept for callers that read the module for the ``validate_*`` name."""
    return validate_publish_payload(payload)


__all__ = [
    "PUBLISH_TOKENS_ENV",
    "CODE_UNAUTHENTICATED",
    "CODE_FORBIDDEN",
    "ProducerPrincipal",
    "require_trusted_producer",
    "trusted_tokens",
    "PayloadValidationError",
    "validate_publish_payload",
    "validate_and_sanitize_publish_payload",
    "MAX_PAYLOAD_KEYS",
    "MAX_PAYLOAD_BYTES",
    "MAX_VALUE_STR_LEN",
    "MAX_LIST_ITEMS",
    "MAX_KEY_LEN",
]
