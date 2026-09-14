# DECISIONS.md
## Architecture & Product Decision Log

## ADR-001 — V1 使用 Tauri 作为桌面框架

**Status:** Accepted

**Decision:** Windows 桌面端 V1 使用 Tauri + Vue 3。

**Reason:** 需要桌面应用能力，同时希望保持前端开发效率与较低资源开销。

---

## ADR-002 — V1 只支持 BitBrowser

**Status:** Accepted

**Decision:** 第一阶段 BrowserProvider 只实现 BitBrowserProvider。

**Reason:** 降低初期复杂度，先完成真实闭环。

**Future:** 未来可扩展其他 Provider。

---

## ADR-003 — Agent 与 Persona 分离

**Status:** Accepted

**Decision:** Persona 描述“是谁和怎么说”，Agent 描述“谁在工作并拥有何种能力”。

---

## ADR-004 — Platform Adapter 与业务逻辑分离

**Status:** Accepted

**Decision:** 平台差异通过 Adapter 隔离。

---

## ADR-005 — Browser Provider 与业务逻辑分离

**Status:** Accepted

**Decision:** 业务层不得直接依赖 BitBrowser 实现细节。

---

## ADR-006 — Memory 与 Knowledge 分离

**Status:** Accepted

**Decision:** Memory 表示发生过什么及客户相关记忆；Knowledge 表示可查询的业务知识。

---

## ADR-007 — QA 与 Reviewer 独立于开发角色

**Status:** Accepted

**Decision:** 开发员工不应独自完成开发、验收和最终质量确认。

---

## ADR-008 — Project Orchestrator 负责调度而非万能开发

**Status:** Accepted

**Decision:** project-orchestrator 负责任务分解、路由、依赖、流程和看板状态，不作为默认万能开发者。

---

## ADR-009  Data Model Conventions (Private Domain & Beyond)

**Status:** Accepted

**Decision:** All entity tables use soft-delete `is_deleted` flag + UUID primary keys + `DateTime(timezone=True)` timestamps. Flexible/variable fields (contact_info, tags, extra_config, filter_config, sequence_steps) are stored as JSON columns.

**Reason:** Consistent lifecycle handling, timezone-correctness across the desktop app, and schema flexibility without per-feature migrations.

**Source:** Phase 5 Private Domain Architecture Review (t_a0195813), 2026-09-14

---

## ADR-010  NurturePlan Data/Execution Split

**Status:** Implemented (2026-09-14, t_a2ce2cae)

**Decision:** Phase 5 delivered the NurturePlan data model + API + segment rule engine only. The runtime execution layer (Scheduler Worker, Step Execution Engine, execution log, error handler) is deferred as a P0 follow-up (tracked on the board).

**Reason:** Keeps the data layer independently testable (84/84 integrity tests pass) while the execution engine (scheduler/executor/logging) is scoped and staffed separately, avoiding a premature speculative implementation.

**Source:** Phase 5 Private Domain Architecture Review P0 #3 (t_a0195813), 2026-09-14

**Implementation (t_a2ce2cae, P1):**
The deferred execution layer has been landed, split into a pure core + a thin
platform adapter (the repo's standard rule - AI/platform logic separated,
testable without a DB):

- **Pure core** - `app/services/nurture_schedule.py` (plan due-detection for
  fixed / drip / triggered, cumulative step sequencing that honours
  `delay_hours`, deterministic exponential backoff + retry / dead-letter
  decision, automatic/dynamic segment sync predicate) and
  `app/services/nurture_step_executor.py` (the `StepExecutionEngine`: runs the
  due steps of one run, resolves content via an injected `ContentProvider` -
  reusing a library item or generating AI content - and emits per-step
  `StepExecutionResult`s).
- **Platform adapter** - `app/services/nurture_scheduler_service.py`:
  `DBContentProvider` bridges to the Phase-5 `ContentGenerationService`
  (LLM optional, template fallback), `NurtureScheduler.run_pass` picks up due
  active plans with no manual trigger, persists a `NurtureStepExecution` row
  per step and drives retry / dead-letter + segment sync; `NurtureSchedulerLoop`
  is the in-process tick worker; the execution-log read API
  (`list_plan_executions` / `list_dead_letters` / `get_plan_execution_progress`).
- **Execution log table** - `nurture_step_execution` (model
  `app/db/models/nurture_execution.py`, Alembic `025_nurture_step_execution`).
- **API** - `app/routers/nurture_execution.py` under `/api/v1/nurture/executions`
  (per-plan history + progress, dead-letter queue, manual trigger, segment sync,
  and opt-in background engine start/stop/status). The background tick is OPT-IN
  (`POST /nurture/executions/engine/start` or `NURTURE_SCHEDULER_AUTOSTART=1`),
  mirroring the Phase-4 scheduler engine's controlled start/stop semantics.

Tests: `backend/tests/test_nurture_execution.py` (45 tests: pure scheduling,
retry/backoff/dead-letter, step engine, DB-adapter run_pass, the Phase-5 content
bridge, segment sync, execution-log queries + REST endpoints, tick loop).
All green alongside the 84-integrity + nurture + content-generation suites.

---

## ADR-011  Security & Sensitive-Data Protection (P0 Follow-up)

**Status:** Accepted - Pending Implementation

**Decision:** The Private Domain API surface (and platform API generally) has no JWT auth middleware or RBAC; `account_id` travels as a raw Query param, and sensitive fields (phone, email, WeChat ID in `contact_info` JSON / `customer` / `customer_identity`) are stored and returned in plaintext. This is recorded as a P0 follow-up: add JWT auth middleware + per-account ownership checks, mask PII in API responses, encrypt sensitive fields at rest, and add audit logging.

