# AI Agent Platform - Phase 6 Analytics & Optimization 阶段总结

**ID**: t_adcbbb97 (t_an_017)
**日期**: 2026-09-15
**作者**: project-orchestrator (Agnes)
**状态**: Phase 6 Analytics 实现层（后端 9 + 前端 3）+ QA（3）+ 架构审查（1）全部完成；E2E QA 判定 **PASS**；架构审查判定 **CHANGES_REQUIRED**（无 P0；P1 唯一项已修复）。**无 P0/P1 遗留**；4 张 P2 跟进卡已建（P2-1/2/3/5），P2-4 已随 P1 卡修复；2 张 P2/P3 缺陷卡在途。Phase 6 验收 Gate **放行**。

> 依据来源：上游 P6AN-15 E2E QA（t_31ca8734）与 P6AN-16 架构审查（t_67f18134）两份 parent handoff + 对 25 张 P6AN 板卡的活库核对。本报告以真实板面/报告为准，非推测。

---

## 1. 目标

汇总 Phase 6 Analytics & Optimization 阶段成果：功能清单、QA/审查结论、技术债务分级、架构决策变更、项目文档更新。范围为 P6AN-01~17；**Phase 7（AdsPower / LocalChromium Provider、插件市场）不在本阶段**。

---

## 2. Phase 6 Kanban 任务盘点（25 张，16 实现/前端 + 4 QA + 2 缺陷在途 + 3 P1/P3 修复卡）

### 实现层（后端 9 + 前端 3）— 全部 done

| 板卡 ID | 任务 | 负责 | 状态 |
|---------|------|------|------|
| t_e94a362e | P6AN-01 Analytics 基础框架 + Schema（5 表 + migration 028/029） | backend | done |
| t_8c512f23 | P6AN-02 Dashboard 概览 API（Agent/对话/转化/活跃度 KPI） | backend | done |
| t_0d09e4b8 | P6AN-03 Acquisition Funnel 获客漏斗 API | backend | done |
| t_ae6880c6 | P6AN-04 Conversation Metrics 对话指标 API | backend | done |
| t_d4865475 | P6AN-05 Lead Conversion 线索转化 API | backend | done |
| t_24e62012 | P6AN-06 Private Domain Conversion 私域转化 API | backend | done |
| t_1330e1cc | P6AN-07 Agent Performance Agent 绩效 API | backend | done |
| t_98039e0f | P6AN-08 Strategy Experiment 策略实验 API（A/B CRUD） | backend | done |
| t_46f3916b | P6AN-09 ROI 分析 API | backend | done |
| t_d0a9f89d | P6AN-10 Analytics 前端框架 + Dashboard UI | frontend | done |
| t_394feb9a | P6AN-11 Funnel + Conversion 图表 UI | frontend | done |
| t_67c18832 | P6AN-12 Agent Performance + Experiment UI | frontend | done |

### QA（3）— 全部 done

| 板卡 ID | 任务 | 负责 | 结论 |
|---------|------|------|------|
| t_bbd45760 | P6AN-13 用户流程测试 | qa | 发现 DEF-1(P1) + DEF-2(P2)，已派修复 |
| t_5d2ead18 | P6AN-14 数据准确性测试 | qa | 发现 DEF-5/6/7(P3)，已派修复 |
| t_31ca8734 | P6AN-15 E2E QA（DB→API→UI 全链路验收） | qa | **PASS**（主链路全绿，无 P0/P1 遗留） |

### 架构审查（1）— done

| 板卡 ID | 任务 | 负责 | 结论 |
|---------|------|------|------|
| t_67f18134 | P6AN-16 架构审查 | reviewer | **CHANGES_REQUIRED**（无 P0；1 P1 + 5 P2；P1-1 已建卡 t_3e806a29 并修复） |

### 缺陷修复卡（QA/审查衍生）

| 板卡 ID | 缺陷 | 级别 | 状态 |
|---------|------|------|------|
| t_45d18bdf | DEF-1 P6AN-02 Dashboard 概览恒 500（naive/aware datetime 冲突） | P1 | done |
| t_18229849 | DEF-2 P6AN-02 Agent 过滤下拉全页 422（page_size=200 越后端 le=100） | P2 | done |
| t_bb8e10d1 | DEF-5 P6AN-03 漏斗坏 from/to 时间戳 → 500（应 422）+ alias 静默忽略 | P3 | done |
| t_b20a2bb4 | DEF-6 P6AN-05 线索转化泄漏软删 agent_customer_binding | P3 | done |
| t_7378c374 | DEF-7 P6AN-05 比率/周期未四舍五入 | P3 | done |
| t_3e806a29 | P1-1 analytics 表面加认证 + 租户隔离（同卡顺手修 P2-4 CORS） | P1 | done |
| t_dc92c614 | DEF-3 P6AN-05 aware-UTC 时间边界 → 500（归一 naive/aware 解析） | P2 | **running** |
| t_645352c1 | DEF-8 P6AN-03 test_route_registered 在 FastAPI 0.141 _IncludedRouter 下失配（测试器写法） | P3 | **running** |

