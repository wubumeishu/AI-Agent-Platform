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

**Status:** Accepted

**Decision:** Phase 5 delivers the NurturePlan data model + API + segment rule engine only. The runtime execution layer (Scheduler Worker, Step Execution Engine, execution log, error handler) is deferred as a P0 follow-up (tracked on the board).

**Reason:** Keeps the data layer independently testable (84/84 integrity tests pass) while the execution engine (scheduler/executor/logging) is scoped and staffed separately, avoiding a premature speculative implementation.

**Source:** Phase 5 Private Domain Architecture Review P0 #3 (t_a0195813), 2026-09-14

---

## ADR-011  Security & Sensitive-Data Protection (P0 Follow-up)

**Status:** Accepted - Pending Implementation

**Decision:** The Private Domain API surface (and platform API generally) has no JWT auth middleware or RBAC; `account_id` travels as a raw Query param, and sensitive fields (phone, email, WeChat ID in `contact_info` JSON / `customer` / `customer_identity`) are stored and returned in plaintext. This is recorded as a P0 follow-up: add JWT auth middleware + per-account ownership checks, mask PII in API responses, encrypt sensitive fields at rest, and add audit logging.

**Reason:** Privacy + Architecture reviews both returned CHANGES_REQUIRED (t_dcc56882, t_a0195813). Data leakage risk under Personal Information Protection Law (PIPL). Implementation is out of scope for the Phase 5 summary and tracked as a P0 board task.

**Source:** Phase 5 Data Privacy Review (t_dcc56882) + Architecture Review (t_a0195813), 2026-09-14