**Reason:** Privacy + Architecture reviews both returned CHANGES_REQUIRED (t_dcc56882, t_a0195813). Data leakage risk under Personal Information Protection Law (PIPL). Implementation is out of scope for the Phase 5 summary and tracked as a P0 board task.

**Source:** Phase 5 Data Privacy Review (t_dcc56882) + Architecture Review (t_a0195813), 2026-09-14

---

## ADR-012  API Routing: Single /api/v1 Prefix Convention (CRM Double-Prefix Fix)

**Status:** Accepted - Implemented

**Decision:** Canonical API paths are single-prefixed `/api/v1/...`. Every sub-router carries ONLY its module segment (e.g. `/crm/leads`, `/360`); `main.py` adds the `/api/v1` prefix exactly once via `include_router(router, prefix="/api/v1")`. For the CRM module, `crm/routers/__init__.py` exposes an aggregate router that includes ONLY the sub-routers not mounted directly by `main.py` (lead + lifecycle). Customer / tag / customer_360 are mounted directly by `main.py` and must NOT appear in the aggregate, to avoid duplicate route registration and double-prefix paths like `/api/v1/api/v1/crm/...`.

**Reason:** E2E QA (t_8119f738) found all CRM endpoints returning 404 due to the double prefix; Architecture Review (t_5a2cbc46 P1-001/P1-002) confirmed router-level prefix confusion plus an unregistered Lead router. The fix landed in t_b6b64212 (strip `/api/v1` from all 5 CRM sub-routers; aggregate mounts lead+lifecycle only).

**Source:** t_8119f738 (CRM E2E QA, P0-001), t_5a2cbc46 (Architecture Review), t_b6b64212 (fix), 2026-09-14

---

## ADR-013  ExecutionLog Uses Logical-UUID References (no FK) — V1 Tech Debt

**Status:** Accepted - Recorded as Tech Debt (P1-4)

**Decision:** `execution_log.workflow_id` / `queue_id` / `worker_id` / `task_id` are plain indexed UUIDs with **no foreign-key constraint** to their target tables. This is intentional (t_wf_005): it lets the execution-log table migrate and be read independently of the runtime tables, and matches the platform's logical-UUID decoupling convention.

**Reason:** Hard FKs would couple the log to the runtime tables' lifecycle and block independent migration; the V1 trade-off accepts a soft referential integrity (a log row may transiently point at a deleted object).

**Follow-up (tech debt):** After the runtime schema stabilises, promote these to real FKs (or add a documented, indexed soft-reference policy + a periodic integrity sweep) so a dangling reference is guarded rather than silently allowed. Tracked here, not blocking.

**Source:** Workflow Architecture Review t_c81d72fe P1-4, implemented/recorded in t_c94bba06, 2026-09-14

---

## ADR-014  Scheduler Execution Wiring + Auto-Start (P1-2)

**Status:** Accepted - Implemented

**Decision:** The scheduler engine's default dispatcher is now the real `QueueDispatcher` (`app/services/scheduler/dispatcher.py`), which enqueues each fired schedule as a `WorkflowTask` onto the workflow's queue (or a named default queue) via the t_wf_004 `QueueWorkerEngine`. Timed (cron/interval) workflows therefore actually execute end-to-end instead of the old record-only `NoopDispatcher`. Auto-start is **on by default**: `main.py` startup calls `get_scheduler_engine().start()` + `load_schedules()` so a restarted process re-arms persisted schedules, honouring the engine docstring's "restarts pick up persisted schedules" contract.

**Config knobs:** `SCHEDULER_AUTOSTART=0` restores explicit-start semantics (`POST /api/v1/schedulers/engine/start`) for deployments that intentionally disable timed execution; `SCHEDULER_DEFAULT_QUEUE` overrides the fallback queue name (default `workflow-scheduler`); a missing queue is a soft no-op (`{"enqueued": false, "reason": "no-queue"}`) unless `QueueDispatcher(require_queue=True)` is used.

**Reason:** P1-2 (review t_c81d72fe): the scheduler was a "record-only shell" (fire wrote an ExecutionLog but ran no action) and restarts silently dropped persisted schedules, contradicting the committed docstring. Wiring a real dispatcher + auto-start makes timed workflows genuinely available without a manual operator step, while keeping execution off by an env flag for deployments that don't want it.

**Source:** Workflow Architecture Review t_c81d72fe P1-2, implemented in t_c94bba06, 2026-09-14

---

## ADR-015  CORS `*` + credentials — Security Follow-up Handoff (P2-5)

**Status:** Accepted - Recorded / Handed to Security Task

**Decision:** `main.py` currently sets `allow_origins=["*"]` together with `allow_credentials=True`. This is a known-insecure CORS combination (star origins with credentialed requests is disallowed/misleading by browser CORS rules) and is flagged as a security hardening item, **not** a change to make in this workflow card.

**Reason:** CORS hardening is out of scope for the Workflow architecture review (its security surface is a dedicated task). Record-only here so it is not lost; a dedicated security task should restrict origins to the deployed frontend and/or drop credentialed wildcard CORS.

**Follow-up (tech debt / security):** Owned by the security-hardening task; do not "fix" casually from the workflow lane.

**Source:** Workflow Architecture Review t_c81d72fe P2-5, recorded in t_c94bba06, 2026-09-14