---

## 3. 截至 2026-09-15 的功能清单

### 后端（FastAPI + SQLAlchemy async + PostgreSQL）

- **P6AN-01 基础层** — 5 张 analytics 定义表（`dashboard_widget` / `funnel_step` / `metric_definition` / `experiment` / `experiment_result`），迁移 028（029 建 experiment_result 硬 FK 表）。迁移幂等：CREATE/index 走 live `to_regclass` / `pg_indexes` 守卫，可在 fresh 与 legacy(stamped) 库重跑不静默跳建索引。跨域引用用软引用（metric_code / funnel_code 为 TEXT 非 FK），唯一硬 FK 为 experiment_result.experiment_id→experiment.id（CASCADE，两表原子创建）。
- **P6AN-02 Dashboard** — Agent/对话/转化/活跃度核心 KPI 概览；`dashboard_cache.py` Redis 可用则异步原生、缺失/故障一次性降级 in-memory TTL（缓存仅作性能优化非正确性要求，任何故障降级重算 + 1 条 warning，不打断 API）。实测冷 P95=51.9ms@10k（warm 命中 0.2ms/0 SQL）。
- **P6AN-03 获客漏斗** — 曝光→点击→对话→留资→私域 4 stages + 各步转化率（round 4dp）+ 渠道/时间维度。
- **P6AN-04 对话指标** — 时长/轮次分布、意图准确率、满意度 proxy、Agent 对话绩效对比。
- **P6AN-05 线索转化** — 来源分布、New→Contacted→Qualified→Converted 转化、时效（首触时长）、Agent 效率；**口径：Lead.status=='converted'**。
- **P6AN-06 私域转化** — 渠道效率、NurturePlan/FollowUpTask 效果、LTV proxy、渠道 ROI；**成交口径：DealItem.status=='won'**。
- **P6AN-07 Agent 绩效** — 对话量/转化率/效率、排行榜；**成交口径：Lead.lifecycle_stage_code in {成交}**。
- **P6AN-08 策略实验** — Experiment A/B CRUD（分组/份额/指标/周期）、状态机（draft→running→paused/completed）、结果快照 + 显著性。
- **P6AN-09 ROI** — 投入产出（Campaign/Agent/渠道），ROI_COST_PER_*_CENTS 未配则 ROI=None（默认全 0，设计正确）。
- 分层：**纯 assemble 数学层（除零/空域安全，可无库单测）+ collect_raw SQL 聚合层（只读聚合 Phase 1-5 源表，零新表零迁移，集合式 GROUP BY 无 N+1）**，两关注点解耦，对拍可独立跑 live PG。

### 前端（Vue 3 + TypeScript + Pinia + Vite）

- **P6AN-10** — Analytics 路由 + Dashboard 布局 + Pinia store（dashboard/funnel/metrics）+ 核心指标卡 + 时序图 + Agent 排行表。
- **P6AN-11** — 获客漏斗 + 渠道对比 + Lead 转化 + 私域转化 + 时间趋势图。
- **P6AN-12** — Agent 绩效详情/对比 + Experiment 列表/创建/结果/历史。
- 7 个 analytics 页面经 P6AN-15 headless-Chrome CDP 真渲染验收：0 红横幅、0 agent-422、KPI 数值与 p6an15_e2e 种子逐项吻合（32 新会话 / 9 窗口内消息 / 4 agents·3 active / funnel 4 stages）。

---

## 4. 技术债务分级清单（P0/P1/P2/P3）

### P0 — 无遗留

### P1 — 全部已修，无遗留

| # | 问题 | 来源 | 处置 |
|---|------|------|------|
| P1-1 | `/api/v1/analytics/*` 全表面（5 router、35 端点）未认证 + 无租户隔离（读=跨租户 BI 外泄；CRUD=account_id 自由字段可写任意账户） | P6AN-16 架构审查 | **已修复 t_3e806a29**（P6AN-16 [P1]）：复用 ADR-011 get_current_principal + require_analytics_read/write 双 guard + 读按 account 主体作用域 + CRUD 强制归属 + 缓存键含租户。回归 246 + 新增 54 auth 用例全绿。 |

