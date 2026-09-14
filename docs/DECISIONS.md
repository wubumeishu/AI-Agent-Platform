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

---

## ADR-016  P1-003 Conversation CRUD Router Restored in Shipped `app.main`

**Status:** Accepted - Restored + Verified (revertable)

**Decision:** Re-mount the P1-003 conversation CRUD router in the shipped
`backend/app/main.py`:

```python
from app.routers.conversations import router as conversations_router
app.include_router(conversations_router, prefix="/api/v1")
```

`conversations_router` now exposes `/api/v1/conversations` CRUD
(list / create / get / update / delete / restore / search / sort,
plus `/messages`, `/messages/stats`, and the P1-003 SSE
`/messages/stream`). The mount is mounted **WITH** the `prefix="/api/v1"`
argument, matching every other `/api/v1`-mounted router in `main.py`
(the ADR-012 single-prefix convention); `conversations.py` declares
bare routes (`/conversations`) so no double-prefix results.

**Reason:** P1-003 (t_898db8ab) was a formally delivered + tested
feature whose delivery notes (`backend/docs/P1-003-delivery-notes.md`)
explicitly include the router mount and 95 passing conversation tests.
Yet the shipped `main.py` carried two `# P1-003 shelved:` commented-out
lines that disabled the mount, with **no recorded decision** in
DECISIONS.md, ROADMAP.md, or any doc. The rest of the app is explicitly
scaffolded around P1-003 being live (the `_WorkflowCrmAutoflush` SSE
comment at line ~131 names P1-003's `/messages/stream`; the
`workflow_conversation_bridge`, `conversation_lead_bridge`, and
P5MSG-04 realtime conversation-management read endpoints all assume the
router is present). P5MSG-08 QA (t_affbf15e) proved the router is fully
functional when re-mounted (main flow 24/25 PASS on the QA overlay) —
only the mount was missing — and that the shipped product returns 100%
404 on the entire "open conversation list → detail → load history" main
user flow (P5MSG-08 DEFECT-2).

