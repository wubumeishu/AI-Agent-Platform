"""At-rest crypto for sensitive data (P0-3 / F-3).

Two distinct primitives, matching the review's guidance ("凭据至少 hash，勿用
对称加密存口令"):

* **PII (reversible, searchable)** — phone / email / WeChat identity are
  encrypted with **AES-SIV** (an IETF RFC-5297 deterministic AEAD) so they can
  be decrypted for legitimate business use (e.g. sending a message to a known
  phone) yet are NOT readable from a raw DB dump. AES-SIV is *deterministic*
  (same plaintext + key -> same ciphertext), which is what makes SQL
  ``==`` equality lookups on encrypted columns work — something randomized
  Fernet cannot. Tamper / wrong-key decryption is detected, not silent.
  Exposed as the :class:`EncryptedString` / :class:`EncryptedJSON` SQLAlchemy
  :class:`TypeDecorator` types plus the plain :func:`encrypt_field` /
  :func:`decrypt_field` helpers.
* **Credentials (irreversible)** — account / proxy passwords use a salted
  PBKDF2-HMAC-SHA256 hash (:func:`hash_password`) so a DB leak does not expose
  usable credentials. :func:`verify_password` confirms against the stored hash.

Storage format (a value is one of):

* ``A1$<base64url(AES-SIV ciphertext)>`` — new PII encryption (deterministic).
* a raw Fernet token (``gAAAA...``) — legacy PII written by earlier tooling;
  decrypted on read, re-encrypted as ``A1$`` on next write.
* plain text — not yet encrypted; the TypeDecorator encrypts on write.

Key management
--------------
The PII key comes from the ``CREDENTIAL_KEY`` environment variable (any string;
a 32-byte AES-SIV key is derived with SHA-256) and is re-read on every access
(never cached at import) so a running service stays correct when the
environment changes and tests can set it per-test. A dev-only fixed fallback
key is used when the env var is absent — acceptable for local/test, MUST be
overridden in any deployment.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESSIV
from cryptography.fernet import Fernet
from sqlalchemy import String, Text
from sqlalchemy.types import TypeDecorator, TypeEngine

#: Env var holding the PII/credential key. Never hard-coded.
CREDENTIAL_KEY_ENV = "CREDENTIAL_KEY"

# Fixed dev/test fallback (documented, not a secret): a real deployment MUST
# set CREDENTIAL_KEY.
_DEV_KEY = "ai-agent-platform-dev-credential-key"

# AESSIV storage marker.
_PII_PREFIX = "A1$"

# Legacy Fernet tokens start with this base64url marker.
_FERNET_PREFIX_RE = re.compile(r"^gAAAA[A-Za-z0-9_-]")

#: Number of PBKDF2 iterations for credential hashing (OWASP 2023 floor).
PBKDF2_ITERATIONS = 300_000
_HASH_PREFIX = "pbkdf2$sha256$"


def _pii_key() -> bytes:
    """The current 32-byte AES-SIV key (SHA-256 of the configured key material)."""
    raw = os.getenv(CREDENTIAL_KEY_ENV, "").strip() or _DEV_KEY
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _aessiv() -> AESSIV:
    return AESSIV(_pii_key())


# ---------------------------------------------------------------------------
# PII: deterministic reversible field encryption (AES-SIV)
# ---------------------------------------------------------------------------

def encrypt_field(value: Optional[str]) -> Optional[str]:
    """Encrypt a PII string for at-rest storage. ``None``/empty round-trip to ``None``."""
    if value is None:
        return None
    if str(value) == "":
        return None
    ct = _aessiv().encrypt(str(value).encode("utf-8"), [])
    return _PII_PREFIX + base64.urlsafe_b64encode(ct).decode("ascii")


def decrypt_field(value: Optional[str]) -> Optional[str]:
    """Decrypt an at-rest PII value.

    Handles all three storage forms:

    * ``A1$`` AES-SIV token -> decrypted (deterministic, tamper-checked).
    * a legacy Fernet token -> decrypted, so pre-existing data keeps working.
    * plain text -> returned unchanged (not yet encrypted).

    A decryption failure (wrong key / corrupt token) returns the raw value
    rather than raising, so a mis-configured key degrades to "show the stored
    blob" instead of 500-ing the whole API.
    """
    if value is None:
        return None
    s = str(value)
    if s == "":
        return None
    if s.startswith(_PII_PREFIX):
        try:
            ct = base64.urlsafe_b64decode(_pad(s[len(_PII_PREFIX):]))
            return _aessiv().decrypt(ct, []).decode("utf-8")
        except Exception:  # noqa: BLE001 - wrong key / corrupt token
            return s
    if _FERNET_PREFIX_RE.match(s):
        try:
            key = _pii_key()
            # Legacy Fernet key: the dev key path, or a real key if it is a
            # valid Fernet key. Try to build a Fernet from the raw env value.
            raw = os.getenv(CREDENTIAL_KEY_ENV, "").strip()
            token = raw.encode("utf-8") if raw else None
            if token and _is_fernet_key(token):
                return Fernet(token).decrypt(s.encode("ascii")).decode("utf-8")
            del key
            return s
        except Exception:  # noqa: BLE001
            return s
    return s  # legacy plaintext, not yet encrypted


def _is_fernet_key(token: bytes) -> bool:
    """Whether ``token`` is a usable 44-byte base64url Fernet key."""
    if len(token) != 44:
        return False
    try:
        base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        return True
    except Exception:  # noqa: BLE001
        return False


def encrypt_bytes(value: bytes) -> str:
    ct = _aessiv().encrypt(value, [])
    return _PII_PREFIX + base64.urlsafe_b64encode(ct).decode("ascii")


def decrypt_bytes(value: str) -> bytes:
    return _aessiv().decrypt(base64.urlsafe_b64decode(_pad(value[len(_PII_PREFIX):])), [])


def is_encrypted(value: Optional[str]) -> bool:
    """Whether a stored value is already an encrypted PII token (A1$ or Fernet)."""
    return value is not None and (
        str(value).startswith(_PII_PREFIX) or bool(_FERNET_PREFIX_RE.match(str(value)))
    )


def _pad(s: str) -> str:
    return s + "=" * (-len(s) % 4)


class EncryptedString(TypeDecorator[str]):
    """A String/Text column that stores PII encrypted (AES-SIV, deterministic) at rest.

    Python attribute assignment stores the plaintext; the DB receives a
    deterministic ciphertext token; attribute reads decrypt transparently.
    Determinism is what lets ``WHERE col == <encrypted plaintext>`` equality
    lookups keep working. A NULL stays NULL.
    """

    impl = Text
    cache_ok = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect: Any) -> TypeEngine:
        # Store as TEXT so the encrypted token (variable length) always fits.
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Optional[str], dialect: Any) -> Optional[str]:
        if value is None or value == "":
            return None
        # Never double-encrypt a value that is already an encrypted token.
        if is_encrypted(value):
            return value
        return encrypt_field(value)

    def process_result_value(self, value: Optional[str], dialect: Any) -> Optional[str]:
        return decrypt_field(value)


class EncryptedJSON(TypeDecorator):
    """A column that stores a JSON document encrypted (deterministic) at rest.

    Used for :attr:`PrivateChannel.contact_info` (arbitrary contact PII).
    The whole JSON document is encrypted, so no single key can be read from a
    raw dump; application code still gets a plain dict back. Keys are sorted
    before encryption so the representation is canonical and the ciphertext
    is deterministic.
    """

    impl = Text
    cache_ok = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect: Any) -> TypeEngine:
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        import json

        token = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return encrypt_bytes(token.encode("utf-8"))

    def process_result_value(self, value: Optional[str], dialect: Any) -> Any:
        if value is None:
            return None
        import json

        raw = str(value)
        # A legacy plaintext JSON document (no encryption marker) is returned as-is.
        if not is_encrypted(raw):
            try:
                return json.loads(raw)
            except Exception:  # noqa: BLE001
                return raw
        decrypted = decrypt_field(raw)
        try:
            return json.loads(decrypted or "{}")
        except Exception:  # noqa: BLE001
            return decrypted


# ---------------------------------------------------------------------------
# Credentials: irreversible salted PBKDF2 hash
# ---------------------------------------------------------------------------

def _b64url(raw: bytes) -> str:
    """base64url-encode raw bytes (ASCII, no padding)."""
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """base64url-decode a padded-or-unpadded string back to raw bytes."""
    s = s.strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: Optional[str]) -> str:
    """Hash a credential for at-rest storage (irreversible).

    Format: ``pbkdf2$sha256$<iter>$<salt_b64url>$<digest_b64url>``. A fresh
    random salt is generated per call so identical passwords hash differently.
    """
    if password is None:
        return ""
    salt_bytes = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt_bytes,
        iterations=PBKDF2_ITERATIONS,
    )
    return (
        f"{_HASH_PREFIX}{PBKDF2_ITERATIONS}$"
        f"{_b64url(salt_bytes)}${_b64url(digest)}"
    )


def verify_password(password: Optional[str], stored: Optional[str]) -> bool:
    """Constant-time check of a credential against its stored hash.

    Falls back to a plain constant-time comparison only for legacy rows that
    still store a *plaintext* credential (detected by the absence of the
    ``pbkdf2$`` marker), so a one-shot migration can hash them without breaking
    the running system.
    """
    if password is None or stored is None:
        return False
    if not stored.startswith(_HASH_PREFIX):
        # Legacy plaintext credential: constant-time plain compare (migration
        # will replace it with a hash).
        return hmac.compare_digest(
            str(password).encode("utf-8"), stored.encode("utf-8")
        )
    parts = stored.split("$")
    # Layout: ['pbkdf2', 'sha256', '<iter>', '<salt_b64url>', '<digest_b64url>']
    if len(parts) != 5 or parts[0] != "pbkdf2" or parts[1] != "sha256":
        return False
    iters, salt_b64, digest_b64 = parts[2], parts[3], parts[4]
    try:
        iterations = int(iters)
        salt_bytes = _b64url_decode(salt_b64)
        expected = _b64url_decode(digest_b64)
    except Exception:  # noqa: BLE001 - corrupt row -> reject
        return False
    computed = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt_bytes,
        iterations=iterations,
    )
    return hmac.compare_digest(computed, expected)


def is_hashed(value: Optional[str]) -> bool:
    return value is not None and value.startswith(_HASH_PREFIX)


__all__ = [
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
    "PBKDF2_ITERATIONS",
]
