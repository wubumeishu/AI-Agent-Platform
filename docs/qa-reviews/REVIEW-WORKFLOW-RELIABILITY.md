# Workflow 可靠性审查报告 (t_069e5699 / t_wf_016)

Reviewer: code-architecture-reviewer
Scope: 调度器稳定性 / 任务队列可靠性 / 执行器容错 / 日志完整性 / 异常恢复 / 性能瓶颈
Out of scope: 前端性能、数据库调优、安全渗透（已由专门任务负责）
Base: H:/AI-Agent-Platform/backend（main checkout，t_c94bba06 修复后代码）
前置: 架构审查 t_c81d72fe 裁定 CHANGES_REQUIRED；修复卡 t_c94bba06 已落地 P0/P1 + 全套回归。
Verdict: **CHANGES_REQUIRED**（2×P1 可靠性缺口 + 4×P2；上游 P0/P1 修复本身全部核实通过）

---

## 修复状态（t_0d7a076a / backend-engineer，2026-09-15）

本报告的 2×P1 + 4×P2 缺口已由 backend-engineer 卡 t_0d7a076a 修复并回写，
复审卡 t_a3f82e43 待重跑。逐项销项（✅=已落地+实测，🟡=部分/文档记录）：

| 项 | 修复 | 证据 |
|---|---|---|
| P1-R1 无消费者+缺默认队列→静默丢弃记 success | ① 迁移 027 幂等 seed 默认队列 `workflow-scheduler`（timeout_seconds=600）；② 默认引擎 `require_queue=True`（缺队列 fire 记 failed、schedule 停摆可观测，非静默 success）；③ 可选 in-process consumer（`SCHEDULER_WORKER=1`，fire→claim→execute 闭环，执行真实 workflow action graph） | 027 已在 prod `ai_agent_platform` 应用+幂等重跑通过（head=027）；单测 `test_default_engine_dispatcher_requires_queue` + `test_consumer_poll_once_claims_and_executes`；真实 PG E2E 场景 A（9/9） |
| P1-R2 running 崩溃/卡死无自动恢复 | ① 启动回收 `recover_stale_running`（stale running→pending）；② 周期 `sweep_and_retry`（sweep timeout→重投，30s 独立 loop `task_recovery`）；③ 默认基线：调度任务默认 `max_retries=2`+`timeout_seconds=600`（config 可覆写） | 单测 `test_recover_stale_running_*` / `test_sweep_and_retry_*`；E2E 场景 B（崩溃 running 重投 success）+ C（卡死 running 被 sweep→timeout→重投 success） |
| P2-R4 stalled schedule 跨重启保持停摆 | 引擎 `repair_stalled_schedules`：启动对 enabled 但 next_run_at 缺失的行 repair/recompute+重 arm+告警（仍 invalid 的留给人工） | 单测 `test_engine_repair_stalled_schedules_*`；main.py startup 接线 |
| P2-R5 "no-queue" 软成功 trace 失真 | 缺队列 fire 记 `status="dropped"`+`error_code=E_NO_QUEUE`（非 success）；引擎 `_fire_one` 识别 dispatcher 的 dropped trace 状态 | 单测 `test_engine_noqueue_dropped_records_not_success` + `test_queue_dispatcher_no_queue_soft_noop` |
| P2-R6 单 tick 串行 + 3 次 DB 往返 | **文档记录（低频可接受）**：每 fire 由 3 往返降为 2 commit（删掉 commit 后 re-SELECT）；串行 fire 批 + O(n) disarm 记为已接受低频频瓶，remediation 留待未来 wave | engine.py 模块 docstring "Performance note (P2-R6)"；`_fire_one` 已改 2 commit |
| P2-R7 丢失 terminal commit 的重复 fire | 引擎 `finalize_stale_execution_logs`：启动把 stale running 的 scheduler ExecutionLog 收尾为 timeout/`STALE_RUNNING`（at-least-once 重 fire 可观测、不留孤立 running 日志） | 单测 `test_engine_finalize_stale_running_logs`；main.py startup 接线 |

