# P6AN-16 · Analytics 架构审查报告（Phase 6 / Analytics & Optimization）

- 审查人：code-architecture-reviewer
- 任务：t_67f18134
- 日期：2026-09-15
- 范围：Analytics schema 设计、API 边界与命名、缓存与性能策略、模块分层与 Phase 1-5 耦合
- 裁定：**CHANGES_REQUIRED**（无 P0；1 项 P1 + 5 项 P2 需修复/跟进后方可进入生产/多租户部署）

> 说明：本审查基于对后端源码的实际核验（H:/AI-Agent-Platform/backend），而非仅信任上游
> handoff。上游 P6AN-01~09 的"全绿测试"结论被采纳为输入，但其架构风险独立复评如下。

---

## 0. 裁定摘要

| 维度 | 结论 |
|---|---|
| Schema 设计 | 良好 — 5 表一致、幂等迁移 028、软引用解耦 |
| API 边界 / 命名 | 良好 — 统一 /api/v1/analytics 前缀；但跨两个挂载约定分裂 |
| 缓存 / 性能 | 可接受 — 仅 overview 有缓存，其余端点未缓存但达 P95 目标 |
| 模块分层 / 耦合 | 良好 — 纯数学层 + SQL 层解耦，只读聚合 Phase 1-5 源表，无反向改写已验收模块 |
| 安全 / 多租户 | **缺口** — analytics 表面未认证 + 无租户隔离（P1-1） |
| 指标口径一致性 | **缺口** — "成交/converted"三种口径（P2-1） |

整体实现质量高：两层解耦（纯 assemble 数学 + collect_raw SQL 对拍）、除零/空域安全、
empty-scope 返回 200 而非 500、迁移幂等可重跑、无 N+1。**但存在 1 个架构/安全级 P1**
（认证与租户隔离缺失）必须处理，另 5 个 P2 建议跟进。无 P0（无使功能失效或数据破坏项）。

---

## 1. Schema 设计审查

### 1.1 良好
- 5 实体（dashboard_widget / funnel_step / metric_definition / experiment /
  experiment_result）遵循资源层约定（channel_config / workflow_runtime）：
  UUID PK、aware-UTC created_at/updated_at、is_deleted 软删、JSONB 演进配置、
  部分（live-row）唯一索引 `postgresql_where is_deleted=false`。
- 迁移 028 幂等：所有 CREATE/index 走 live `to_regclass` / `pg_indexes` 守卫，
  可在 fresh 与 legacy（stamped）库上重跑而不静默跳建索引。验证 028.down=027、
  029.down=028，单一线性链（非多头）。
- 跨域引用用软引用（metric_code / funnel_code 为 TEXT，非 FK）：schema 不阻塞
  在引用域实体存在前注册 analytics 定义。正确取舍。
- 唯一硬 FK：experiment_result.experiment_id → experiment.id（CASCADE），两表同一
  迁移原子创建，fresh/legacy 皆安全。

### 1.2 建议（无 P 级，记录在案）
- metric_definition.formula 是"JSONB spec，禁止裸 SQL"（P6AN-01 无 free-report
  引擎，符合范围）。后续若做 SQL 引擎须单独立卡并补沙箱/只读保护。

---

## 2. API 边界与命名一致性

### 2.1 良好
- 全部端点统一挂在 /api/v1/analytics 前缀下：/widgets /funnel-steps /metrics
  /experiments /experiment-results /funnel /conversations /leads/conversion，
  以及自前缀 router（BARE 挂载）/dashboard/overview、/agents/performance、
  /private-domain/conversion、/roi。命名一致，动词/资源符合 REST。
- 错误语义统一：404 实体不存在、409 唯一性/流量分配冲突、422 非法参数、
  400 窗口反序。除零/空域 → 200 + 0/None，绝不 500。

