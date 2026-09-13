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

## Phase 4 — CRM

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