**回归**：test_scheduler + test_scheduler_consumer + 全部 test_workflow_* = **357 passed**（基线 336 + 21 新增）。
**真实 Postgres E2E**（tests/_e2e_workflow_reliability.py，对 `ai_agent_platform_test`）：9/9 通过 ——
默认 fire 端到端执行、崩溃 running 重投、卡死 running sweep 触发、成功 ExecutionLog 可追溯。
预存在且与本卡无关：test_crm_conversation_integration 的 2 条 crm-lead 路由断言（flat app.routes vs OpenAPI 嵌套），已用 `git stash` 验证无我改动时同样失败（CRM 域，非本卡范围）。

---

## 复审记录（t_a3f82e43 / code-architecture-reviewer，2026-09-15）

本卡为 t_0d7a076a（backend-engineer 修复卡）的复审 gate。以下为独立核实结果（非信任 handoff，按代码路径 + 实际执行验证）：

**裁定：APPROVED** —— 6 项缺口全部真实落地，回归 + E2E 全绿。

### 逐条销项（实测）

| 项 | 核实方式 | 结论 |
|---|---|---|
| P1-R1 seed 默认队列 | 迁移 027 在真实 `ai_agent_platform_test` DB 上幂等验证：BEFORE=1 row (workflow-scheduler, timeout=600)；DDL 重跑后仍 1 row；NULL-timeout baseline 恢复后 DDL 正确回填 600。`get_scheduler_engine().dispatcher.require_queue is True` 在 E2E 中直接断言 | ✅ |
| P1-R1 缺队列不再静默 success | engine.py:407-420 识别 dispatcher 的 `output["status"]=="dropped"` trace → 翻转 `status="dropped"` + `err_code="E_NO_QUEUE"`，`fires_failed+=1`，不 re-arm。单测 `test_engine_noqueue_dropped_records_not_success` 通过 | ✅ |
| P1-R1 可选 in-process consumer 闭环 | consumer.py 的 `SchedulerTaskExecutor` 路由 `origin=="scheduler"` + `workflow_id` 到 `WorkflowConversationBridge.run_scheduled`；E2E 场景 A：fire→enqueue→consumer claim→execute→task success，result 携带 `executor="scheduler-task"` + `scheduler_run.ok=True`（非 Echo）| ✅ |
| P1-R2 启动回收 stale running | main.py:312-330 `recover_stale_running`（gated `WORKFLOW_TASK_CRASH_RECOVERY`，默认 on）；E2E 场景 B：插入 running task→recover 重置 pending→consumer 认领→success | ✅ |
| P1-R2 周期 sweep 驱动 | main.py:338-352 `TaskRecoveryLoop.start(interval_seconds=30)`；E2E 场景 C：卡死 running task→sweep 触发 timeout→retry_count=1→success | ✅ |
| P1-R2 默认 timeout/retry 基线 | config.py：`scheduler_default_max_retries()=2` + `scheduler_default_timeout_seconds()=600`（env 可覆写）；dispatcher `_baseline_defaults` 在 enqueue 时 stamp 到 TaskCreate | ✅ |
| P2-R4 stalled schedule 跨重启 repair | engine.py:225-283 `repair_stalled_schedules`（recompute+re-arm+warn）；main.py:278-287 startup 接线 | ✅ |
| P2-R5 no-queue soft-success trace 失真 | 见上 P1-R1 第 2 行（dropped status + E_NO_QUEUE） | ✅ |
| P2-R6 单 tick 串行 + 3 DB 往返 | 第 3 次 SELECT 已删除（engine.py docstring 记录，每 fire 现为 2 commits）；串行 fire 批 + O(n) disarm 记为 V1 已接受低频上限（remediation 留待未来 wave）。**文档记录，非阻断** | ✅ |
| P2-R7 丢失 terminal commit 重复 fire | engine.py:285-340 `finalize_stale_execution_logs`（closing stale running log→timeout/STALE_RUNNING）；main.py:292-301 startup 接线 | ✅ |

### 回归 + E2E 实测

- **回归 357/357 全绿**（组合运行 test_scheduler + test_scheduler_consumer + 全部 test_workflow_*：`357 passed, 0 failed`，与父卡 t_0d7a076a 声称的 357 完全一致）
- 注：首跑时 test_workflow_task(4) 和 test_workflow_execution_log(3) 有 7 条 import 失败，根因是 **app/security/__init__.py 尚未创建**（并发 P5MSG/ADR-011 安全任务正在写入中）——非本卡代码问题。重跑时 __init__.py 已落盘，全部通过。
- **真实 Postgres E2E 9/9**（`tests/_e2e_workflow_reliability.py`，对 `ai_agent_platform_test`）—— 默认 fire 端到端、崩溃 running 重投、卡死 running sweep 触发、成功 ExecutionLog 可追溯。两次独立跑均 9/9。

