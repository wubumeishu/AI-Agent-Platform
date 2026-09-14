"""Auth token endpoint (P0-1 / ADR-011).

Mints the HS256 JWT the Private Domain API requires. In V1 there is no
interactive login flow; the token endpoint issues a bound operator token given
a principal + owning account + (optionally) a shared signing passphrase, so a
caller can be authenticated and account-scoped. This is what the 401/403 tests
drive, and it is how an operator obtains a token in dev.

The endpoint itself does NOT require a token (it is the entry point), but it is
account-scoped: the returned token always carries the requested ``account_id``
so subsequent private-domain calls are bound to it.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from uuid import UUID

from app.security.jwt_auth import create_access_token, JWT_SECRET_ENV

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    """Request to mint a private-domain operator token."""

    principal: str = Field(..., min_length=1, max_length=200, description="Operator / service identity")
    account_id: UUID = Field(..., description="Owning account the token is bound to")
    role: str = Field("operator", max_length=50, description="Role claim")
    ttl_seconds: Optional[int] = Field(None, ge=60, le=30 * 24 * 60 * 60)


class TokenResponse(BaseModel):
    """A minted Bearer token + its metadata."""

    access_token: str
    token_type: str = "bearer"
    principal: str
    account_id: UUID
    role: str


@router.post("/token", response_model=TokenResponse, summary="Mint a private-domain operator token")
async def mint_token(data: TokenRequest) -> TokenResponse:
    token = create_access_token(
        principal=data.principal,
        account_id=data.account_id,
        role=data.role,
        ttl_seconds=data.ttl_seconds,
    )
    return TokenResponse(
        access_token=token,
        principal=data.principal,
        account_id=data.account_id,
        role=data.role,
    )


__all__ = ["router", "TokenRequest", "TokenResponse", "JWT_SECRET_ENV"]
