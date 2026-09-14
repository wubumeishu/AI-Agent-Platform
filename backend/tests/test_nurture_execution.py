"""Tests for the NurturePlan execution engine (P1 - t_a2ce2cae / ADR-010).

Covers, layer by layer (pure core -> engine -> DB adapter -> API):

- ``app.services.nurture_schedule``        pure scheduling + retry + segment core
- ``app.services.nurture_step_executor``   the Step Execution Engine
- ``app.services.nurture_scheduler_service`` the DB adapter + scheduler + log queries
- ``app.routers.nurture_execution``       the execution-log REST API

Acceptance criteria exercised here:
- [x] Scheduler picks up due plans without manual trigger
- [x] Steps execute in sequence honouring delay_hours; failures logged + retried
- [x] Execution log table / API + tests
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from app.services import nurture_schedule as ns
from app.services.nurture_schedule import (
    backoff_seconds,
    due_steps,
    is_plan_due,
    is_recoverable,
    normalize_descriptor,
    sequence_steps,
    segment_needs_sync,
    should_retry,
    step_terminal_status,
    to_utc,
)
from app.services.nurture_step_executor import (
    ContentResolution,
    ContentProvider,
    RunResult,
    StepExecutionEngine,
    StepExecutionResult,
)


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# =====================================================================
# 1. Pure scheduling core (nurture_schedule)
# =====================================================================

class TestIsPlanDue:
    def test_only_active_plans_fire(self):
        plan = {"status": "draft", "schedule_type": "fixed", "schedule_config": {}}
        assert is_plan_due(plan, _utc(2026, 1, 1)) is False

    def test_fixed_due_when_no_anchor(self):
        plan = {"status": "active", "schedule_type": "fixed", "schedule_config": {}}
        assert is_plan_due(plan, _utc(2026, 1, 1)) is True

    def test_fixed_not_due_before_run_at(self):
        plan = {
            "status": "active",
            "schedule_type": "fixed",
            "schedule_config": {"run_at": "2026-06-01T00:00:00+00:00"},
        }
        assert is_plan_due(plan, _utc(2026, 5, 1)) is False
        assert is_plan_due(plan, _utc(2026, 7, 1)) is True

    def test_fixed_repeating_honours_interval(self):
        cfg = {
            "run_at": "2026-01-01T00:00:00+00:00",
            "interval_hours": 24,
            "last_run_at": "2026-01-01T00:00:00+00:00",
        }
        plan = {"status": "active", "schedule_type": "fixed", "schedule_config": cfg}
        # 12h after last run < 24h interval -> not due
        assert is_plan_due(plan, _utc(2026, 1, 1, 12)) is False
        # 25h after last run >= 24h -> due (Jan 1 00:00 + 25h = Jan 2 01:00)
        assert is_plan_due(plan, _utc(2026, 1, 1, 0) + timedelta(hours=25)) is True

    def test_drip_due_when_pending_steps_remain(self):
        plan = {
            "status": "active",
            "schedule_type": "drip",
            "schedule_config": {
                "pending_steps": 2,
                "earliest_pending_at": "2026-01-01T00:00:00+00:00",
            },
        }
        assert is_plan_due(plan, _utc(2026, 1, 1, 1)) is True

    def test_drip_not_due_when_no_pending_steps(self):
        plan = {
            "status": "active",
            "schedule_type": "drip",
            "schedule_config": {"pending_steps": 0},
        }
        assert is_plan_due(plan, _utc(2026, 1, 1)) is False

    def test_triggered_only_fires_when_armed(self):
        base = {"status": "active", "schedule_type": "triggered"}
        # not armed -> not due
        assert is_plan_due({**base, "schedule_config": {}}, _utc(2026, 1, 1)) is False
        # armed in the past -> due
        armed = {**base, "schedule_config": {"armed_at": "2026-01-01T00:00:00+00:00"}}
        assert is_plan_due(armed, _utc(2026, 1, 1, 1)) is True
        # auto_armed flag -> due
        auto = {**base, "schedule_config": {"auto_armed": True}}
        assert is_plan_due(auto, _utc(2026, 1, 1)) is True

    def test_unknown_schedule_type_fail_safe(self):
        plan = {"status": "active", "schedule_type": "bogus", "schedule_config": {}}
        assert is_plan_due(plan, _utc(2026, 1, 1)) is False


class TestSequenceSteps:
    def test_delays_are_cumulative(self):
        steps = [
            {"step_id": "a", "step_order": 0, "delay_hours": 0},
            {"step_id": "b", "step_order": 1, "delay_hours": 24},
            {"step_id": "c", "step_order": 2, "delay_hours": 48},
        ]
        start = _utc(2026, 1, 1, 0)
        scheduled = sequence_steps(steps, run_started_at=start)
        assert [s.scheduled_at for s in scheduled] == [
            _utc(2026, 1, 1, 0),   # 0h
            _utc(2026, 1, 2, 0),   # +24h
            _utc(2026, 1, 4, 0),   # +48h
        ]

    def test_negative_delay_clamped(self):
        scheduled = sequence_steps(
            [{"step_id": "a", "step_order": 0, "delay_hours": -5}], run_started_at=_utc(2026, 1, 1)
        )
        assert scheduled[0].scheduled_at == _utc(2026, 1, 1, 0)

    def test_due_steps_filter(self):
        scheduled = sequence_steps(
            [
                {"step_id": "a", "step_order": 0, "delay_hours": 0},
                {"step_id": "b", "step_order": 1, "delay_hours": 24},
            ],
            run_started_at=_utc(2026, 1, 1, 0),
        )
        # 12h in: only step a is due
        assert [s.step_id for s in due_steps(scheduled, _utc(2026, 1, 1, 12))] == ["a"]
        # 30h in: both due
        assert [s.step_id for s in due_steps(scheduled, _utc(2026, 1, 2, 6))] == ["a", "b"]


class TestRetryCore:
    def test_backoff_exponential_then_capped(self):
        assert backoff_seconds(1, base=60, cap=3600) == 60
        assert backoff_seconds(2, base=60, cap=3600) == 120
        assert backoff_seconds(3, base=60, cap=3600) == 240
        # capped at 3600 after many attempts
        assert backoff_seconds(10, base=60, cap=3600) == 3600

    def test_should_retry_boundary(self):
        assert should_retry(1, 3) is True
        assert should_retry(2, 3) is True
        assert should_retry(3, 3) is False

    def test_terminal_status(self):
        assert step_terminal_status(1, 3) == "failed"
        assert step_terminal_status(3, 3) == "dead_letter"

    def test_is_recoverable_transient_markers(self):
        assert is_recoverable(TimeoutError("connection timed out")) is True
        assert is_recoverable(Exception("http 503 unavailable")) is True
        assert is_recoverable(Exception("rate limited 429")) is True

    def test_is_recoverable_programming_error(self):
        # Deterministic programming errors are NOT retryable: retrying a
        # type bug / bad request never succeeds, so dead-letter immediately.
        assert is_recoverable(TypeError("bad operand")) is False
        assert is_recoverable(ValueError("bad shape")) is False
        assert is_recoverable(KeyError("missing")) is False

    def test_is_recoverable_generic_exception_allows_one_retry(self):
        # Unknown exception types are conservative: allow one retry.
        assert is_recoverable(RuntimeError("mystery failure")) is True


class TestSegmentSyncCore:
    def test_manual_segments_never_auto_sync(self):
        assert segment_needs_sync({"segment_type": "manual"}, _utc(2026, 1, 1)) is False

    def test_auto_segment_never_synced_is_due(self):
        seg = {"segment_type": "automatic", "last_synced_at": None}
        assert segment_needs_sync(seg, _utc(2026, 1, 1)) is True

    def test_stale_segment_is_due(self):
        seg = {"segment_type": "dynamic", "last_synced_at": _utc(2026, 1, 1, 0).isoformat()}
        assert segment_needs_sync(seg, _utc(2026, 1, 1, 7)) is True  # 7h > 6h default

    def test_fresh_segment_is_not_due(self):
        seg = {"segment_type": "dynamic", "last_synced_at": _utc(2026, 1, 1, 5).isoformat()}
        assert segment_needs_sync(seg, _utc(2026, 1, 1, 6)) is False


class TestNormalizeDescriptor:
    def test_uuids_and_datetimes_become_json_safe(self):
        from uuid import uuid4
        plan_uuid = uuid4()
        acct = uuid4()
        raw = {
            "id": plan_uuid,
            "account_id": acct,
            "status": "active",
            "schedule_type": "fixed",
            "schedule_config": {"run_at": _utc(2026, 1, 1, 5)},
            "trigger_conditions": [{"field": "stage"}],
        }
        out = normalize_descriptor(raw)
        assert out["id"] == str(plan_uuid)
        assert out["account_id"] == str(acct)
        # run_at datetime coerced to an ISO string inside schedule_config
        assert isinstance(out["schedule_config"]["run_at"], str)
        assert out["trigger_conditions"] == [{"field": "stage"}]

    def test_missing_optional_fields_are_dropped(self):
        out = normalize_descriptor({"id": "p1", "status": "active"})
        assert "account_id" not in out
        assert "target_segment_id" not in out


# =====================================================================
# 2. Step Execution Engine (nurture_step_executor)
# =====================================================================

class _FakeProvider:
    """Deterministic ContentProvider for engine tests (no DB, no LLM).

    Content ids are *valid* UUIDs so the DB adapter's ``uuid.UUID(...)``
    coercion in ``_persist_results`` succeeds (matches the real PGUUID columns).
    """

    def __init__(self, resolutions=None, raise_exc=None):
        self.resolutions = resolutions or {}
        self.raise_exc = raise_exc
        self.calls = []
        self._seq = 0

    def _next_content_uuid(self):
        self._seq += 1
        return f"{self._seq:032d}"  # 32-hex, valid canonical UUID without dashes

    async def reuse(self, plan, step):
        self.calls.append(("reuse", step.step_order))
        if self.raise_exc:
            raise self.raise_exc
        return self.resolutions.get(step.step_order) or ContentResolution(
            content_item_id=self._next_content_uuid(), strategy="reuse"
        )

    async def generate(self, plan, step):
        self.calls.append(("generate", step.step_order))
        if self.raise_exc:
            raise self.raise_exc
        return ContentResolution(
            content_item_id=self._next_content_uuid(), strategy="llm"
        )


class _Step:
    @staticmethod
    def _mk(order, content_id, delay=0):
        return SimpleNamespace(
            step_id=f"s{order}",
            step_order=order,
            content_id=content_id,
            trigger_type="time_based",
            delay_hours=delay,
            config={},
            scheduled_at=_utc(2026, 1, 1, 0),
        )


class TestStepExecutionEngine:
    @pytest.mark.asyncio
    async def test_success_path_reuse_and_generate(self):
        provider = _FakeProvider()
        engine = StepExecutionEngine(provider)
        plan = {"id": "p1", "account_id": "a1"}
        steps = [
            _Step._mk(0, content_id="c0"),   # reuse
            _Step._mk(1, content_id=None),   # generate (no content_id)
        ]
        result = await engine.execute_run(plan, steps, _utc(2026, 1, 1), run_id="run-1")
        assert result.succeeded == 2
        assert result.all_done is True
        # provider picked the right method per step
        assert ("reuse", 0) in provider.calls
        assert ("generate", 1) in provider.calls
        # provenance recorded
        by_order = {r.step_order: r for r in result.results}
        assert by_order[0].content_strategy == "reuse"
        assert by_order[1].content_strategy == "llm"

    @pytest.mark.asyncio
    async def test_transient_failure_retries_then_dead_letters(self):
        provider = _FakeProvider(raise_exc=TimeoutError("provider timed out"))
        engine = StepExecutionEngine(provider, max_attempts=3)
        plan = {"id": "p1"}
        step = _Step._mk(0, content_id="c0")

        # attempt 1 -> failed, will retry
        r1 = await engine.execute_run(plan, [step], _utc(2026, 1, 1), run_id="r")
        assert r1.failed == 1
        assert r1.results[0].status == "failed"
        assert r1.results[0].will_retry is True
        assert r1.results[0].next_retry_in_s == backoff_seconds(1)

        # attempt 3 (budget exhausted, attempt_for tells it 2 prior failures)
        r3 = await engine.execute_run(
            plan, [step], _utc(2026, 1, 1), run_id="r", attempt_for={0: 2}
        )
        assert r3.results[0].status == "dead_letter"
        assert r3.results[0].will_retry is False
        assert r3.dead_lettered == 1

    @pytest.mark.asyncio
    async def test_non_recoverable_error_dead_letters_immediately(self):
        provider = _FakeProvider(raise_exc=ValueError("bad shape"))
        engine = StepExecutionEngine(provider, max_attempts=5)
        plan = {"id": "p1"}
        step = _Step._mk(0, content_id=None)
        # even with a large budget, a deterministic error is terminal
        result = await engine.execute_run(plan, [step], _utc(2026, 1, 1), run_id="r")
        assert result.results[0].status == "dead_letter"
        assert result.results[0].metadata.get("dead_reason") == "non_recoverable_error"

    @pytest.mark.asyncio
    async def test_only_due_steps_execute(self):
        provider = _FakeProvider()
        engine = StepExecutionEngine(provider)
        plan = {"id": "p1"}
        now = _utc(2026, 1, 1, 0)
        # step 0 due now, step 1 fires 24h later (not due yet)
        scheduled = sequence_steps(
            [
                {"step_id": "s0", "step_order": 0, "delay_hours": 0},
                {"step_id": "s1", "step_order": 1, "delay_hours": 24},
            ],
            run_started_at=now,
        )
        result = await engine.execute_run(plan, scheduled, now, run_id="r")
        assert result.executed == 1
        assert result.all_done is False  # step 1 not due yet
        assert [r.step_order for r in result.results] == [0]

    def test_result_row_is_json_safe(self):
        provider = _FakeProvider()
        engine = StepExecutionEngine(provider)
        # build one via _execute_step success
        import asyncio
        step = _Step._mk(0, content_id=CONTENT_UUID)
        outcome = asyncio.run(
            engine._execute_step({"id": PLAN_UUID}, step, "run", 1)
        )
        row = outcome.to_execution_row()
        assert row["status"] == "success"
        # _FakeProvider returns a valid 32-hex UUID content id
        assert len(row["content_item_id"]) == 32
        assert row["content_strategy"] == "reuse"
        # scheduled_at stays a tz-aware datetime (ORM column), JSON-safe on persist
        assert row["scheduled_at"].tzinfo is not None
        # metadata is a plain dict (JSON-safe)
        assert isinstance(row["metadata_"], dict)


# =====================================================================
# 3. DB adapter + scheduler (nurture_scheduler_service)
# =====================================================================

class _Result:
    """Minimal stand-in for a SQLAlchemy Result supporting the accessors the
    adapter uses: ``.scalars().all()``, ``.all()``, ``.scalar()``,
    ``.scalar_one_or_none()``.

    ``rows`` serves both ``.scalars().all()`` (the ORM rows) AND ``.all()``
    (the tuple rows, e.g. ``(status, count)`` or ``(step_order, retry_count)``).
    For a COUNT SELECT the call site uses ``.scalar()`` -> ``scalar``.
    """

    def __init__(self, rows, scalar=None, one=None):
        self._rows = rows
        self._scalar = scalar
        self._one = one

    def scalars(self):
        outer = self

        class _S:
            def all(self):
                return outer._rows

        return _S()

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._one


class _FakeSession:
    """A session stand-in that pops pre-scripted results from a queue for each
    ``execute`` call and records ORM objects passed to ``add``. ``get`` returns
    a configurable value so we control what ``db.get`` looks up."""

    def __init__(self, execute_results=None, get_value=None):
        self._queue = list(execute_results or [])
        self.get_value = get_value
        self.added = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.close_calls = 0
        self.rollback_calls = 0

    async def execute(self, *a, **k):
        if self._queue:
            return self._queue.pop(0)
        return _Result([])

    async def get(self, model, id_):
        return self.get_value

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flush_calls += 1

    async def commit(self):
        self.commit_calls += 1

    async def rollback(self):
        self.rollback_calls += 1

    async def close(self):
        self.close_calls += 1


# Deterministic, *valid* UUIDs - the DB layer coerces ids via uuid.UUID(str(...))
# so fixtures must be well-formed 36-char hex strings (real models use PGUUID).
PLAN_UUID = "00000000-0000-0000-0000-000000000001"
ACCT_UUID = "00000000-0000-0000-0000-000000000002"
CONTENT_UUID = "00000000-0000-0000-0000-000000000003"
STEP_UUID = "00000000-0000-0000-0000-000000000004"
SEG_UUID = "00000000-0000-0000-0000-000000000005"


def _make_plan(status="active", schedule_type="fixed", cfg=None, target_segment=None,
               plan_id=PLAN_UUID, account_id=ACCT_UUID):
    return SimpleNamespace(
        id=plan_id,
        account_id=account_id,
        status=status,
        schedule_type=schedule_type,
        schedule_config=cfg or {},
        trigger_conditions=[],
        target_segment_id=target_segment,
        updated_at=_utc(2026, 1, 1, 0),
    )


def _make_step(order=0, content_id=CONTENT_UUID, delay=0, step_id=STEP_UUID):
    return SimpleNamespace(
        id=step_id,
        step_order=order,
        content_id=content_id,
        trigger_type="time_based",
        delay_hours=delay,
        config={},
        is_deleted=False,
    )


class TestNurtureSchedulerRunPass:
    @pytest.mark.asyncio
    async def test_picks_up_due_plan_and_executes_steps(self):
        from app.services.nurture_scheduler_service import NurtureScheduler

        plan = _make_plan()
        step = _make_step()
        # execute queue order in run_pass:
        #  1) select(NurturePlan)            -> [plan]
        #  2) select(NurturePlanItem)        -> [step]
        #  3) select(NSE.step_order) success -> []
        #  4) select(step_order,retry_count) prior_attempts -> []
        session = _FakeSession(
            execute_results=[
                _Result([plan]),
                _Result([step]),
                _Result([]),
                _Result([]),
            ],
            get_value=None,  # no segment targeted
        )

        provider = _FakeProvider()
        sched = NurtureScheduler(lambda: session, content_provider=provider)
        summary = await sched.run_pass(now=_utc(2026, 1, 1, 0))

        assert summary["plans_scanned"] == 1
        assert summary["plans_due"] == 1
        assert summary["steps_executed"] == 1
        assert summary["steps_succeeded"] == 1
        # a NurtureStepExecution row was persisted via add()
        from app.db.models.nurture_execution import NurtureStepExecution
        assert len(session.added) == 1
        rec = session.added[0]
        assert isinstance(rec, NurtureStepExecution)
        assert rec.status == "success"
        assert session.commit_calls == 1
        assert session.close_calls == 1

    @pytest.mark.asyncio
    async def test_not_due_plan_is_skipped(self):
        from app.services.nurture_scheduler_service import NurtureScheduler

        plan = _make_plan(status="paused")  # non-active -> never due
        session = _FakeSession(
            execute_results=[
                _Result([plan]),
            ],
        )
        provider = _FakeProvider()
        sched = NurtureScheduler(lambda: session, content_provider=provider)
        summary = await sched.run_pass(now=_utc(2026, 1, 1, 0))
        assert summary["plans_scanned"] == 1
        assert summary["plans_due"] == 0
        assert summary["steps_executed"] == 0
        assert session.commit_calls == 1

    @pytest.mark.asyncio
    async def test_persisted_row_captures_failure_and_dead_letter(self):
        from app.services.nurture_scheduler_service import NurtureScheduler

        plan = _make_plan()
        step = _make_step()
        session = _FakeSession(
            execute_results=[_Result([plan]), _Result([step]), _Result([]), _Result([])],
            get_value=None,
        )
        # a provider that blows up with a deterministic error -> dead letter
        provider = _FakeProvider(raise_exc=ValueError("deterministic"))
        sched = NurtureScheduler(lambda: session, content_provider=provider, max_attempts=3)
        summary = await sched.run_pass(now=_utc(2026, 1, 1, 0))
        assert summary["dead_lettered"] == 1
        rec = session.added[0]
        assert rec.status == "dead_letter"
        assert rec.error_code == "E_ValueError"
        assert "deterministic" in rec.error_message

    @pytest.mark.asyncio
    async def test_prior_attempts_drive_retry_resume(self):
        from app.services.nurture_scheduler_service import NurtureScheduler

        plan = _make_plan()
        step = _make_step()
        session = _FakeSession(
            execute_results=[
                _Result([plan]),   # select(NurturePlan)
                _Result([step]),   # select(NurturePlanItem)
                _Result([]),       # select(NSE.step_order) where success
                _Result([(0, 1)]), # select(step_order,retry_count) prior_attempts -> 1 prior
            ],
            get_value=None,
        )
        # transient error; with 1 prior attempt and max_attempts=3, attempt=2 -> still retried
        provider = _FakeProvider(raise_exc=TimeoutError("timeout"))
        sched = NurtureScheduler(lambda: session, content_provider=provider, max_attempts=3)
        summary = await sched.run_pass(now=_utc(2026, 1, 1, 0))
        rec = session.added[0]
        assert rec.status == "failed"       # still has retries
        assert rec.retry_count == 2         # prior(1)+this attempt index
        assert summary["will_retry"] == 1


class TestDBContentProvider:
    @pytest.mark.asyncio
    async def test_reuse_returns_library_item(self):
        from app.services.nurture_scheduler_service import DBContentProvider

        item = SimpleNamespace(
            id="c0",  # provider returns str(item.id); downstream coerces to UUID
            content_type="text",
            title="hi",
            usage_count=3,
            last_used_at=None,
        )
        db = _FakeSession(get_value=item)
        provider = DBContentProvider(db)
        # step.content_id must be a well-formed UUID (provider does db.get(ContentItem, UUID(...)))
        step = _Step._mk(0, content_id=CONTENT_UUID)
        res = await provider.reuse({"id": PLAN_UUID}, step)
        assert res.content_item_id == "c0"
        assert res.strategy == "reuse"

    @pytest.mark.asyncio
    async def test_reuse_missing_content_raises_lookup(self):
        from app.services.nurture_scheduler_service import DBContentProvider

        db = _FakeSession(get_value=None)
        provider = DBContentProvider(db)
        step = _Step._mk(0, content_id=CONTENT_UUID)
        with pytest.raises(LookupError):
            await provider.reuse({"id": PLAN_UUID}, step)

    @pytest.mark.asyncio
    async def test_generate_bridges_to_phase5_service(self):
        import app.services.content_generation_service as cgs
        from app.services.nurture_scheduler_service import DBContentProvider
        from app.schemas.content_generation import GeneratedContent, QualityEvaluation

        captured = {}

        class _FakeGenSvc:
            def __init__(self, db, llm_provider=None):
                captured["llm"] = llm_provider

            async def generate_content(self, request):
                captured["request"] = request
                q = QualityEvaluation(score=4.5, passed=True)
                return GeneratedContent(
                    generation_id=UUID("77777777-7777-7777-7777-777777777777"),
                    content_item_id=UUID("88888888-8888-8888-8888-888888888888"),
                    title="t",
                    body="b",
                    content_type="text",
                    quality=q,
                    strategy="llm",
                )

        # monkeypatch the module-level service the provider imports lazily
        orig = cgs.ContentGenerationService
        cgs.ContentGenerationService = _FakeGenSvc
        try:
            db = _FakeSession()
            provider = DBContentProvider(db, llm_provider="FAKE_LLM")
            step = _Step._mk(0, content_id=None)
            step.config = {"content_type": "text", "objective": "nurture"}
            # plan.account_id must be a well-formed UUID (provider coerces it)
            res = await provider.generate(
                {"id": PLAN_UUID, "account_id": ACCT_UUID}, step
            )
        finally:
            cgs.ContentGenerationService = orig

        assert res.strategy == "llm"
        # the provider str()-ifies the library UUID into ContentResolution
        assert res.content_item_id == "88888888-8888-8888-8888-888888888888"
        assert res.quality_score == 4.5
        # prove it reached the Phase-5 service + passed the LLM provider through
        assert captured["llm"] == "FAKE_LLM"
        assert captured["request"].save_to_library is True
        assert str(captured["request"].account_id) == ACCT_UUID


class TestExecutionLogQueries:
    @pytest.mark.asyncio
    async def test_list_plan_executions(self):
        from app.db.models.nurture_execution import NurtureStepExecution
        from app.services.nurture_scheduler_service import list_plan_executions
        from uuid import UUID

        rec = NurtureStepExecution(
            plan_id=UUID("11111111-1111-1111-1111-111111111111"),
            step_order=0,
            status="success",
            created_at=_utc(2026, 1, 1),
        )
        db = _FakeSession(
            execute_results=[
                _Result([], scalar=1),        # count
                _Result([rec]),               # rows
            ]
        )
        out = await list_plan_executions(
            db, UUID("11111111-1111-1111-1111-111111111111")
        )
        assert out["total"] == 1
        assert out["items"][0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_dead_letters(self):
        from app.db.models.nurture_execution import NurtureStepExecution
        from app.services.nurture_scheduler_service import list_dead_letters
        from uuid import UUID

        rec = NurtureStepExecution(
            plan_id=UUID("22222222-2222-2222-2222-222222222222"),
            step_order=2,
            status="dead_letter",
            error_code="E_TimeoutError",
            created_at=_utc(2026, 1, 1),
        )
        db = _FakeSession(
            execute_results=[
                _Result([], scalar=1),
                _Result([rec]),
            ]
        )
        out = await list_dead_letters(db)
        assert out["total"] == 1
        assert out["items"][0]["error_code"] == "E_TimeoutError"

    @pytest.mark.asyncio
    async def test_plan_execution_progress(self):
        from app.services.nurture_scheduler_service import get_plan_execution_progress
        from uuid import UUID

        # group_by status -> rows of (status, count); then a last-activity scalar
        db = _FakeSession(
            execute_results=[
                _Result([("success", 2), ("dead_letter", 1)]),
                _Result([], scalar=_utc(2026, 1, 2)),
            ]
        )
        out = await get_plan_execution_progress(db, UUID("33333333-3333-3333-3333-333333333333"))
        assert out["total_attempts"] == 3
        assert out["completed"] == 2
        assert out["dead_lettered"] == 1
        assert out["last_activity_at"].startswith("2026-01-02")


# =====================================================================
# 4. Segment sync driver (sync_due_segments / TD-9)
# =====================================================================

class TestSyncDueSegments:
    @pytest.mark.asyncio
    async def test_syncs_due_auto_segment(self, monkeypatch):
        import app.services.segment_rule_engine as sre
        from app.services.nurture_scheduler_service import sync_due_segments

        seg = SimpleNamespace(
            id="seg1",
            segment_type="automatic",
            last_synced_at=None,
            is_deleted=False,
        )
        db = _FakeSession(
            execute_results=[
                _Result([seg]),  # select(CustomerSegment) where type in (...)
            ]
        )
        monkeypatch.setattr(
            sre, "sync_segment_members",
            lambda db, sid: _fake_sync(sid),
        )

        async def _fake_sync(sid):
            return {"segment_id": str(sid), "total_members": 42, "synced": True}

        results = await sync_due_segments(db)
        assert len(results) == 1
        assert results[0]["total_members"] == 42
        assert db.commit_calls == 1  # commits only when there were results

    @pytest.mark.asyncio
    async def test_no_due_segments_no_commit(self):
        from app.services.nurture_scheduler_service import sync_due_segments

        db = _FakeSession(
            execute_results=[_Result([])]  # no auto/dynamic segments
        )
        results = await sync_due_segments(db)
        assert results == []
        assert db.commit_calls == 0


# =====================================================================
# 5. API layer (FastAPI TestClient + get_db override)
# =====================================================================

class TestNurtureExecutionAPI:
    @staticmethod
    def _client(execute_results):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.db.session import get_db
        from app.routers import nurture_execution as ne

        app = FastAPI()
        app.include_router(ne.router, prefix="/api/v1")

        def _fresh_session():
            return _FakeSession(execute_results=list(execute_results))

        async def _override():
            yield _fresh_session()

        app.dependency_overrides[get_db] = _override
        return TestClient(app)

    def test_plan_execution_history_endpoint(self):
        from app.db.models.nurture_execution import NurtureStepExecution
        from uuid import UUID

        plan_id = UUID("44444444-4444-4444-4444-444444444444")
        rec = NurtureStepExecution(plan_id=plan_id, step_order=0, status="success")
        db = _FakeSession(execute_results=[_Result([], scalar=1), _Result([rec])])
        client = self._make_client_one_shot(db)
        r = client.get(f"/api/v1/nurture/executions/plan/{plan_id}")
        assert r.status_code == 200
        assert r.json()["total"] == 1
        assert r.json()["items"][0]["status"] == "success"

    def test_dead_letters_endpoint(self):
        from app.db.models.nurture_execution import NurtureStepExecution
        from uuid import UUID

        rec = NurtureStepExecution(
            plan_id=UUID("55555555-5555-5555-5555-555555555555"),
            step_order=1,
            status="dead_letter",
            error_message="boom",
        )
        db = _FakeSession(execute_results=[_Result([], scalar=1), _Result([rec])])
        client = self._make_client_one_shot(db)
        r = client.get("/api/v1/nurture/executions/dead-letters")
        assert r.status_code == 200
        assert r.json()["items"][0]["status"] == "dead_letter"

    def test_progress_endpoint(self):
        from uuid import UUID
        plan_id = UUID("66666666-6666-6666-6666-666666666666")
        db = _FakeSession(
            execute_results=[
                _Result([("success", 3), ("failed", 1)]),
                _Result([], scalar=_utc(2026, 1, 3)),
            ]
        )
        client = self._make_client_one_shot(db)
        r = client.get(f"/api/v1/nurture/executions/plan/{plan_id}/progress")
        assert r.status_code == 200
        assert r.json()["total_attempts"] == 4
        assert r.json()["completed"] == 3

    @staticmethod
    def _make_client_one_shot(db):
        """Override get_db to always return the same scripted session instance.

        The router's prefix is ``/api/v1/nurture/executions`` (self-carried),
        so the app includes it BARE - mounting it under another ``/api/v1``
        would double-prefix the paths (the same class of defect the AI-tier
        routers in main.py deliberately avoid).
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.db.session import get_db
        from app.routers import nurture_execution as ne

        app = FastAPI()
        app.include_router(ne.router)

        async def _override():
            yield db

        app.dependency_overrides[get_db] = _override
        return TestClient(app)

    def test_engine_status_reports_not_running(self, monkeypatch):
        from app.routers import nurture_execution as ne

        class _FakeLoop:
            def __init__(self):
                self.running = False

            def status(self):
                return {
                    "running": self.running,
                    "tick_seconds": 30.0,
                    "last_pass_at": None,
                    "passes_total": 0,
                    "passes_failed": 0,
                }

            async def start(self):
                self.running = True

            async def stop(self):
                self.running = False

        loop = _FakeLoop()
        monkeypatch.setattr(ne, "_nurture_engine_loop", loop)
        client = self._make_client_one_shot(_FakeSession(execute_results=[]))
        r = client.get("/api/v1/nurture/executions/engine/status")
        assert r.status_code == 200
        assert r.json()["running"] is False