### 架构 / 安全 / 可维护性

- **无双执行风险**：in-process consumer 默认 OFF（`SCHEDULER_WORKER=0`）；外部 worker 部署可避免双执行，文档记录在 config.py
- **无硬编码平台逻辑**：executor 可插拔（`SchedulerTaskExecutor` 是默认路由；deployment 可替换为自定义 executor）
- **错误处理**：consumer poll 循环和 recovery loop 均 catch-all + 下一 tick 重试，不会 kill 后台 task
- **无 fake 实现**：E2E 场景 A 验证了真实 action graph 执行（`scheduler_run.ok=True`），非 Echo 空壳
- **测试覆盖**：21 新增单测（consumer/recovery-loop/bridge.scheduled）+ E2E 三场景真实 DB
- **迁移 027 幂等**：在真实 DB 上验证了 re-run 不增加 row，NULL-timeout 恢复后 DDL 正确回填基线

### 出 scope 记录

`app/security/` namespace package 的 `__init__.py`（re-export shim）由并发 P5MSG-06/ADR-011 安全任务正在写入中（本卡运行时段 00:19-00:46 间出现）。在 `__init__.py` 落盘前首跑时有 7 条 import 失败（`from app.security import require_trusted_producer` → `app.security` 是 PEP-420 namespace package 无 re-export），这是瞬态竞争非本卡缺陷。`__init__.py` 落盘后全部通过。

### 结论

P1-R1 + P1-R2 + P2-R4..R7 全部真实落地、回归 + 真实 PG E2E 全绿。无安全/架构/可维护性新风险。**APPROVED，放行 Phase 6 gate（t_e94a362e）。**

---

## 结论概览

上游架构审查提出的 P0/P1 修复**全部实证通过**（下节"已核实项"）。但本次可靠性审查针对
**队列消费与异常恢复**两条上游未覆盖的链路做冷读 + 实际执行验证，发现 2 个 P1 级可靠性缺口：

- 调度器修复后确实把每次 fire **入队**为 WorkflowTask（消除了 P1-2 的"记录型空壳"），
  但**入队的任务在系统内没有任何消费者**（无后台 worker/claim 循环，默认队列既未 seed 也未自动创建），
  默认部署下定时工作流每次 fire 都以 `{"enqueued": false}` **软无操作**并记录为 **success** —— 工作被静默丢弃。
- **崩溃/卡死的 running 任务无自动恢复**：claim 后 worker 崩溃，任务永久停留 running；
  恢复完全依赖**人工** `POST /sweep-timeouts`，且默认 `timeout=None`（不扫）+ `max_retries=0`（不重投），
  默认组合下是不可恢复孤儿。

对照本卡验收标准逐条：
- [x] 调度器设计稳定可靠 —— 纯函数 cron 计算 / 最小堆+tick / 可插拔 dispatcher / autostart 均健全；P0-1 已修
- [ ] 任务队列无数据丢失风险 —— **R-1：定时工作负载在默认部署下被静默丢弃且记为 success**
- [ ] 异常恢复机制完备 —— **R-2：running 任务崩溃/卡死无自动恢复，默认不可重试**
- [~] 日志记录完整可追溯 —— 基本健全，但"no-queue 软成功"记为 success 使 trace 失真（P2-2）；ExecutionLog 无 FK（ADR-013，已记录 tech-debt）
- [x] 审查报告已提交（本文档）

---

## 一、已核实项（上游 P0/P1/P2 修复全部落地 —— 实证通过）

