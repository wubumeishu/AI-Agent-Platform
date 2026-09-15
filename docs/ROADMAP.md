# ROADMAP.md
## AI Agent Platform Roadmap v1.0

## Phase 0 — Team & Project Foundation

目标：建立 AI 研发团队与可控开发机制。

### Epic 0.1 Team

- 配置 8 个核心 Agent
- 配置 Soul.md
- 配置看板编排者
- 配置默认负责人
- 开启自动分解分派
- 建立 AGENTS.md

### Epic 0.2 Project Baseline

- PROJECT.md
- ARCHITECTURE.md
- DEVELOPMENT_RULES.md
- ROADMAP.md
- ADR 基础目录

### Epic 0.3 Desktop Foundation

- Tauri
- Vue 3
- 基础 Layout
- 路由
- Dashboard 空状态
- Settings

---

## Phase 1 — Resource Layer

### Agent
- Agent CRUD
- Agent detail
- Agent configuration

### Persona
- Persona CRUD
- Style parameters
- Versioning baseline

### Account
- Account CRUD
- Status
- Agent binding
- Browser binding
- Proxy binding

### Platform
- Platform registry
- Capabilities
- Adapter interface

### Browser
- BrowserProvider
- BitBrowserProvider
- Profile management
- Connection status

### Proxy
- Proxy CRUD
- Binding
- Connection checks

---

## Phase 2 — AI & Conversation

- AI Provider
- Model configuration
- Prompt management
- Agent context
- Conversation
- Message
- Persona generation
- Memory
- Knowledge
- Intent

---

## Phase 3 — Workflow & Automation

> Status (2026-09-15): Workflow / Scheduler implementation, QA and both reviews complete. E2E QA 72/72 live checks PASS (condition satisfied: seconds-cron P1 t_61bc0556 + create_lead P2 t_52db7696 both done and verified); reliability re-review t_a3f82e43 APPROVED (regression 357/357 + real-Postgres E2E 9/9). Known issues: serial tick low-freq limit (accepted, P2-R6), CORS `*`+credentials (ADR-015, platform-wide security lane), ExecutionLog no-FK (ADR-013, tech debt). Phase summary + test/review reports + known-issue pool: `.cache/phases/phase4-workflow-summary/` (WF-phase-summary.md, WF-test-report.md, WF-review-report.md, wf-known-issues.json). Phase 6 gate t_e94a362e released by t_a3f82e43.

- Workflow model
- Trigger
- Condition
- Action
- Delay
- Branch
- Scheduler
- Queue
- Worker
- Execution log

---

## Phase 4  CRM

> Status (2026-09-14): Implementation layer 13/14 board tasks done; known open items: prod DB missing 7 CRM tables (follow-up card), frontend base-URL default points at 8000, security/privacy P0s tracked under ADR-011. E2E QA re-run pending. See docs/PHASE-3-SUMMARY.md.

- Customer
- CustomerIdentity
- Customer 360
- Lead
- Tags
- Lifecycle stages
- Notes
- Activities

---

## Phase 5 — Private Domain

> Status (2026-09-14): Implementation layer complete (10 tables, 24 API endpoints, segment rule engine, CRM integration, 8 frontend views, 84/84 integrity tests). Security P0 follow-ups (auth/RBAC + sensitive-data protection) and the NurturePlan execution engine remain open - see docs/PHASE-5-SUMMARY.md.

- Private channels
- Nurture plan
- Content library
- Follow-up tasks
- Customer segmentation
- Deal pipeline

---

## Phase 6 — Analytics & Optimization

> Status (2026-09-15): Phase 6 Analytics & Optimization implementation (9 backend + 3 frontend cards), QA and architecture review complete. E2E QA (P6AN-15, t_31ca8734) verdict PASS (main chain DB→API→UI all green, no P0/P1 leftover). Architecture review (P6AN-16, t_67f18134) verdict CHANGES_REQUIRED: no P0; single P1 (analytics surface unauthenticated + no tenant isolation) FIXED in t_3e806a29 (ADR-018, including P2-4 CORS whitelist); 5 P2 items — P2-1 caliber, P2-2 router hotspot, P2-3 naive/tz DDL, P2-5 prod-DB drift filed as P2 follow-up cards (P6AN-17), P2-4 closed with the P1 card. Regression 272/275 (2 pre-existing shared-test-DB drift + 1 pre-existing test-route harness nit, both filed: t_dc92c614 DEF-3 P2 / t_645352c1 DEF-8 P3, in flight). Phase summary: `docs/PHASE-6-SUMMARY.md`.

- Dashboard
- Acquisition funnel
- Conversation metrics
- Lead conversion
- Private-domain conversion
- Deal metrics
- Agent performance
- Strategy experiments
- ROI

---

## Phase 7 — Future

暂缓：

- AdsPower Provider
- LocalChromium Provider
- More platforms
- Plugin marketplace
- Cloud service
- Team collaboration
- Multi-tenant SaaS
- Mobile application

只有明确开启时才进入看板。
