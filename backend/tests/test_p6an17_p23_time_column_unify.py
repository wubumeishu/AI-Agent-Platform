"""P6AN-17 P2-3 regression: source-table time columns unified to aware-UTC.

Locks in the three acceptance scenarios from P6AN-02 (the recurring
naive/timestamptz mixed-DDL bug class) now that migration
``032_unify_source_time_tz`` re-typed the last ten naive columns:

1. **Column re-type is session-tz safe** — the 032 upgrade only fires while a
   column is still a naive ``timestamp without time zone`` and uses
   ``ALTER ... TYPE timestamptz USING (col AT TIME ZONE 'UTC')``; on an
   already-aware column it is a no-op (idempotent / re-runnable).
2. **ORM defaults are aware-UTC** — the six migrated models default to
   ``datetime.now(timezone.utc)`` on ``DateTime(timezone=True)`` (a naive
   default would drift on a non-UTC session timezone).
3. **Service bound coercion is aware-UTC** — the analytics services bind
   absolute (aware) instants; naive inputs are treated as UTC; the
   lead-conversion cycle math subtracts two aware datetimes (no
   naive/aware ``TypeError``).

Run without a database (repo fake-session convention).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import DateTime

# -- 1) Migration guard: idempotent re-type ------------------------------

_MIGRATION = "backend/alembic/versions/032_unify_source_time_tz.py"


def _load_032_upgrade() -> Any:
    """Load migration 032's module so we can drive its guard logic with fakes."""
    import importlib.util
    import os
    import sys

    here = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(here, "alembic", "versions", "032_unify_source_time_tz.py")
    spec = importlib.util.spec_from_file_location("_p6an17_p23_032", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["_p6an17_p23_032"] = mod
    return mod


def _run_032_upgrade(current_type: str, table_present: bool = True):
    """Drive migration 032's upgrade() against a fake op/bind that reports a
    given live column type. Returns the list of DDL strings it issued.

    ``current_type`` is what the fake ``information_schema.columns`` read
    returns for every one of the 10 migrated columns:
      * 'timestamp with time zone'    -> already aware  -> expect no DDL
      * 'timestamp without time zone' -> still naive    -> expect guarded alters
    """
    mod = _load_032_upgrade()

    class _Row:
        def __init__(self, v):
            self.v = v

        def scalar(self):
            return self.v

    class _Bind:
        def execute(self, clause, params=None):
            sql = str(clause)
            if "to_regclass" in sql:
                return _Row(table_present)
            if "information_schema.columns" in sql:
                return _Row(current_type)
            raise AssertionError(f"unexpected bind query: {sql}")

    class _Ops:
        def __init__(self):
            self.issued: list[str] = []
            self._bind = _Bind()

        def get_bind(self):
            return self._bind

        def execute(self, text):
            self.issued.append(str(text))

    op = _Ops()
    mod.op = op
    mod.upgrade()
    return op.issued


def test_032_upgrade_noop_when_columns_already_tz() -> None:
    """Re-running 032 on a fully-aware schema issues ZERO DDL (idempotent)."""
    issued = _run_032_upgrade("timestamp with time zone")
    assert issued == [], f"expected no DDL on an aware schema, got {issued}"
    print("PASS: 032 upgrade is a no-op when all 10 cols are already timestamptz")


def test_032_upgrade_uses_at_time_zone_utc_when_naive() -> None:
    """While a column is still naive the re-type fires — and it must carry the
    session-tz-safe ``USING (col AT TIME ZONE 'UTC')`` clause (a bare CAST
    would shift the instant on a JST server)."""
    issued = _run_032_upgrade("timestamp without time zone")
    mod = _load_032_upgrade()
    alters = [s for s in issued if s.startswith("ALTER TABLE public.")]
    expected_pairs = set(mod._MIGRATED_COLUMNS)
    assert len(alters) == len(expected_pairs), (
        f"{len(alters)} alters issued, expected {len(expected_pairs)}")
    for sql in alters:
        assert "AT TIME ZONE 'UTC'" in sql, f"missing session-tz-safe USING: {sql}"
    print(f"PASS: 032 issued {len(alters)} guarded AT TIME ZONE 'UTC' alters")


# -- 2) ORM defaults are aware-UTC ----------------------------------------

def _model_tz(table_model, col: str) -> bool:
    """True when the column is declared ``DateTime(timezone=True)``."""
    type_ = table_model.__table__.c[col].type
    assert isinstance(type_, DateTime), f"{table_model.__name__}.{col} is not DateTime"
    return bool(type_.timezone)


@pytest.mark.parametrize("model,col", [
    ("lead", "created_at"), ("lead", "updated_at"),
    ("customer", "created_at"), ("customer", "updated_at"),
    ("customer_identity", "created_at"), ("customer_identity", "updated_at"),
    ("lifecycle_stage", "created_at"), ("lifecycle_stage", "updated_at"),
    ("lifecycle_stage_log", "created_at"),
    ("tag", "created_at"),
])
def test_source_models_declare_timezone_columns(model: str, col: str) -> None:
    from app.db.models.lead import Lead
    from app.db.models.customer import Customer
    from app.db.models.customer_identity import CustomerIdentity
    from app.db.models.lifecycle import LifecycleStage, LifecycleStageLog
    from app.db.models.tag import Tag

    m = {
        "lead": Lead, "customer": Customer, "customer_identity": CustomerIdentity,
        "lifecycle_stage": LifecycleStage, "lifecycle_stage_log": LifecycleStageLog,
        "tag": Tag,
    }[model]
    assert _model_tz(m, col), f"{model}.{col} must be DateTime(timezone=True)"


def test_source_model_defaults_produce_aware_utc() -> None:
    """A default() call on any of the six migrated models yields an aware
    UTC datetime — the write-path half of the session-tz hazard.

    ``CallableColumnDefault.arg`` is invoked with a compile context argument;
    passing ``None`` stands in for it (the default lambda ignores it)."""
    from app.db.models.lead import Lead
    from app.db.models.customer import Customer

    val = Lead.created_at.default.arg(None)
    assert val.tzinfo is not None and val.utcoffset() == timezone.utc.utcoffset(None)
    val2 = Customer.updated_at.default.arg(None)
    assert val2.tzinfo is not None and val2.utcoffset() == timezone.utc.utcoffset(None)


# -- 3) Service bound coercion is aware-UTC ------------------------------

def test_funnels_parse_date_is_aware_utc() -> None:
    from app.services.funnel_service import _parse_date

    # date-only -> midnight aware-UTC
    d = _parse_date("2026-09-01")
    assert d == datetime(2026, 9, 1, tzinfo=timezone.utc) and d.tzinfo is not None
    # Zulu -> aware-UTC instant
    d = _parse_date("2026-09-01T12:00:00Z")
    assert d == datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    # foreign offset -> normalized aware-UTC instant
    d = _parse_date("2026-09-01T15:00:00+03:00")
    assert d == datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    # naive datetime string -> treated as UTC (documented assumption)
    d = _parse_date("2026-09-01T12:00:00")
    assert d.tzinfo is not None and d == datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert _parse_date(None) is None
    assert _parse_date("") is None


def test_lead_conversion_bound_coercion() -> None:
    from app.services.lead_conversion_service import _coerce_aware_utc

    assert _coerce_aware_utc(None) is None
    # naive -> assumed UTC
    naive = datetime(2026, 3, 1, 10, 0)
    assert _coerce_aware_utc(naive) == naive.replace(tzinfo=timezone.utc)
    # aware foreign offset -> converted to UTC instant
    foreign = datetime(2026, 3, 1, 10, 0, tzinfo=timezone(timedelta(hours=3)))
    assert _coerce_aware_utc(foreign) == datetime(2026, 3, 1, 7, 0, tzinfo=timezone.utc)
    # aware UTC passes through
    utc = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    assert _coerce_aware_utc(utc) is utc


def test_lead_conversion_cycle_math_is_aware() -> None:
    """The cycle computation subtracts two aware datetimes — the DEF-3
    read-hazard: a naive/aware mix would raise TypeError."""
    from app.services.lead_conversion_service import _coerce_aware_utc

    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stage = datetime(2026, 1, 11, tzinfo=timezone.utc)
    days = max(0.0, (_coerce_aware_utc(stage) - _coerce_aware_utc(created)).total_seconds() / 86400.0)
    assert days == 10.0


def test_dashboard_window_is_aware_utc() -> None:
    from app.services.dashboard_service import _resolve_window

    now = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    # days-only window: start=None, end=None, days=7 -> (now-7d, now, 7)
    start, end, days = _resolve_window(None, None, 7, now=now)
    assert start.tzinfo is not None and end.tzinfo is not None
    assert (end - start).days == 7 and days == 7
    # explicit bounds: aware pass-through + zero effective days + validation
    s2, e2, d2 = _resolve_window(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 2, 1, tzinfo=timezone.utc), 0, now=now)
    assert d2 == 0 and s2.tzinfo is not None and e2.tzinfo is not None
    with pytest.raises(ValueError):
        _resolve_window(
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc), 0, now=now)
