# Workflow 模块架构审查报告 (t_c81d72fe / t_wf_015)

Reviewer: code-architecture-reviewer
Scope: 数据库 Schema / API 接口 / 模块边界与依赖 / 代码质量 / 可扩展性 / 调度器设计
Out of scope: 前端 UI、安全渗透(由专门安全任务负责)
Base: H:/AI-Agent-Platform/backend (main checkout, 7 个实现任务 t_wf_001~007 全部完成)
Verdict: **CHANGES_REQUIRED**

---

## 结论概览

Workflow 子系统的配置模型 + 通用 CRUD 骨架 + 事件驱动的 CRM/Conversation 桥接，工程质量整体较高
(测试 104/48/49/38 全绿、真实 Postgres E2E、模块解耦清晰、可插拔执行器抽象到位)。
但存在 **1 个 P0 功能性缺陷** 和 **多个 P1 架构/一致性问题**，未达到验收标准，需修复后复审。

判定理由(对照验收标准逐条):
- [x] 架构决策基本符合项目规范(可插拔执行器、事件总线域拆分、逻辑 UUID 解耦均遵循 ARCHITECTURE.md)
- [ ] 模块边界清晰 → **P1: /workflows 双路由重叠，边界被打破**
- [x] 数据库设计合理(多表 schema、软删除、唯一/部分索引、015→020 迁移链已 linearize 到单 head)
- [ ] API 设计符合规范 → **P1: 同一资源双 API 面 + OpenAPI 重复 Operation ID**
- [x] 审查报告已提交(本文档)

---

## P0 阻断项

### P0-1  秒级(6字段)Cron 下次触发时间计算错误，执行精度验收不达标
文件: `backend/app/services/scheduler/cron_parser.py` `compute_next_cron_time` (行 187-203)

当 `spec.has_seconds` 为真(6 字段 cron)，内层循环只按 **分钟** 步进:
```python
for _m in range(1440):
    cand = d0 + timedelta(minutes=_m)   # 秒分量恒为 minute_norm，从不递增秒
```
秒分量被钉死在 `minute_norm = min(spec.seconds) % 60`，因此秒级 cron 的相邻两次触发间隔恒为 60s，
而非配置的实际间隔。

**实测**(本地 python 直接调用,非推断):
```
spec = parse_cron("*/10 * * * * *")      # 每 10 秒
next after 00:00:00 -> 00:01:00  (间隔 60s, 期望 10s)
next after 00:00:05 -> 00:01:00  (间隔 55s, 期望 10s)
```
影响:
- 直接违反 t_wf_003 验收标准「调度准确性 误差 < 1s」(秒级配置误差最高 50s)。
- 引擎 docstring 声称「6-field second fires land exactly on the boundary」为 **假实现描述**，与代码行为矛盾。
- 5 字段(分钟级)计算正确(实测 */5 分钟边界精确)，故缺陷仅限秒级路径。

修复建议: 秒级 spec 时内层循环改为按 1s 步进(或先定位到分钟窗口再在窗口内按秒扫描)，
并对齐 48 个 scheduler 单测(当前测试未覆盖 `*/N * * * * *` 秒级步进，漏测是本 bug 逃逸根因)。

---

## P1 架构 / 边界 / 一致性问题

### P1-1  同一 `/workflows` 资源存在两套并存 API，边界被打破
- `routers/workflow_config.py` (prefix `/workflows`): 嵌套 CRUD + `/detail` + `/triggers/fire`
- `routers/workflow_framework.py`: 扁平 CRUD(`/workflows`、`/workflow-triggers`、`/workflow-conditions`、`/workflow-actions`…)

`main.py` 中 `workflow_config_router` 先注册(行 68)、`workflow_framework_router` 后注册(行 69)。
FastAPI 对同路径取先注册者 → **framework 的 `GET/POST /workflows` 被 config 的嵌套路由遮蔽**，
实测 OpenAPI 生成时已产生告警 `Duplicate Operation ID create_workflow_api_v1_workflows_post`。

后果:
- 对同一 workflow 资源有两个"事实来源"(嵌套 vs 扁平)，语义重叠、客户端易误用。
- 这是 backend 工程师在 t_wf_002 卡上已标记的 hotspot("建议后续收敛为单一规范 API")，
  本审查予以确认 —— 属于应修复而非"两可"的架构债。

修复建议: 收敛为单一 API 面(推荐保留嵌套 `workflow_config`，删除 framework 中对
`/workflows` 的重复声明，或将 framework 重定位为纯运行时实体 delay/branch/scheduler/queue/worker 的 CRUD)。
需后端裁决并更新 OpenAPI。

### P1-2  调度器执行链路断开：NoopDispatcher 默认 + 无自动 start，定时工作流端到端不可用
- `engine.py` 默认 `NoopDispatcher`，`dispatch()` 返回 None —— **定时触发不执行任何工作流动作**，仅写一条 ExecutionLog。
- 全仓 grep 仅有 `NoopDispatcher` 一个实现，**没有任何 JobDispatcher 把 cron 触发接入 t_wf_004 的 Queue/Worker 或工作流执行器**。
- `main.py` 的 startup 钩子只注册了 conversation subscriber；**不调用 `engine.start()`**。
  因此进程重启后调度器默认停止，持久化 schedule 不会自动 re-arm，需人工 `POST /schedulers/engine/start`。
  这与 `engine.py` docstring 行 171「restarts pick up persisted schedules」的承诺矛盾 —— 该承诺仅在显式 start 时成立，而 start 未接 app 生命周期。