### 2.2 发现 P2-2：analytics 表面分裂为两套挂载约定（架构漂移）
- P6AN-01/03/04/05/08 的 CRUD + 计算端点全部追加进共享文件
  `app/routers/analytics.py`（及 `app/schemas/analytics.py`）——该文件被多张卡并发
  追加，是**已确认的编辑热点**（P6AN-03/05/08 均标注 hotspot）。
- P6AN-02/06/07/09 为规避热点，各自新建独立 router 文件（dashboard.py /
  agent_performance.py / private_domain_conversion.py / roi_analysis.py）+ BARE 挂载。
- 结果：同一个 analytics API 表面同时存在于"共享大文件"与"逐波独立文件"两种模式，
  边界不统一，共享文件将继续成为并发冲突源。
- **处置建议**：冻结 `routers/analytics.py` 的追加；把 P6AN-03/04/05/08 的计算端点
  逐步拆入各自 router 模块（与 02/06/07/09 对齐），或在 orchestrator 层串行化写入。

---

## 3. 缓存与性能策略

### 3.1 良好
- `dashboard_cache.py`：Redis 可用则异步原生（lazy 解析，无 import 期硬依赖），
  缺失/故障一次性降级 in-memory TTL；缓存是性能优化而非正确性要求——任何缓存故障
  降级到重算并记 1 条 warning，绝不打断 API。键 = sha1(normalized params)，
  不同过滤组合互不别名；`cached` 标志由**服务端**在交付时打上（命中不谎报 live）。
  DASHBOARD_CACHE_URL/REDIS_URL 解析、_redact_url 掩码凭据。设计严谨。
- 性能实测（上游 対撞）：overview 冷 P95=51.9ms@10k（warm 命中 0.2ms/0 SQL）；
  conversations P95=278ms@10k。均 < 500ms 目标，**未加缓存的端点也达标**。

### 3.2 发现 P3（记录，非阻塞）
- 仅 overview 有响应缓存；funnel/conversations/leads/agent/private-domain/roi 无缓存。
  当前达标可接受；若数据量上探 10^5-10^6 再按需加缓存层。
- Redis 缺失时 in-memory fallback 是**进程级**（非跨进程共享、无失效广播）；多实例
  部署下各进程各自重算。多实例上线前需评估（或配置 REDIS_URL）。

---

## 4. 模块分层与 Phase 1-5 耦合

### 4.1 良好（无反向修改已验收模块）
- 全部计算服务（funnel/dashboard/lead_conv/private_domain/roi/agent_perf）是**只读
  聚合**，骑 Phase 1-5 源表（lead/conversation/message/deal_item/
  nurture_step_execution/follow_up_task/agent_customer_binding/customer），**零新表、
  零迁移**（仅 P6AN-01 建 5 张 analytics 定义表）。
- 分层干净：`collect_raw`（SQL/对拍层，每指标一个聚焦聚合）+ 纯 `assemble`（数学/
  舍入/除零层，可无库单测）。两关注点解耦，对拍可独立跑 live PG。
- 集合式 GROUP BY 聚合，无 10k IN-list、无 N+1（leaderboard 固定 ≈7 条分组查询）。

### 4.2 发现 P2-3：naive/timestamptz 混合 DDL（反复 bug 类）
- 源表时间列分两族：`lead`/`customer` 为 naive `timestamp`，`conversation`/
  `message`/`agent` 为 `timestamptz`。每个服务各自用 per-table `_naive_utc` 剥离处理。
  P6AN-02 实测曾因此抓到 3 个真实 bug（naive/timestamptz 族绑定、非法
  func.filter、URL +00:00 解码变空格 400）。
- **处置建议**：建一张归一迁移，将 Phase 1-5 源表时间列统一到 timestamptz（aware
  UTC），消除整类时间比较 bug；或至少在 DB-DSN.md/ADR 记录该约定供后续模块遵循。

### 4.3 发现 P2-1：指标口径不一致（"成交/converted"三种定义）
- P6AN-02 dashboard & P6AN-05 lead-conversion：**Lead.status == 'converted'**（CRM 线索
  状态机终态）。
