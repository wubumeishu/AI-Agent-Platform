"""Security package for the AI Agent Platform backend.

Historically a single ``app/security.py`` module (P5MSG trusted-producer Bearer
auth + realtime payload validation). It was promoted to a *package* to add the
P0 security & data-protection layer (ADR-011 / task t_da21042d):

* :mod:`app.security.realtime_trusted_producer` — the original trusted-producer
  Bearer token control (``require_trusted_producer`` + publish-payload
  validation). Kept here and re-exported so every existing
  ``from app.security import ...`` import keeps working.
* :mod:`app.security.jwt_auth` — JWT (HS256) auth + per-account authorization
  for the Private Domain API (P0-1).
* :mod:`app.security.crypto` — Fernet PII encryption at rest + PBKDF2
  credential hashing (P0-3 / F-3).
* :mod:`app.security.masking` — response-layer PII masking (P0-2).
* :mod:`app.security.audit` — sensitive-operation audit logging (P1-1).

``from app.security import <name>`` therefore resolves to both the legacy API
and the new primitives.
"""
from app.security.realtime_trusted_producer import (  # noqa: F401
    PUBLISH_TOKENS_ENV,
    CODE_UNAUTHENTICATED,
    CODE_FORBIDDEN,
    ProducerPrincipal,
    require_trusted_producer,
    trusted_tokens,
    PayloadValidationError,
    validate_publish_payload,
    validate_and_sanitize_publish_payload,
    MAX_PAYLOAD_KEYS,
    MAX_PAYLOAD_BYTES,
    MAX_VALUE_STR_LEN,
    MAX_LIST_ITEMS,
    MAX_KEY_LEN,
)
from app.security.jwt_auth import (  # noqa: F401
    JWT_SECRET_ENV,
    create_access_token,
    decode_access_token,
    PrivateDomainPrincipal,
    get_current_principal,
    require_private_domain,
)
from app.security.crypto import (  # noqa: F401
    CREDENTIAL_KEY_ENV,
    encrypt_field,
    decrypt_field,
    encrypt_bytes,
    decrypt_bytes,
    is_encrypted,
    EncryptedString,
    EncryptedJSON,
    hash_password,
    verify_password,
    is_hashed,
    PBKDF2_ITERATIONS,
)
from app.security.masking import (  # noqa: F401
    mask_phone,
    mask_email,
    mask_wechat,
    mask_text,
    mask_dict,
    sanitize_log_data,
)
from app.security.audit import (  # noqa: F401
    record_audit,
    OP_CREATE,
    OP_UPDATE,
    OP_DELETE,
    OP_READ,
    OP_TRANSITION,
)

__all__ = [
    # legacy trusted-producer API
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
    # jwt auth (P0-1)
    "JWT_SECRET_ENV",
    "create_access_token",
    "decode_access_token",
    "PrivateDomainPrincipal",
    "get_current_principal",
    "require_private_domain",
    # crypto (P0-3 / F-3)
    "CREDENTIAL_KEY_ENV",
    "encrypt_field",
    "decrypt_field",
    "encrypt_bytes",
    "decrypt_bytes",
    "is_encrypted",
    "EncryptedString",
    "EncryptedJSON",
    "hash_password",
    "verify_password",
    "is_hashed",
    # masking (P0-2)
    "mask_phone",
    "mask_email",
    "mask_wechat",
    "mask_text",
    "mask_dict",
    "sanitize_log_data",
    # audit (P1-1)
    "record_audit",
    "OP_CREATE",
    "OP_UPDATE",
    "OP_DELETE",
    "OP_READ",
    "OP_TRANSITION",
]
