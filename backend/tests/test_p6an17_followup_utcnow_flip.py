"""P6AN-17 follow-up regression: naive utcnow() writes into timestamptz columns.

Pre-existing bug family (same class as P2-3 / ADR-019) that was explicitly
OUT OF SCOPE of P2-3: several ORM ``default=``/``onupdate=`` hooks on
``DateTime(timezone=True)`` columns still used the naive ``datetime.utcnow``,
and a set of CRM / private-domain / provider write-sites stamped
``datetime.utcnow()`` / ``.isoformat()`` onto the same timestamptz columns.
On a JST session-timezone server a naive value written into a ``timestamptz``
column is re-interpreted in the session tz -> silent 9h drift.

This module locks the fix in, database-free (repo fake convention):

1. **No naive ``utcnow`` source writes remain** in ``app/db/models`` and the
   affected service / provider / CRM modules (the aware ``_utcnow()`` helpers
   already in use are allowed; only the deprecated ``datetime.utcnow`` /
   ``_dt.utcnow`` call-sites are banned).
2. **ORM column defaults produce aware-UTC** for every model whose
   ``DateTime(timezone=True)`` column is exercised here (a naive default would
   drift on a non-UTC session timezone).
3. **Write-path helpers are aware-UTC** - the customer-merge / 360 / tag /
   content-usage / follow-up-timestamp stamps that land in JSON payloads or
   timestamptz columns are now aware UTC.

Run without a database.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"

# Modules that must no longer call the deprecated naive datetime.utcnow()
# (nor _dt.utcnow()). The aware _utcnow() helper pattern is NOT banned - it
# resolves to datetime.now(timezone.utc) already.
_MODULES_WITHOUT_UTCNOW = [
    "db/models/account.py",
    "db/models/agent.py",
    "db/models/audit_log.py",
    "db/models/memory.py",
    "db/models/persona.py",
    "db/models/platform.py",
    "db/models/private_domain.py",
    "db/models/prompt_template.py",
    "services/content_library.py",
    "services/integration_service.py",
    "services/nurture_plan_service.py",
    "services/private_domain.py",
    "services/segment_rule_engine.py",
    "services/segment_service.py",
    "services/nurture_scheduler_service.py",
    "crm/services/tag.py",
    "crm/services/customer.py",
    "crm/services/customer_360.py",
    "providers/bitbrowser_provider.py",
]

# (table, column) pairs whose declared default/onupdate must be aware-UTC.
# A representative set spanning every ORM model touched by the flip.
_DEFAULT_CHECKS: List[Tuple[str, str]] = [
    ("account", "created_at"),
    ("account", "updated_at"),
    ("agent_persona_binding", "bound_at"),
    ("account_browser_binding", "bound_at"),
    ("account_proxy_binding", "bound_at"),
    ("browser_profile", "created_at"),
    ("browser_profile", "updated_at"),
    ("proxy", "created_at"),
    ("proxy", "updated_at"),
    ("agent", "created_at"),
    ("agent", "updated_at"),
    ("agent_customer_binding", "assigned_at"),
    ("agent_customer_binding", "created_at"),
    ("audit_log", "created_at"),
    ("memory", "created_at"),
    ("memory", "updated_at"),
    ("activity_log", "created_at"),
    ("conversation_summary", "created_at"),
    ("context_window", "created_at"),
    ("context_window", "updated_at"),
    ("persona", "created_at"),
    ("persona", "updated_at"),
    ("platform", "created_at"),
    ("private_channel", "created_at"),
    ("private_channel", "updated_at"),
    ("nurture_plan", "created_at"),
    ("nurture_plan", "updated_at"),
    ("content_item", "created_at"),
    ("content_item", "updated_at"),
    ("follow_up_task", "created_at"),
    ("follow_up_task", "updated_at"),
    ("customer_segment", "created_at"),
    ("customer_segment", "updated_at"),
    ("segment_member", "added_at"),
    ("deal_pipeline", "created_at"),
    ("deal_pipeline", "updated_at"),
    ("deal_stage", "created_at"),
    ("deal_stage", "updated_at"),
    ("deal_item", "created_at"),
    ("deal_item", "updated_at"),
    ("prompt_template", "created_at"),
    ("prompt_template", "updated_at"),
    ("prompt_template_usage", "created_at"),
]


def _model_by_tablename(tablename: str):
    """Resolve a mapped model class by its __tablename__ (unique in the app)."""
    from app.db.models.base import Base

    registry = Base.registry
    for cls in registry._class_registry.items():
        klass = cls[1]
        if getattr(klass, "__tablename__", None) == tablename:
            return klass
    raise AssertionError(f"no model with __tablename__={tablename!r}")


# ---------------------------------------------------------------------------
# 1) Source-ban: no naive utcnow call-sites in the flipped modules.
# ---------------------------------------------------------------------------

def test_no_naive_utcnow_in_flipped_modules() -> None:
    for rel in _MODULES_WITHOUT_UTCNOW:
        path = _APP / rel
        assert path.exists(), f"expected module missing: {rel}"
        text = path.read_text(encoding="utf-8")
        for banned in ("datetime.utcnow(", "_dt.utcnow("):
            for i, line in enumerate(text.splitlines(), 1):
                if banned in line:
                    raise AssertionError(
                        f"{rel}:{i} still uses deprecated naive '{banned}': {line.strip()}"
                    )
    print("PASS: no naive utcnow() call-sites remain in flipped modules")


# ---------------------------------------------------------------------------
# 2) ORM defaults are aware-UTC.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tbl,col", _DEFAULT_CHECKS)
def test_orm_defaults_produce_aware_utc(tbl: str, col: str) -> None:
    """A default()/onupdate() invocation on any flipped model yields an
    aware-UTC datetime - the write-path half of the session-tz hazard.

    Mirrors P2-3's ``CallableColumnDefault.arg(None)`` idiom (the default
    lambda ignores its compile-context argument)."""
    klass = _model_by_tablename(tbl)
    col_obj = klass.__table__.c[col]
    # The column itself must be a timezone-aware timestamptz.
    assert bool(col_obj.type.timezone), f"{tbl}.{col} must be DateTime(timezone=True)"

    checked = 0
    for attr in ("default", "onupdate"):
        hook = getattr(col_obj, attr, None)
        if hook is None:
            continue
        # ColumnDefault (both default & onupdate) exposes .arg = the callable.
        arg = getattr(hook, "arg", None)
        if arg is None or not callable(arg):
            continue
        value = arg(None)
        assert isinstance(value, datetime), f"{tbl}.{col} {attr} not a datetime: {type(value)}"
        assert value.tzinfo is not None, (
            f"{tbl}.{col} {attr} produced a NAIVE datetime (the pre-flip bug)"
        )
        assert value.utcoffset() == timezone.utc.utcoffset(None), (
            f"{tbl}.{col} {attr} not aware-UTC: {value}"
        )
        checked += 1
    assert checked >= 1, f"{tbl}.{col} had no callable default/onupdate to verify"
    print(f"PASS: {tbl}.{col} defaults are aware-UTC timestamptz")


# ---------------------------------------------------------------------------
# 3) JSON payload / service stamps are aware-UTC.
# ---------------------------------------------------------------------------

def test_integration_service_isoformat_stamps_are_aware_utc() -> None:
    """The get_customer_deals() / *_at stamps in integration_service emit
    aware-UTC ISO strings (zulu suffix), not naive wall-clock."""
    import re
    from app.services import integration_service

    text = inspect.getsource(integration_service)
    # Every .isoformat() timestamp in this module must be driven by an aware
    # now(timezone.utc) - the naive utcnow().isoformat() pattern must be gone.
    assert "datetime.utcnow" not in text, "integration_service still uses naive utcnow"
    assert "datetime.now(timezone.utc).isoformat()" in text, (
        "expected aware-UTC .isoformat() stamps in integration_service"
    )
    # Confirm the aware call is actually present in the module's live code.
    src = integration_service.__file__
    assert Path(src).read_text(encoding="utf-8").count("datetime.now(timezone.utc)") >= 5
    print("PASS: integration_service stamps are aware-UTC")


def test_customer_service_merge_stamp_is_aware_utc() -> None:
    from app.crm.services import customer as cust_svc
    text = cust_svc.__file__ and Path(cust_svc.__file__).read_text(encoding="utf-8")
    assert "datetime.utcnow" not in text
    assert "datetime.now(timezone.utc).isoformat()" in text
    print("PASS: customer merge stamp is aware-UTC")


def test_content_library_usage_stamp_is_aware_utc() -> None:
    from app.services import content_library
    text = Path(content_library.__file__).read_text(encoding="utf-8")
    assert "datetime.utcnow" not in text
    assert "datetime.now(timezone.utc)" in text
    print("PASS: content library usage stamps are aware-UTC")