- P6AN-07 agent-performance：**Lead.lifecycle_stage_code in {成交}**（生命周期阶段码）。
- P6AN-06/09：成交金额走 **DealItem.status == 'won'**（成交单）。
- 即"已成交/转化率"在不同端点用了 3 个不同口径。用户跨端点对比 conversion_rate 会
  得到不一致数字。P6AN-02 handoff 已将其标为 P2 一致性问题。
- **处置建议**：指定单一 SoT（建议 lifecycle_stage_code/成交 为主口径，DealItem.won
  仅用于金额），或为每个端点在响应里回显 caliber 字段 + docs 显式说明三者差异。
  属数据可信度问题，建议 P2 处理（当前各口径已有各自 docs，可先补对齐说明）。

---

## 5. 安全 / 多租户（最重发现）

### 5.1 P1-1：analytics 表面未认证 + 无租户隔离
**证据（源码核验）**：
- `main.py` 构造 FastAPI 时未设全局 `dependencies`；仅 `auth.py` 与
  `private_domain.py` 通过 `require_private_domain`/jwt 接入认证。
- 5 个 analytics router（analytics.py / dashboard.py / agent_performance.py /
  private_domain_conversion.py / roi_analysis.py）所有端点依赖**只有** `Depends(get_db)`，
  无任何 Bearer/主体校验。
- P0 安全卡（t_f1f591ab）将 24 条路由纳入 Bearer，但那是"私域 + integration"范围，
  **analytics 表面未覆盖**。

**影响**：
- 读：任意调用方读取**全平台/跨租户**业务 BI（转化率、ROI、成交额 cents、agent KPI、
  线索漏斗）。跨租户数据外泄。
- 写：analytics 定义 CRUD（POST/PUT/DELETE /analytics/widgets|funnel-steps|metrics|
  experiments...）account_id 是**自由 body 字段、无 ownership 校验** → 任意调用方可
  创建/改/删**任意账户**的 analytics 定义。跨租户写。