# =====================================================================
# 6. Tick loop (NurtureSchedulerLoop) - pure, no DB
# =====================================================================

class TestNurtureSchedulerLoop:
    @pytest.mark.asyncio
    async def test_start_stop_lifecycle_and_counters(self):
        import asyncio
        from app.services.nurture_scheduler_service import (
            NurtureScheduler,
            NurtureSchedulerLoop,
        )

        # fake scheduler: run_pass just returns a canned summary
        class _FakeSched:
            def __init__(self):
                self.calls = 0

            async def run_pass(self, now=None):
                self.calls += 1
                return {"plans_due": 0}

        fake = _FakeSched()
        sched = NurtureScheduler.__new__(NurtureScheduler)  # not needed; use real with fake? 
        # Build the loop over a real NurtureScheduler whose session_factory is a no-op
        loop = NurtureSchedulerLoop(
            _SchedulerAdapter(fake), tick_seconds=0.01
        )
        await loop.start()
        assert loop.status()["running"] is True
        await asyncio.sleep(0.05)
        await loop.stop()
        assert loop.status()["running"] is False
        assert loop.passes_total >= 1
        assert fake.calls >= 1


class _SchedulerAdapter:
    """Adapts a fake run_pass to the interface NurtureSchedulerLoop calls
    (``scheduler.run_pass()``) without needing a real DB session."""

    def __init__(self, fake):
        self._fake = fake

    def run_pass(self, *a, **k):
        return self._fake.run_pass()


if __name__ == "__main__":
    import pytest as _p

    _p.main([__file__, "-q"])