影响: 定时(cron/interval)工作流当前是"记录型空壳"，真正能端到端执行的只有 **事件驱动**(conversation/CRM 桥)。
即 t_wf_003 验收「Cron 表达式正确解析并执行」中的"执行"并未真实发生 → 属"mostly working / fake implementation"，必须拒绝默认放行。

修复建议(择一或组合，需与 System Architect 确认目标形态):
1. 将 SchedulerEngine 接入 Queue/Worker：新增一个 `JobDispatcher` 实现，把每次 fire enqueue 为 `WorkflowTask`；
2. 在 `main.py` startup 中按配置自动 `engine.start()` + `load_schedules()`，消除"重启即停"隐坑;
3. 若 V1 明确不做定时执行，须在文档/卡上显式声明 scope，避免误导。

### P1-3  SchedulerService 更新 next_run_at 但不 re-arm 内存堆，DB 与内存状态分叉
`service.py create()/update()` 重算并持久化 `next_run_at`，但**不 push 到引擎内存 min-heap**。
运行中的引擎只认堆 → 新建/修改的 schedule 要等引擎重启才生效；期间 DB 的 next_run_at 与堆状态不一致。
属"隐藏耦合"：DB 持久态与进程内态两套真相源。建议服务层在 create/update/delete 后调用
`get_scheduler_engine().arm()`/移除，或将"下次触发"完全由引擎从 DB 拉取(去掉 service 预计算)。

### P1-4  数据一致性：执行日志为无外键逻辑引用(有意但属应记录的技术债)
`execution_log.{workflow,queue,worker,task}_id` 均为纯索引 UUID、无 FK(t_wf_005 有意为之，便于独立迁移)。
可接受于 V1，但须在 DECISIONS.md 登记为 tech-debt 并计划"稳定后提升为真实 FK"，否则引用可能指向已删除对象且无约束护栏。

### P1-5  迁移脚本残留错误 DDL：downgrade 引用从未创建的 domain
`015_workflow_framework.py` 行 308 `downgrade()` 末尾 `op.execute("DROP DOMAIN IF EXISTS workflow_trigger_type")`，
但 upgrade 中并无任何 `CREATE DOMAIN`。`IF EXISTS` 使其无害，但属复制粘贴自废弃方案的死代码，
会给读迁移者造成"这里曾有 enum/domain 约束"的误导。建议删除该行。

---

## P2 代码质量 / 一致性(非阻断，建议随修复一并处理)

- **P2-1 时间戳一致性**: `workflow_runtime.py` 用 `datetime.utcnow()`(naive)，而 `workflow.py`/scheduler 用
  `datetime.now(timezone.utc)`(aware)。同为 `DateTime(timezone=True)` 列，混用 naive/aware 会造成时区隐患。统一到 aware-UTC。
- **P2-2  N+1**: `workflow_task.py sweep_timeouts`(行 534-540)对每个 distinct queue_id 各发一条
  `select(WorkflowQueue)`。改为一次 `in_()` 批量查询。
- **P2-3  更新越权面**: `_GenericCRUD.update` 用 `model_dump(exclude_unset=True)` + `setattr`，
  若 Update schema 暴露了 `is_deleted`/`created_at` 等字段则可被外部改写。建议 Update schema 明确排除系统列。
- **P2-4  死代码**: `engine.py` 行 338 `_NullSessionCtx` 注释"unused, kept for import compatibility"——无人 import，直接删。
- **P2-5  安全(转专门安全任务)**: `main.py` CORS `allow_origins=["*"]` + `allow_credentials=True`，
  为已知不安全组合。本卡不在安全渗透范围，仅记录移交。

---

## 调度器设计合理性评估(专题)

- **合理**: 纯函数 next-fire 计算(cron_parser/schedule_calc 无 I/O、可单测)、最小堆 + 200ms tick、
  可插拔 JobDispatcher、200ms 粒度对分钟级触发 <1s 误差、ExecutionLog 记录 firing 成败、graceful shutdown。
- **不合理/缺口**: ① 秒级 cron 计算错(P0-1)；② 默认 Noop 执行器使"调度"名不副实(P1-2)；
  ③ 重启不自启 + 不自动 re-arm(P1-2/3)；④ 单机堆在内存，进程即状态容器，无崩溃恢复持久化队列。
  V1 单机可接受，但 ②③ 是"声称有调度能力实际不落地"的验收风险，必须处置。

## 可扩展性评估
- 事件总线为 in-process 单例，已留 `get_event_bus()` 单一接入口，可换 Redis/queue 后端 —— 良好。
- 执行器/调度器均为可插拔抽象(Executor/JobDispatcher/AIResponder) —— 符合平台分层规则，加分。
- 逻辑 UUID 引用使各实体可独立迁移，但也导致无 FK 护栏(见 P1-4)。
- 无分布式调度/优先队列/死信(均明确 out of scope)，V1 边界清晰。

---

## 复审要求(DoD)
1. 修复 P0-1(秒级 cron)并补秒级步进单测。
2. 处置 P1-2(接线真实执行器 或 显式声明 V1 不做定时执行 + startup 自动 start/load_schedules)。
3. 收敛 P1-1 双 `/workflows` API 面为单一规范。
4. 修复 P1-3 next_run_at 与内存堆分叉。
5. 记录 P1-4/P1-5 为 tech-debt；顺带处理 P2-1/2/3/4。
完成后重新跑 Workflow 相关全量 pytest + 真实 Postgres E2E，再复审。
