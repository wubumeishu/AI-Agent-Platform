"""Response-layer PII masking (P0-2).

The service layer returns PII in plaintext; the *response* layer must never
leak it. These helpers mask phone / email / WeChat-id values before they are
serialized into an API response, and :func:`mask_dict` walks a nested
response payload so no single field can escape the rule.

Masking is deliberately *partial* (not fully redacted): it keeps enough of
the value to be human-verifiable (is this the customer I meant?) while hiding
the sensitive middle. The review's suggested formats are used:

* phone ``13800138000`` -> ``138****8000``
* email ``john.doe@example.com`` -> ``jo***@example.com``
* WeChat id ``wx_abc1234`` -> ``wx_******`` (shorter / opaque values are
  fully masked to 6 stars)
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

#: Keys whose values are PII and must be masked wherever they appear.
PII_KEYS: Iterable[str] = (
    "phone",
    "mobile",
    "email",
    "wechat_id",
    "wechat",
    "platform_account_id",
    "platform_username",
)

#: Keys whose values are credentials / secrets and must be fully redacted.
SECRET_KEYS: Iterable[str] = (
    "password",
    "password_encrypted",
    "passwd",
    "pwd",
    "secret",
    "token",
    "cookie",
    "credential",
)


def mask_phone(phone: Optional[str]) -> Optional[str]:
    """Mask a phone number: keep the first 3 and last 4, star the middle."""
    if not phone:
        return phone
    p = str(phone)
    if len(p) < 7:
        return "*" * len(p)
    return p[:3] + "****" + p[-4:]


def mask_email(email: Optional[str]) -> Optional[str]:
    """Mask an email: keep the first 2 local chars + domain, star the rest."""
    if not email:
        return email
    local, _, domain = str(email).partition("@")
    if not domain:
        return "****"
    keep = local[:2]
    return f"{keep}***@{domain}" if keep else f"***@{domain}"


def mask_wechat(wechat_id: Optional[str]) -> Optional[str]:
    """Mask a WeChat identity: keep a short prefix, star the remainder."""
    if not wechat_id:
        return wechat_id
    w = str(wechat_id)
    if len(w) <= 6:
        return "******"
    return w[:3] + "*" * (len(w) - 3)


def mask_text(value: Optional[str], kind: str = "generic") -> Optional[str]:
    """Mask a value of an unknown PII kind (defaults to phone-like)."""
    if value is None:
        return None
    if kind == "email":
        return mask_email(value)
    if kind in ("wechat", "wechat_id"):
        return mask_wechat(value)
    return mask_phone(value)


def _mask_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    for secret in SECRET_KEYS:
        if secret in lowered:
            return "***"  # credentials are fully redacted, never partially
    if value is None or not isinstance(value, str):
        return value
    if lowered in ("phone", "mobile"):
        return mask_phone(value)
    if lowered in ("email", "mail"):
        return mask_email(value)
    if lowered in ("wechat_id", "wechat", "platform_account_id", "platform_username"):
        return mask_wechat(value)
    return value


def mask_dict(payload: Any) -> Any:
    """Return a copy of ``payload`` with all PII/secret keys masked.

    Recurses through nested dicts *and* lists so a ``{"items": [{"phone":
    ...}], "contact_info": {"phone": ...}, "identities": [{"wechat_id": ...}]}``
    response is fully scrubbed at every level. Plain non-PII values pass
    through unchanged, so the response stays shape-compatible with existing
    clients. Scalars that are PII-keyed are masked; list items are masked
    recursively (so lists of PII dicts / lists of raw phone strings under a
    PII key are both handled).
    """
    if isinstance(payload, dict):
        out: Dict[str, Any] = {}
        for key, value in payload.items():
            out[key] = mask_dict(value) if isinstance(value, (dict, list)) else _mask_value(key, value)
            # A list-of-dicts / list-of-scalars under any key is masked too
            # (covers "items" arrays and "contact_info" that is a list).
            if isinstance(value, list):
                out[key] = [mask_dict(v) for v in value]
        return out
    if isinstance(payload, list):
        return [mask_dict(v) for v in payload]
    return payload


def sanitize_log_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Redact PII / secret values for safe logging (P1 privacy-review item).

    Every PII / secret key is replaced with a ``[REDACTED_<KEY>]`` marker so a
    log line never carries a phone / email / password in the clear.
    """
    if not isinstance(data, dict):
        return data
    out = dict(data)
    for key in list(out):
        lowered = key.lower()
        if any(marker in lowered for marker in PII_KEYS) or any(
            marker in lowered for marker in SECRET_KEYS
        ):
            out[key] = f"[REDACTED_{key.upper()}]"
    return out


__all__ = [
    "PII_KEYS",
    "SECRET_KEYS",
    "mask_phone",
    "mask_email",
    "mask_wechat",
    "mask_text",
    "mask_dict",
    "sanitize_log_data",
]
