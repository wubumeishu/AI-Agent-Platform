"""JWT authentication + per-account authorization for the Private Domain API.

Closes P0-1 (t_dcc56882 / t_a0195813): the 24 Private Domain endpoints were
unauthenticated and took ``account_id`` as a raw client-supplied Query param,
so any caller could read or write *any* account's data.

Design (ADR-011)
----------------
* **JWT (HS256)** — signed with ``JWT_SECRET`` from the environment (never
  hard-coded; a process-wide default key is used only when the env var is
  absent, which is acceptable for local/dev and MUST be overridden in any
  deployment). The token encodes the caller's *identity* as a compact
  ``{"sub": "<principal>", "account_id": "<uuid>", "role": "..."}`` claim set.
* **account_id is derived, never trusted from the client.** The FastAPI
  dependency :func:`require_private_domain` verifies the Bearer token, then
  returns a :class:`PrivateDomainPrincipal` whose ``account_id`` came from the
  *server-issued* token. Routers pass that value into the service layer; the
  client-supplied ``account_id`` Query param is dropped. A cross-account
  request (token's account != requested account) is a 403, not a 404, so the
  API never leaks *which* accounts exist.
* **No third-party JWT dependency** — HS256 is implemented with the stdlib
  (``hmac`` + ``hashlib``), keeping the audit surface minimal and adding no
  new runtime dependency.

The module exposes:

* :func:`create_access_token` / :func:`decode_access_token` — token helpers
  (also used by the ``/auth/token`` mint endpoint and by tests).
* :func:`require_private_domain` — the router-level dependency (401 / 403).
* :func:`get_current_principal` — resolves the raw Bearer token to a principal
  without the strict private-domain 403 rules (used by the token endpoint).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Secret + algorithm resolution (env-supplied; never hard-coded in a value)
# ---------------------------------------------------------------------------

JWT_SECRET_ENV = "JWT_SECRET"
#: Used ONLY when JWT_SECRET is unset (local/dev convenience). A deployment MUST
#: set JWT_SECRET; a fixed fallback means anyone with the source can forge
#: tokens, so it is acceptable for the dev/test posture only.
_DEFAULT_SECRET = "ai-agent-platform-dev-jwt-secret"
_ALGORITHM = "HS256"
#: Default access-token lifetime (seconds) when not overridden per-token.
DEFAULT_TOKEN_TTL_SECONDS = 8 * 60 * 60

_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    return os.getenv(JWT_SECRET_ENV, _DEFAULT_SECRET)


# ---------------------------------------------------------------------------
# HS256 JWT encode / decode (stdlib only)
# ---------------------------------------------------------------------------

def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def _sign(secret: str, signing_input: bytes) -> bytes:
    return hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()


def create_access_token(
    principal: str,
    account_id: Optional[str] = None,
    role: str = "operator",
    ttl_seconds: Optional[int] = None,
    extra_claims: Optional[dict] = None,
) -> str:
    """Mint an HS256 JWT carrying the caller's identity + owning account.

    ``principal`` (the token ``sub``) is the authenticated user / service
    identity. ``account_id`` is the *owning* account the caller is authorized
    to act as; when present the private-domain dependency binds the request to
    exactly that account.
    """
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else DEFAULT_TOKEN_TTL_SECONDS
    payload: dict = {"sub": principal, "iat": now, "exp": now + ttl}
    if account_id is not None:
        payload["account_id"] = str(account_id)
    if role:
        payload["role"] = role
    if extra_claims:
        payload.update(extra_claims)

    header = {"alg": _ALGORITHM, "typ": "JWT"}
    signing_input = (
        _b64url_encode(json.dumps(header).encode())
        + "."
        + _b64url_encode(json.dumps(payload).encode())
    )
    sig = _sign(_secret(), signing_input.encode("ascii"))
    return signing_input + "." + _b64url_encode(sig)


def decode_access_token(token: str) -> dict:
    """Verify + decode an HS256 JWT, raising ``ValueError`` on any failure.

    Enforces: exactly three segments, the ``alg`` is HS256 (rejects ``none``),
    the signature matches, and the ``exp`` claim (when present) is in the future.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token: expected 3 segments")
    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = _sign(_secret(), signing_input)
    try:
        provided = _b64url_decode(sig_b64)
    except Exception as exc:  # noqa: BLE001 - decode edge
        raise ValueError(f"malformed signature segment: {exc}") from exc
    if not hmac.compare_digest(expected, provided):
        raise ValueError("invalid signature")

    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"malformed token segments: {exc}") from exc

    if header.get("alg") != _ALGORITHM:
        raise ValueError(f"unsupported algorithm: {header.get('alg')!r}")
    exp = payload.get("exp")
    if exp is not None and int(exp) < int(time.time()):
        raise ValueError("token expired")
    return payload


