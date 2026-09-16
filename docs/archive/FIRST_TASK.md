# P0-001 — Tauri + Vue 3 基础骨架

## Goal

搭建 AI Agent Platform 的 Tauri 2 + Vue 3 基础项目结构，使应用可以正常启动。

## Background

Phase 0 的目标是建立一个可运行的 Windows 桌面应用框架，为后续功能开发奠定基础。

## Scope

- 初始化 Tauri 2 项目
- 配置 Vue 3 + TypeScript + Vite
- 配置 Pinia 状态管理
- 配置 Vue Router
- 创建基础应用壳（App.vue）
- 确保 npm install 成功
- 确保 npm run build 成功

## Out of Scope

- UI 样式设计（后续阶段）
- 路由页面内容（后续阶段）
- 后端 API 连接（后续阶段）
- 真实业务功能（后续阶段）

## Acceptance Criteria

1. 运行 `npm run tauri dev` 可以启动应用
2. 应用窗口正常显示
3. 控制台无错误日志
4. `npm run build` 构建成功
5. 页面可以正常显示

## Dependencies

- 无（这是第一个开发任务）

## Expected Routing

project-orchestrator → frontend-engineer