**Shelving was an undocumented hold, NOT a justified architectural
decision.** Shelving a delivered+tested feature without a recorded
decision violates the orchestrator forbidden-action rule ("change
architecture without recording a decision"). No card, review, or ADR
justified removing it, so the hold is treated as drift and restored.

**Acceptance:** On shipped `uvicorn app.main:app` (no QA overlay),
`GET /api/v1/conversations/` returns 200 (not 404), and
`POST /api/v1/conversations/` returns 201. Verified in the follow-up
verification task.

**Downstream note:** P5MSG-08 DEFECT-1 (P0, t_8c059295) — the
`ConversationBase.channel` pattern 500 on `douyin`/`xiaohongshu` rows —
now becomes *reachable* on the shipped list/detail endpoints because the
router is mounted. DEFECT-1 must land before the P5MSG main-flow
"100% pass" acceptance is re-tested; this ADR does not itself fix the
channel pattern.

**Follow-up:** Restored mount is a 2-line, reversible change; re-shelving
is only permitted with a new recorded ADR.

**Source:** P5MSG-08 QA defect P5MSG-D3, decided + applied by
project-orchestrator t_3610a964, 2026-09-14

---

## ADR-017  Message State-Transition Audit: ExecutionLog Is the Single Source of Truth (dual-write SoT convergence + P5MSG-02 ExecutionLog reuse)

**Status:** Accepted - Implemented (2026-09-14, P5MSG-12-AR-1, t_8bd0d6a9)

**Decision:** The message delivery state-machine audit trail has exactly
**one** write source: the platform `execution_log` table
(`ExecutionLog`, `execution_type='message_status'`).

1. **SoT choice (P0-1 dual-write convergence).** P5MSG-02's
   `MessageService.update_status` previously wrote the *same* transition to
   two stores atomically — a per-row append-only `messages.receipts` JSONB
   **and** an `execution_log` row (plus the enqueue path logged a row but
   wrote no receipt). That is a textbook dual-write that violates
   single-source-of-truth. Decision: **`execution_log` is the audit SoT.**
   The per-row `messages.receipts` JSONB is **demoted to a deprecated,
   read-only legacy column** — it is no longer written by the state
   machine. The API-facing read (`GET /api/v1/messages/{id}/receipt`) now
   **projects** the receipt trail from the SoT (`_project_receipts`),
   excluding the `to='queued'` enqueue row so the API surface is unchanged.
   `messages.last_receipt_at` is kept as a lightweight, denormalized
   "when last acknowledged" scalar (an API-facing convenience subset of
   the SoT, explicitly non-authoritative).

2. **P5MSG-02 ExecutionLog reuse (P0-2 unrecorded decision).** P5MSG-02
   deliberately reuses the *workflow* subsystem's `execution_log` to record
   message-state audit (logical-UUID, no FK, per the ADR-013 precedent)
   instead of introducing a message-domain-specific log table. This ADR
   records that decision: it was chosen to (a) reuse the platform's
   existing, already-migrated audit/observability table + retention
   cleanup, (b) keep the message domain decoupled from the workflow
   runtime per ADR-004/005, and (c) avoid a second, parallel audit sink
   that would reintroduce the dual-write problem. `execution_type`
   discriminates domain (`'message_status'` vs `'task'`/`'workflow'`/...)
   so domains share one table without cross-domain FKs.

**Reason:** Two stores recording the same fact guarantees they will drift
under a partial failure or a future consumer, and forces every downstream
audit/metrics reader (Phase 6 Analytics, P6AN-01) to reconcile two sources.
A single SoT keeps `execution_log` the authoritative trail (as the known-
issue pool `phase6_data_availability` already assumed) while the deprecated
JSONB remains readable for legacy rows during a transition window.

**Why keep the JSONB at all (not dropped now):** the `receipts` column and
`migration 023` already ship and existing rows carry a populated trail.
Dropping the column / backfilling legacy rows from the log is schema
churn with no functional need in V1 — legacy rows simply stop receiving
new entries and the column is read-only until a follow-up migration.

**Follow-up (tech debt, tracked):**
- Backfill + drop: a migration that (a) backfills `messages.receipts` from
  the `execution_log` SoT for legacy rows, then (b) drops the column and
  `idx_messages_last_receipt_at` (or keeps `last_receipt_at` as the
  denormalized scalar), so only one column family remains. Non-blocking.
- P1-1 (recorded in-card, not a separate card): the message-domain
  `channel` value domain (`MESSAGE_CHANNELS`, 10 items) is a hardcoded
  superset that deviates from the Phase-1 resource-layer single source
  (`ChannelType` in `private_domain` + `Platform` seeds). The
  conversation-side half was aligned by P5MSG-D2 (t_8c059295:
  `ConversationBase.channel` pattern → `MESSAGE_CHANNELS ∪ legacy`).
  **Deriving the message-domain channel domain from the resource layer is
  recorded here as a follow-up and is intentionally NOT implemented in this
  card** (the channel *adapters* that would consume a derived domain are
  P5MSG-03's completed scope). Phase 6 channel-mix analytics should use the
  resource-layer domain once derived.

**Acceptance:** P5MSG regression suite green (351 passed; 2 pre-existing
out-of-scope failures in `test_crm_conversation_integration` = P5MSG-12-
LEAD-ROUTE Phase-3 gap, unchanged from baseline). `execution_log` is the
only write path for the message audit trail; `get_receipt` reads from the
SoT; no test depends on the JSONB being written.

**Source:** P5MSG-10 architecture review P0-1/P0-2 (t_5c4341d4), carried
forward by P5MSG-12 phase summary (t_09792da5) as P5MSG-12-AR-1; decided +
implemented by code-architecture-reviewer t_8bd0d6a9, 2026-09-14
