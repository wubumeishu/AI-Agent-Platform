# AI Agent Platform - Phase 3 CRM / Lead 阶段总结

**ID**: t_328f2ac2 (t_crm_017)
**日期**: 2026-09-14 13:10
**作者**: project-orchestrator (Agnes)
**状态**: CRM 实现层 13/14 完成；安全/隐私 P0 与 3 个运行时 P0 为已知未决项（已记录，不阻断 Phase 4+）

---

## 1. 目标

汇总 Phase 3 CRM / Lead Management 阶段成果：功能清单、技术债务、架构决策变更、测试与审查报告、项目文档更新。

---

## 2. Phase 3 Kanban 任务盘点

### 14 / 17 完成（3 running 于本总结时点）

| ID | 任务 | 负责 | 状态 |
|----|------|------|------|
| t_ce500779 | CRM 后端框架 + 数据库 Schema（7 表） | backend-engineer | done |
| t_27ad6650 | Customer 实体 + CustomerIdentity（13/13 测试通过） | backend-engineer | done |
| t_20d0231a | Lead 管理 + 意向评分（30/30 单测 + 18/18 E2E） | backend-engineer | done |
| t_477a97e2 | 标签系统（22 E2E + 79 pytest 全绿） | backend-engineer | done |
| t_ac64e62b | 生命周期阶段 + 漏斗流水线 | backend-engineer | running |
| t_e101436e | Customer 360 | backend-engineer | done |
| t_4b56018e | CRM + Conversation 集成 | backend-engineer | running |
| t_7c22822f | CRM + Agent 集成 | backend-engineer | done |
| t_6d0786b8 | CRM 前端框架 + 路由 | frontend-engineer | done |
| t_4e81154a | Customer 列表 + 详情 UI | frontend-engineer | running |
| t_f260781a | Lead 管理 UI | frontend-engineer | done |
| t_1eb443fb | CRM 用户流测试 | qa-engineer | done (BLOCKED 记录：依赖未就绪时) |
| t_dd81f28c | CRM 数据完整性测试 | qa-engineer | done - FAIL（13 项 7 通过 + 6 bug，SQLAlchemy CustomerIdentity/Tag 问题） |
| t_8119f738 | CRM 端到端 QA | qa-engineer | done - FAIL - 3 P0 阻断 bug，0/35 通过 |

**衍生修复卡**（QA/Review 发现后由 orchestrator 创建并已完成）：

| ID | 任务 | 状态 |
|----|------|------|
| t_b6b64212 | P1: 路由前缀去重（CRM 双前缀 /api/v1/api/v1/...） | done |
| t_a2b0e658 | P0: 服务默认 DSN 无凭据无法连 prod DB - 改为从配置解析 | done |

---

## 3. 截至 2026-09-14 的功能清单

### backend (FastAPI + SQLAlchemy async + PostgreSQL)

- **Customer / CustomerIdentity** - CRUD、身份解析（phone/email/external_id）、merge；`001_crm_lifecycle` 迁移含 7 张表（customer, customer_identity, lead, tag, lifecycle_stage, customer_activity, customer_note）
- **Lead** - CRUD、来源追踪（source_type 白名单 + source_id）、可配置 Intent Scoring（4 维度权重，`GET /crm/leads/intent-config`）、状态机 new→contacted→qualified→converted、`{code,message,data}` 响应信封对齐 PHASE1-API-SPEC
- **Tag** - 实体 CRUD、层级（父子）、客户/线索批量关联、统计接口
- **Lifecycle / 漏斗** - 阶段枚举 + 统计接口（任务 running，基线代码已存在）
- **Customer 360** - 详情聚合 + 会话/活动/记忆/下一步
- **集成** - Conversation→Lead 桥（conversation_lead_bridge）、Agent 集成
- **路由约定（ADR-012）**: 单一 `/api/v1` 前缀 - CRM 子路由只带模块段，main.py 统一加前缀

### frontend (Vue 3 + TypeScript + Pinia)

- `/crm/customers`、`/crm/leads` 视图 + Pinia store + API client
- API client 兼容双格式响应（CRM 信封 `{code,message,data}` 与原生 FastAPI）

---

## 4. 技术债务（P0 / P1 / P2）

### P0（已知未决，记录不隐藏）

| # | 问题 | 来源 | 现状 |
|---|------|------|------|
| PD-1 | 敏感数据明文存储（email/phone 无加密） | 隐私审查 t_f075831b P0-001 | 未修 - 归入平台级安全 P0（ADR-011） |
| PD-2 | API 响应无 PII 脱敏 | t_f075831b P0-002 | 未修 |
| PD-3 | 无认证授权（CORS `*` + allow_credentials） | t_f075831b P0-003 | 未修 - ADR-011 跟踪 |
| PD-4 | 身份解析接口未授权，可枚举用户 | t_f075831b P0-004 | 未修 |
| PD-5 | 无数据保留策略（仅软删除） | t_f075831b P0-005 | 未修 |
| RT-1 | prod 库缺 7 张 CRM 表（legacy create_all + stamp 021 遗留，与 001_crm_lifecycle DDL 分叉） | t_20d0231a 备注 / t_8119f738 P0-003 | 未修 - 待 022+ 迁移按现行 ORM 补表（后续卡） |