### P2 — 分级跟进（本总结建卡 4 张；P2-4 已随 P1 卡修复；DEF-3 在途）

| # | 问题 | 来源 | 处置 |
|---|------|------|------|
| P2-1 | "成交/converted" 三种口径不一致（P6AN-02/05=Lead.status=='converted'；P6AN-07=lifecycle_stage_code；P6AN-06/09=DealItem.won）→ 用户跨端点对比 conversion_rate 得不同数字 | P6AN-16 §4.3 | **建跟进卡**（backend）：指定单一 SoT（建议 lifecycle_stage_code/成交 为主口径、DealItem.won 仅金额），或每端点回显 caliber 字段 + docs 说明差异。 |
| P2-2 | analytics 表面分裂两套挂载约定（P6AN-01/03/04/05/08 追加共享 `routers/analytics.py` = 并发编辑热点；P6AN-02/06/07/09 各自独立 router + BARE 挂载）→ 边界不统一 | P6AN-16 §2.2 | **建跟进卡**（backend）：冻结共享文件，将 03/04/05/08 计算端点逐步拆入各自 router，与 02/06/07/09 对齐。 |
| P2-3 | naive/timestamptz 混合 DDL（lead/customer 为 naive timestamp，conversation/message/agent 为 timestamptz；每服务各自 per-table `_naive_utc` 剥离，反复 bug 类，P6AN-02 曾抓 3 个真实 bug） | P6AN-16 §4.2 | **建跟进卡**（backend）：建归一迁移将 Phase 1-5 源表时间列统一到 aware-UTC timestamptz，或至少在 DB-DSN/ADR 记录约定。 |
| P2-4 | CORS 通配 `allow_origins=["*"] + allow_credentials=True`（反模式，放大未认证外泄面） | P6AN-16 §5.2 | **已修复**（同卡 t_3e806a29）：收敛为 env 驱动白名单（`CORS_ORIGINS`，默认本地 Vite；credentials 仅在非通配白名单下允许）。见 `app/config.py::cors_origins`。 |
| P2-5 | 生产库漂移：prod `ai_agent_platform` 为 legacy fork，stamped 027，缺 028/029 analytics 表 + Phase-5 列（deal_item status/account_id/currency/lead_id、follow_up_task.account_id）→ analytics 端点在生产实例 500（canonical 测试库通过） | P6AN-16 §5.3 | **建跟进卡**（backend）：生产 `alembic upgrade` 至 028/029 或 schema align，否则该 Phase 在生产不可用。 |
| DEF-3 | P6AN-05 leads/conversion aware-UTC 时间边界 → 500（naive-UTC 有 workaround 不阻断） | P6AN-15 §3 | **在途** t_dc92c614（backend，P2，建议 Phase 7 前清掉）。 |

### P3 — 记录归档（非阻塞，规模化/多实例时处理）

| # | 问题 | 来源 | 处置 |
|---|------|------|------|
| P3-1 | by-agent 双归属模型并存（message 量用 ChannelMessage.agent_id；conversation 作用域走 agent_customer_binding） | P6AN-16 §6 | 归档，后续统一。 |
| P3-2 | experiment results/summary 的 `_all_results_unpaged` 将全部快照载入 Python 取 latest/(variant,metric)（O(N) 内存） | P6AN-16 §6 | 归档，规模化后改 SQL 侧窗口。 |
| P3-3 | ROI 成本默认全 0 → ROI=None（未配成本基准，设计正确） | P6AN-16 §6 | 归档，需运维配 ROI_COST_PER_*_CENTS 后才出数。 |
| DEF-8 | test_analytics_funnel_p6an03 test_route_registered 失配（FastAPI 0.141 _IncludedRouter 嵌套致裸 app.routes 不展平；线上 funnel 200 正常，纯测试器写法） | P6AN-15 §3 | **在途** t_645352c1（backend，P3）。 |

---

## 5. 测试与审查报告

### 5.1 E2E QA — P6AN-15（t_31ca8734，verdict **PASS**）