**裁定**：**P1（架构 + 安全）**。平台当前可能仍是单租户/内部阶段，故不判 P0；但进入
多租户/生产前必须：(a) 给 /api/v1/analytics/* 全量加认证（复用 require_private_domain
或统一 get_current_principal）；(b) 按调用方 account 主体做租户作用域（读 + CRUD）；
(c) 处理 account_id=NULL 的 platform-wide 定义的访问权限。

### 5.2 P2-4：CORS 通配 + credentials
- `main.py`：`CORSMiddleware(allow_origins=["*"], allow_credentials=True)`。通配 origin
  与 credentials=True 组合是反模式（浏览器拒绝 credentialed 跨域 + `*`）；在 analytics
  未认证的前提下放大外泄面。**处置**：收敛到白名单 origin。

### 5.3 P2-5：生产库漂移（部署缺口）
- P6AN-06/09 handoff 记录：生产 `ai_agent_platform` 为 legacy fork，stamped 027，
  缺 028 analytics 表 + Phase-5 列（deal_item status/account_id/currency/lead_id、
  follow_up_task.account_id）→ analytics 端点在该生产实例 **500**。canonical 测试库
  通过。
- **处置**：生产需 `alembic upgrade` 至 028/029（或对 schema align）后方可用 analytics；
  立卡跟踪，否则该 Phase 在生产不可用。

---

## 6. P3（记录在案，非阻塞）
- P3-1：by-agent 的 message 量用 `ChannelMessage.agent_id` 作用域，而 conversation 作用域
  走 `agent_customer_binding`——两种 agent 归属模型并存，已文档化，建议后续统一。
- P3-2：experiment results/summary 的 `_all_results_unpaged` 将全部快照载入 Python 取
  latest/(variant,metric)——O(N) 内存。curated 规模无碍，规模化后需 SQL 侧窗口。
- P3-3：ROI 成本价默认全 0 → ROI=None（未配成本基准，非 0%）——按设计正确；需运维
  配 ROI_COST_PER_*_CENTS 后才出数。记录在案。

---

## 7. 上游"全绿"结论的复核态度
上游测试全绿（unit/对拍/HTTP 200/422）作为**功能正确性**证据被采纳。本审查**不因其
"大部分通过"而放行**：已独立发现认证/租户（P1-1）与口径（P2-1）这类测试未覆盖的
架构/安全缺口。故裁定 CHANGES_REQUIRED。

---

## 8. 处置清单（分级）

| 级别 | 项 | 建议处置 | 建议卡 |
|---|---|---|---|
| P1 | P1-1 analytics 未认证 + 无租户隔离 | 全量加认证 + 按 account 主体作用域读/写 | 建卡（→ orchestrator 路由实现方） |
| P2 | P2-1 成交口径三种不一致 | 指定单一 SoT 或回显 caliber | 建卡 |
| P2 | P2-2 analytics.py 热点 / 双挂载约定 | 冻结共享文件，拆分逐波 router | 建卡 |
| P2 | P2-3 naive/timestamptz 混合 DDL | 归一迁移或 ADR 记录 | 建卡 |
| P2 | P2-4 CORS 通配 + credentials | 收敛白名单 | 建卡 |
| P2 | P2-5 生产库漂移（缺 028/029） | 生产 alembic upgrade / schema align | 建卡 |
| P3 | P3-1/2/3 | 记录，规模化/多实例时处理 | 归档 |

## 9. 处置记录（2026-09-15，P1-1 + P2-4 落地）

**P1-1（已修复，卡 t_3e806a29 / P6AN-16 [P1]）**：`/api/v1/analytics/*` 全表面
（analytics / dashboard / agent_performance / private_domain_conversion /
roi_analysis 共 5 router、35 端点）已接入认证 + 租户隔离：

- **认证**：全部端点复用 ADR-011 的 `get_current_principal`（HS256 Bearer），
  新增 `app/security/analytics_access.py` 的两个 guard —— `require_analytics_read`
  （读端点最低 read 权）与 `require_analytics_write`（CRUD 最低 write 权）。
  未携带 / 无效 / 过期 token → 401；角色低于 analytics 底线 → 403。
- **租户作用域**：读（overview/funnel/conversations/leads/agents/roi/
  private-domain）按调用方 token 的 `account_id` 作用域——只返回本账户可见数据
  （经 `agent_persona_binding → agent_customer_binding` 的 customer/agent 维度 +
  account-owned 源表）。`account_id=NULL` 的 platform-wide 定义仅显式授权角色
  （`PLATFORM_WIDE_ROLES` = admin/platform_admin）可见；未绑定的 operator 做
  platform-wide 读 → 403（P1 跨租户读路径在 guard 层即关闭，非仅 service 层）。
- **CRUD 归属**：create 强制归属调用方账户（客户端 `account_id` 永不信任）；
  跨租户写抛 `AccountOwnershipError` → main.py 全局 403 handler；跨租户读按
  定义可见性降为 404（不泄漏账户存在性）。
- **缓存**：dashboard overview 的响应缓存键纳入租户（`account_id`），跨租户缓存
  绝不别名。
- 回归：P6AN-01/02/03/05/06/07/08/09 全套 246 通过 + 新增
  `tests/test_p6an16_analytics_auth.py` 54 用例（401 未认证 / 403 越权 / 租户作用域 /
  未认证调用被拒）。真 app 冒烟：11 个无参读端点全部 401（无 token）。

**P2-4（已顺手修复，同卡）**：`main.py` CORS 由 `allow_origins=["*"] +
allow_credentials=True` 收敛为 env 驱动的白名单（`CORS_ORIGINS`，默认本地 Vite
前端；`cors_allow_credentials` 仅在非通配白名单下允许 credentials）。详见
`app/config.py::cors_origins` 与 `main.py`。

**遗留（本卡范围外，见 §8 其余行）**：P2-1 成交口径、P2-2 双挂载热点、
P2-3 时间列 DDL、P2-5 生产库漂移仍待独立建卡处理；P3 记录归档。