> 上游 E2E QA (t_8119f738) 的 3 个 P0 中：路由双前缀已修（t_b6b64212）、DSN 无凭据已修（t_a2b0e658）、数据库未配置归入 RT-1；端口 8000/8001 双服务为本地多服务现象，canonical 服务为 8001。

### P1

| # | 问题 | 来源 |
|---|------|------|
| P1-A | 缺 Pydantic Response Schema（多数 service 返回裸 dict；Lead 模块已补） | 架构审查 t_5a2cbc46 P1-004 |
| P1-B | lifecycle_stage_code 用字符串而非 FK 约束 | t_5a2cbc46 P1-003 |
| P1-C | merge_customers 缺事务保护 | t_5a2cbc46 P2-003（降级 P1 处理） |

### P2

| # | 问题 |
|---|------|
| P2-A | 默认阶段数据硬编码于 service，未走 migration seed |
| P2-B | 分页参数校验不完整 |
| P2-C | 日志配置未过滤敏感字段（对应隐私审查 P2-001） |
| P2-D | 既有测试失败：test_data_integrity `Lead(name=)` 与现行 customer 关联式 model 不匹配；test_memory_api / test_phase2_integration_qa MagicMock 泄漏 |

---

## 5. 测试与审查报告

### 5.1 E2E QA - t_8119f738（FAIL，0/35）

- 3 个 P0 阻断（路由双前缀 / 端口冲突 / DB 未配置），测试通过率 0%
- 报告：`I:\hermes\kanban\attachments\t_8119f738\CRM_E2E_QA_Report.md`
- 阻断后修复进展：路由双前缀 → t_b6b64212 done；DSN → t_a2b0e658 done；CRM 表缺失 → RT-1（后续卡）
- **需待 RT-1 完成后重跑 E2E 验证**（后续卡）

### 5.2 数据完整性测试 - t_dd81f28c（FAIL）

- 13 项 7 通过，6 个 bug（SQLAlchemy CustomerIdentity/Tag 相关）
- 后续单模块验证已全部通过：Lead 30/30、Tag 79/79 相关用例、Customer 13/13

### 5.3 架构审查 - t_5a2cbc46（CHANGES_REQUIRED，质量 72/100）

- P0-001 CustomerIdentity 语法错误：已验证修复（现可正常导入）
- P1-001 路由前缀重复：已修（t_b6b64212）
- P1-002 Lead 路由未注册：已修（经 `crm/routers/__init__.py` 聚合器挂载 lead+lifecycle）
- P1-003/P1-004 + P2 三项：记录于本总结 §4 P1-B/C、P2-A/B
- 报告：`I:\hermes\kanban\attachments\t_5a2cbc46\review-report.md`

### 5.4 隐私审查 - t_f075831b（CHANGES_REQUIRED，5 P0）

- 5 P0 + 1 P2，全部记录于 §4 P0 表；归属平台级安全 P0（ADR-011），非 CRM 专属实现范围
- 报告：`I:\hermes\kanban\attachments\t_f075831b\review-report.md`

---

## 6. 架构决策变更

- **ADR-012 API 路由单一前缀约定**（新增，见 DECISIONS.md）：
  canonical 路径为 `/api/v1/...`；子路由只带模块段，由 main.py 统一加前缀；
  CRM 聚合器 `crm/routers/__init__.py` 仅承载 main.py 未直接挂载的子路由（lead + lifecycle），避免重复注册。
- **ADR-011（既有）吸收**：CRM 隐私审查 5 P0 并入平台级安全 P0 follow-up，Phase 3 不单独实现。

---

## 7. 后续任务（本总结创建）

1. **RT-1 prod 库 CRM 表落地**（022+ 迁移，按现行 ORM model）→ 解锁 E2E 复测
2. **前端 API base URL 修正**（默认 8000 → 8001 canonical 服务，或经 VITE_API_BASE_URL 注入）
3. **E2E QA 复测**（RT-1 完成后，验证 35 项场景）

> 不在本阶段范围：Phase 4+ 规划、技术重构、平台级安全 P0 实现（ADR-011 卡链处理）。

---

## 8. 备注

- `docs/CURRENT_FOCUS.md` 当前仍写 "Phase 2 当前焦点 / 暂时禁止 CRM"，与 Phase 3/5/6 并行推进的板面状态不符（board unblock 注释已放行，后端工程师 t_20d0231a 曾据此 block 一次）。属文档过期，建议下次 CURRENT_FOCUS 更新时修正。
- 验证环境：Windows 10, Python 3.11.16, FastAPI backend, pytest。