| 项 | 文件/证据 | 结果 |
|---|---|---|
| P0-1 秒级 cron 相邻间隔 | `cron_parser.py:198-209` 按 (h,m,s) 升序扫描；实测 `*/10 * * * * *` = 6×10s、`*/7`=7s、`*/5`(5字段)=300s、`0,20,40`=20s | ✅ 修复，精确到秒 |
| P1-1 /workflows 单一 API 面 | OpenAPI 345 ops/239 paths，**0 重复 operationId**，`/api/v1/workflows` 唯一 | ✅ 收敛 |
| P1-2 真实 dispatcher + autostart | `dispatcher.py` QueueDispatcher；`main.py:256-273` startup autostart+load_schedules；`get_scheduler_engine` 默认 QueueDispatcher | ✅ 接线 |
| P1-3 DB/内存双源 | `service.py:223-254` create/update/delete 后 `_sync_engine_after_create_or_update`/`_disarm_engine` 同步堆 | ✅ |
| P1-5 迁移死代码 | `015` 已清死 DROP DOMAIN | ✅ |
| P2-1 aware-UTC | `workflow_runtime._now` = now(utc) | ✅ |
| P2-2 sweep 批量 in_() | `workflow_task.py:535-543` 单条 in_() 取多队超时 | ✅ |
| P2-4 死代码 | `_NullSessionCtx` 已删，改 `reset_scheduler_engine` | ✅ |
| 回归 | `test_scheduler.py + test_workflow_*.py` = **336 passed**；`app.main` import + OpenAPI build | ✅ |

上述与 t_c94bba06 汇报一致，本审查独立复跑全绿。

---

## 二、可靠性缺口（本卡新增发现）

### P1-R1  定时工作负载无消费者 + 默认队列缺失 → 静默丢弃且记为 success（数据丢失风险）

链路：`SchedulerEngine._fire_one` → `QueueDispatcher.dispatch`（`dispatcher.py:69-125`）→
`QueueWorkerEngine.enqueue`（`workflow_task.py:179`）入队一条 `WorkflowTask`。

但入队之后**系统内无任何环节消费它**：
1. **无消费者**。`main.py` 中既没有 `claim_next` 的后台循环，也没有任何 Worker 引擎进程。
   `routers/workflow_task.py` 只暴露 `POST /queues/{id}/claim`、`/{id}/complete|fail` 等**拉取式**端点，
   需外部 poller 驱动。仓内不存在这样的 poller。
2. **默认队列未 seed 也未自动创建**。`scheduler_default_queue_name()` 默认 `workflow-scheduler`
   （`config.py:106`），但 `alembic/versions/*.py` 无任何 seed 该队列的迁移（仅 prompt-template seed），
   `QueueDispatcher` 也不 `auto-create` 队列（`dispatcher.py` 无 `WorkflowQueue(...)` 建队）。
3. **缺队列时是软无操作且记 success**。`QueueDispatcher(require_queue=False)` 为默认
   （`dispatcher.py:56`）；队列解析不到时 `dispatch` 返回 `{"enqueued": False, "reason": "no-queue"}`
   **而不抛错**（`dispatcher.py:96-101`），`_fire_one` 因此把该 fire 标记 `status="success"`
   （`engine.py:265-267`）并照常 re-arm。

净效果：**默认安装下，任何定时(cron/interval)工作流每次 fire 都不实际执行任何动作，
却写一条 `ExecutionLog status=success`**。这正好是 P1-2"记录型空壳"的残留变体——
入队那半修复了，消费 + seed 那半没落地，且软成功语义把丢弃藏了起来。
直接命中本卡验收"任务队列无数据丢失风险"。

修复建议（择一/组合，需 backend 裁决目标形态）：
1. **seed 默认队列**：新增迁移幂等建 `workflow-scheduler` 队列行（对齐 020/026 先例），使默认部署可端到端；
2. **默认硬失败**：把 `get_scheduler_engine` 默认 `QueueDispatcher(require_queue=True)`，
   缺队列时 fire 记 `failed`（schedule 停摆、可观测）而非静默 success；
3. **提供最小消费者**：为调度器自身队列提供一个可选 in-process consumer
   （startup 可开、`SCHEDULER_WORKER` 门控），闭环 fire→claim→execute；
4. 三者可叠加，但**至少要让"缺队列"不再是静默 success**。

### P1-R2  running 任务崩溃/卡死无自动恢复（异常恢复不完备）

`claim_next` 原子抢占后任务转 `running`（`workflow_task.py:276-336`）。若 claim 的 worker 进程
中途崩溃/卡死，任务**永久停留 running**：

- **无自动重夺**：没有任何"启动时回收 stale running / worker 死亡即重投"的机制。
- **恢复全靠人工 sweep**：`sweep_timeouts`（`workflow_task.py:503`）是唯一恢复入口，
  但 `main.py` 无 cron/定时器驱动它（仅 `POST /workflow-tasks/sweep-timeouts`）。