- **基线**：在 P6AN-13 QA 基线 3b40e6c（P6AN-12 tip + P6AN-11 merge）之上 fast-forward merge 5 张修复卡 DEF-1/2/5/6/7（7fdd20f/f34c182/3572032/c41ea90/eb9aa3d）。
- **API 层**：8 大族全链路，主流程 53/56 + 12/12 recheck + DEF-5/6/7 回归全绿；3 条"套套 FAIL"经独立 recheck 证为 P6AN-13 测试套入参/契约写法瑕疵（逆窗口裸 start/end、conversion 当标量），非产品缺陷。
- **UI 层**：7 页 headless-Chrome CDP 真渲染，0 红横幅/0 agent-422，DB→API→UI KPI 与 p6an15_e2e 种子逐项吻合。
- **回归门禁**：pytest analytics 家族 272/275；2 条 = P6AN-13/14 预存共享 test-DB 漂移（非本卡）；1 条 test_route_registered 预存测试器瑕疵（干净 P6AN-14 worktree 同样 FAIL）。
- **放行条件**：P1 DEF-1 + P2 DEF-2 已修并复测通过 → 满足，主链路放行。非阻断遗留：DEF-3(P2, 有 naive workaround)、DEF-8(P3)。
- 报告：`I:\hermes\kanban\attachments\t_31ca8734\P6AN-15-analytics-E2E-acceptance-report.md`（含 ui_flow_report.json / api_flow_results.json / recheck_results.json / regression_out.txt）。

### 5.2 架构审查 — P6AN-16（t_67f18134，verdict **CHANGES_REQUIRED**）

- 4 维度核验（schema / API 边界命名 / 缓存性能 / 模块分层与 Phase 1-5 耦合），全部基于后端源码而非仅信 handoff。
- 良好：schema 5 表一致、迁移 028 幂等软引用解耦；API 统一 /api/v1/analytics 前缀 + 统一错误语义（除零/空域→200 不 500）；仅 overview 缓存但各端点均 <500ms；纯数学层 + SQL 层解耦、只读聚合零反向改写、无 N+1。
- 缺口：**安全/多租户**（P1-1 未认证无租户隔离）+ **指标口径一致性**（P2-1 三种口径）。已建 P1 修复卡（t_3e806a29，已 done）。
- 报告：`backend/docs/P6AN-16-analytics-architecture-review.md`。

---

## 6. 架构决策变更

- **新增 ADR-018（见 DECISIONS.md）**：`/api/v1/analytics/*` 全表面认证 + 租户隔离——复用 ADR-011 get_current_principal（HS256 Bearer），新增 `app/security/analytics_access.py` 的 `require_analytics_read`/`require_analytics_write` 双 guard；读端点按调用方 token account_id 作用域（仅本账户可见，经 agent_persona_binding→agent_customer_binding 的 customer/agent 维度 + account-owned 源表）；`account_id=NULL` 的 platform-wide 定义仅 `PLATFORM_WIDE_ROLES`(admin/platform_admin) 可见，未绑定 operator 做 platform-wide 读 → 403（P1 跨租户读路径在 guard 层即关闭）；CRUD create 强制归属调用方账户（客户端 account_id 永不信任），跨租户写 → 403（AccountOwnershipError 全局 handler），跨租户读 → 404（不泄漏账户存在性）；dashboard overview 缓存键纳入租户（account_id）跨租户绝不别名。
- **ADR-015（CORS 通配+credentials）状态更新为已实现**：其平台级安全跟进已由 t_3e806a29 顺手收敛为 env 白名单（`CORS_ORIGINS`），非通配下才允许 credentials。

---

## 7. 后续任务（本总结创建 4 张 P2 跟进卡）

1. **P6AN-17-P2-1 成交口径统一**（backend，P2）→ 单一 SoT 或 caliber 回显。
2. **P6AN-17-P2-2 analytics 挂载约定收敛**（backend，P2）→ 冻结共享文件 + 拆分 03/04/05/08 计算端点。
3. **P6AN-17-P2-3 源表时间列归一 aware-UTC**（backend，P2）→ 归一迁移消除 naive/tz bug 类。
4. **P6AN-17-P2-5 生产库 alembic 至 028/029**（backend，P2）→ 解锁生产 analytics。

**在途**：t_dc92c614（DEF-3 P2）、t_645352c1（DEF-8 P3）完成后本 Phase 技术债闭环。

> 不在本阶段范围：Phase 7（AdsPower / LocalChromium Provider、插件市场、多租户 SaaS、移动端）；新技术债实现（本卡只建卡不实现）。

---

## 8. 备注

- **文档一致性**：`docs/CURRENT_FOCUS.md` 仍停留在 "Phase 2 当前焦点 / 暂时禁止 Analytics"，与本板 Phase 6 推进不符（同 PHASE-3-SUMMARY §8 记录的过期现象）。本卡已将其更新为 Phase 6 收口 + Phase 7 待开。ROADMAP.md / PROJECT.md 的 Phase 6 状态段已同步。
- 验证环境：Windows 10, Python 3.11.16, FastAPI backend, pytest；E2E 用隔离 PG（create_all 61 表）+ headless-Chrome CDP。
