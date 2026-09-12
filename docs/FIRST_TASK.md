# P0-000 — 研发体系初始化

## Goal

完成 AI Agent Platform 的 AI 员工体系、协作规则、项目配置、架构基线和看板开发规则，使后续开发可以在受控流程下进行。

## Scope

- 8 个核心 Agent 配置完成
- project-orchestrator SOUL.md 完成
- 各角色擅长领域完成
- 编排者配置正确
- 默认负责人配置正确
- 自动分解分派开启
- PROJECT.md
- AGENTS.md
- ARCHITECTURE.md
- DEVELOPMENT_RULES.md
- ROADMAP.md
- DECISIONS.md

## Out of Scope

- Tauri 编码
- Vue 页面实现
- FastAPI 实现
- BitBrowser 接入
- AI Provider 接入
- CRM 实现

## Expected Routing

Project Orchestrator → PM / Architect / Developer / QA / Reviewer

## Acceptance Criteria

1. Hermes 能识别 8 个角色。
2. 未指定专业负责人时，由 Product Manager 作为默认负责人。
3. 自动分解分派处于开启状态。
4. 项目文档存在并可被 Agent 读取。
5. Agent 能根据任务类型选择正确负责人。
6. 开发完成后的任务不会直接跳过 QA / Review（需要时）。
7. Scope creep 会创建新任务而不是污染当前任务。
8. 项目能够开始第一个真实开发任务：P0-001 Desktop Foundation。