# ---------------------------------------------------------------------------
# Principal + FastAPI dependency
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrivateDomainPrincipal:
    """The authenticated caller, with the owning account derived from the token."""

    principal: str
    account_id: Optional[UUID]
    role: str = "operator"


def get_current_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> PrivateDomainPrincipal:
    """Resolve the Bearer token to a principal. 401 on any auth failure."""
    token = credentials.credentials if credentials and credentials.credentials else ""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": 401, "message": "missing Bearer token", "data": None},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        logger.info("private-domain auth rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": 401, "message": "invalid or expired token", "data": None},
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = payload.get("sub") or "unknown"
    raw_account = payload.get("account_id")
    account_id: Optional[UUID] = None
    if raw_account:
        try:
            account_id = UUID(str(raw_account))
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": 401, "message": "token account_id is not a valid UUID", "data": None},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return PrivateDomainPrincipal(
        principal=principal,
        account_id=account_id,
        role=str(payload.get("role", "operator")),
    )


def require_private_domain(
    principal: PrivateDomainPrincipal = Depends(get_current_principal),
) -> PrivateDomainPrincipal:
    """Router-level guard for the Private Domain surface (P0-1).

    Requires a valid Bearer token whose ``account_id`` claim is present. This
    guarantees every private-domain request is both *authenticated* and
    *account-bound*; the router then uses ``principal.account_id`` (never the
    client-supplied value) as the authoritative account, and any cross-account
    request is a 403.
    """
    if principal.account_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": 403,
                "message": "token is not bound to an account; private-domain access denied",
                "data": None,
            },
        )
    return principal


def _authorize_account(principal: PrivateDomainPrincipal, requested: Optional[UUID]) -> None:
    """Enforce per-account ownership for an explicitly requested account.

    When a request still carries a client-supplied ``account_id`` (the legacy
    Query param kept for API-shape compatibility), it MUST equal the token's
    account or the caller is a cross-account intruder -> 403.
    """
    if requested is None:
        return
    if requested != principal.account_id:
        logger.warning(
            "cross-account private-domain access denied: principal=%s requested=%s",
            principal.principal,
            requested,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": 403,
                "message": "access to another account's data is not permitted",
                "data": None,
            },
        )


class AccountOwnershipError(Exception):
    """A resource the caller acted on does not belong to the caller's account.

    Raised by the service layer when an id-scoped operation (update / delete /
    read) targets a resource owned by a *different* account than the one the
    authenticated principal is bound to. The router maps this to HTTP 403
    (cross-account access), deliberately distinct from 404 (unknown id) so the
    API never leaks *which* accounts exist.
    """

    def __init__(self, resource_type: str = "resource", account_id: Optional[UUID] = None) -> None:
        self.resource_type = resource_type
        self.account_id = account_id
        super().__init__(f"{resource_type} does not belong to the caller's account")


__all__ = [
    "JWT_SECRET_ENV",
    "create_access_token",
    "decode_access_token",
    "PrivateDomainPrincipal",
    "AccountOwnershipError",
    "get_current_principal",
    "require_private_domain",
    "_authorize_account",
]