- **默认不满足 sweep 前置**：sweep 只对"有效超时已到期"的任务生效，`timeout = task.timeout_seconds
  or queue.timeout_seconds`（`workflow_task.py:550-554`），两者默认均为 NULL → `if timeout is None: continue`
  （`:555`）→ 默认任务**永远不会被扫为 timeout**。
- **默认不重试**：`TaskCreate.max_retries` 默认 0（`schemas/workflow_task.py:36`），
  `retry_task` 仅在 `retry_count < max_retries` 时重投（`workflow_task.py:481`）→ 即便被扫成 timeout 也终态。

净效果：默认配置下，一个崩溃/卡死的 running 任务是**不可恢复孤儿**（无自动重投、无自动 sweep、
默认无超时、默认不重试）。直接命中本卡验收"异常恢复机制完备"。

修复建议：
1. **启动回收**：startup 时把 `status=running` 且（worker 已死 或 claimed_at 超过 staleness 阈值）
   的任务重新置 pending（或 timeout），消除崩溃孤儿；
2. **自动 sweep 驱动**：把 `sweep_timeouts` 接入周期定时器（复用 SchedulerEngine tick 或独立 loop）；
3. **默认超时/重试基线**：为队列或任务设默认 `timeout_seconds` 与 `max_retries`（或文档强制必填其一），
   使崩溃任务默认可恢复。

---

## 三、P2（非阻断，建议随修复处理）

- **P2-R4  stalled schedule 跨重启保持停摆**：`_fire_one` 失败时把 `next_run_at` 置 None
  （`engine.py:292-296`）；`load_schedules` 只 arm `next_run_at is not None` 的行（`engine.py:209`），
  故一次失败停摆的 schedule 重启后仍停摆，需人工 re-arm 或改配置。建议启动时对 enabled 但
  next_run_at 缺失的行做 repair/recompute 并显式告警。
- **P2-R5  "no-queue" 软成功 trace 失真**：`{"enqueued": false, "reason": "no-queue"}` 记为
  `ExecutionLog status=success`（`engine.py:265-267` + `dispatcher.py:101`），运维扫 failed 看不到丢弃。
  建议单独 status（如 `skipped`/`dropped`）或至少 warning 级 + 聚合计数。
- **P2-R6  单次 tick 串行 + 每 fire 3 次 DB 往返**：`_run` 单 asyncio 任务，due 批次内 `_fire_one` 串行
  （`engine.py:235-238`），每个 fire = commit(running)+select+commit(terminal) 3 查询。低频 V1 可接受；
  秒级 cron 高频时为吞吐瓶颈。`disarm` 为 O(n) 重建堆（`engine.py:177-182`），小规模可接受。
- **P2-R7  丢失 terminal commit 的重复 fire**：commit(running) 成功而 commit(terminal) 丢失时，重启后
  按 last_run 重新 fire（at-least-once）并留一条 stale `running` ExecutionLog。建议幂等键或对
  stale running log 收尾。低优先。

---

## 四、可扩展性 / 边界确认

- 事件驱动链路（CRM/conversation 桥）**端到端真实执行**（handler 内联跑 action，非入队）——
  唯一当前真正闭环的触发类型；这也是 QA "closed-loop" 实际跑通的部分。
- 调度器→队列这半，"入队"已落地，"消费 + 恢复"未落地，故定时触发**尚未系统级可用**（同架构审查 P1-2 结论的残留）。
- 可插拔抽象（JobDispatcher/Executor/QueueDispatcher）设计良好，边界清晰；上述缺口属**接线/默认值**问题，非架构错。

---

## 复审要求（DoD）
1. 处置 P1-R1：seed 默认队列 和/或 默认 require_queue=True 和/或 提供可选 in-process consumer；
   核心目标：**缺队列不再是静默 success**（必须可观测或真实执行）。
2. 处置 P1-R2：启动回收 stale running + 自动 sweep 驱动 + 默认超时/重试基线；核心目标：
   **默认配置下崩溃/卡死任务可恢复**。
3. 顺手处理 P2-R4~R7。
4. 完成后重跑 `test_scheduler.py + test_workflow_*.py` 回归 + 真实 Postgres E2E
   （含：默认部署下定时 fire 的端到端执行、崩溃 running 任务的重投、sweep 触发），再复审。
