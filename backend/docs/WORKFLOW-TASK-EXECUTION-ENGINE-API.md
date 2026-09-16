# Queue + Worker 执行引擎 API 文档 (Phase 4 / t_wf_004)

> 任务卡：`t_bd5cc37a` — Queue + Worker 执行引擎
> 依赖：`t_wf_001`（Workflow 后端框架 + Schema）、`t_wf_003`（Scheduler）
> 实现位置：
> - 模型：`backend/app/db/models/workflow_task.py`（`WorkflowTask` 任务单元）
> - 服务：`backend/app/services/workflow_task.py`（`QueueWorkerEngine` 执行引擎）
> - 路由：`backend/app/routers/workflow_task.py`
> - Schema：`backend/app/schemas/workflow_task.py`
> - 迁移：`backend/alembic/versions/016_workflow_task.py`
> - 测试：`backend/tests/test_workflow_task.py`（47 用例，引擎覆盖率 92%）

## 概述

`t_wf_004` 实现工作流任务的**异步执行引擎**：任务入队 → 出队（Worker 抢占）
→ 执行 → 状态追踪（pending/running/success/failed/cancelled/timeout）→ 超时处理。
引擎只依赖 `AsyncSession`，通过可插拔的 `Executor` 适配层与 AI/CRM/浏览器
平台逻辑解耦（符合 ARCHITECTURE 平台隔离原则）。

### 与既有框架的边界

| 归属 | 内容 |
|---|---|
| `t_wf_001`（已落地） | `WorkflowQueue` / `WorkflowWorker` 配置实体 + 通用 CRUD（`/workflow-queues`、`/workflow-workers`） |
| `t_wf_004`（本卡） | `WorkflowTask` 任务实体 + 入队/出队/执行/状态/超时的**执行引擎** + 队列管理 API |
| `t_wf_005` | `ExecutionLog` 执行日志（可观测层） |
| `t_wf_003` | Scheduler 调度器（Cron/间隔），可把到期的调度任务 `enqueue` 到本引擎 |

`WorkflowTask.queue_id / worker_id / workflow_id` 为**无 FK 约束的索引 UUID**
（与 `ExecutionLog` 同样的解耦选择），后续可在 schema 稳定后升级为真 FK。

### 任务状态机

```
pending -> running -> success | failed | timeout
                  -> cancelled
failed / timeout -> pending  (retry，retry_count < max_retries 时)
```

合法转移表见 `services/workflow_task.py` 的 `LEGAL_TRANSITIONS`。

## 数据库 Schema

### `workflow_task` 表

| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | 任务 ID（默认 uuid4） |
| queue_id | UUID, index | 所属队列（逻辑引用，无 FK） |
| worker_id | UUID, nullable, index | 绑定/抢占的 Worker（逻辑引用） |
| workflow_id | UUID, nullable, index | 关联工作流（逻辑引用） |
| name | varchar(200), nullable | 任务名 |
| payload | JSONB, 默认 {} | 执行器输入参数 |
| status | varchar(20), 默认 pending, index | pending/running/success/failed/cancelled/timeout |
| priority | int, 默认 0 | 越小越先出队（FIFO 队列内按 priority 再按 created_at 排序） |
| scheduled_at | timestamptz, nullable | 延迟执行；NULL/已过 = 可被 claim |
| retry_count | int, 默认 0 | 已重试次数 |
| max_retries | int, 默认 0 | 最大重试次数（0 = 不重试） |
| timeout_seconds | int, nullable | 单任务超时；NULL 回退到 queue.timeout_seconds |
| claimed_at | timestamptz, nullable | Worker 抢占时刻 |
| started_at | timestamptz, nullable | 实际开始执行 |
| finished_at | timestamptz, nullable | 进入终态时刻 |
| duration_ms | float, nullable | 执行耗时（毫秒） |
| result | JSONB, nullable | 执行结果 |
| error_message | text, nullable | 错误信息 |
| error_code | varchar(100), nullable | 错误码 |
| metadata_ | JSONB, 默认 {} | 可观测元数据（**禁止存密钥**，见 ARCHITECTURE #16） |
| created_at / updated_at | timestamptz | 时间戳 |
| is_deleted | bool, 默认 false | 软删除 |

索引：
- `idx_task_queue_status_scheduled (queue_id, status, scheduled_at)` — 热出队路径
- `idx_task_status_started (status, claimed_at)` — 超时扫描
- `idx_task_status_retry (status, retry_count)` — 重试判定

### 出队（claim）的原子性

`claim_next` 使用 Postgres `SELECT ... FOR UPDATE SKIP LOCKED`，
保证单机多 Worker 时同一任务不会被双抢占。FIFO 内以 `priority ASC,
created_at ASC` 排序取 1 条。

### 超时处理（扫描式）

`sweep_timeouts` 周期性（可由调度器/cron 驱动）扫描 `status=running` 任务：
有效超时 = `task.timeout_seconds`（若 NULL 则回退 `queue.timeout_seconds`），
`started_at/claimed_at + timeout <= now` 即置为 `timeout` 终态（error_code=TIMEOUT）。
仍可用 `retry_task` 重新入队（若有剩余重试次数）。

## API 端点（前缀 `/api/v1/workflow-tasks`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/` | 任务入队（`TaskCreate` → 新建 pending 任务） |
| GET  | `/` | 任务列表（filter + 分页，`TaskFilter`） |
| GET  | `/health` | 服务自检（**须置于 `/`+`/{task_id}` 之前注册**，避免被参数路由吞掉） |
| GET  | `/{task_id}` | 单个任务 |
| PUT  | `/{task_id}` | 更新非终态任务的可变字段 |
| POST | `/{task_id}/cancel` | 取消 pending/running 任务 |
| POST | `/{task_id}/retry` | 将 failed/timeout 任务重新入队（有重试次数时） |
| POST | `/{task_id}/complete` | 标记 running 任务成功 |
| POST | `/{task_id}/fail` | 标记 running 任务失败 |
| POST | `/queues/{queue_id}/claim` | **出队**：原子抢占该队列最老的就绪任务 |
| POST | `/queues/{queue_id}/stats` | 队列各状态计数 + 可重试/空闲/积压标志 |
| POST | `/queues/{queue_id}/clear` | 排空队列（取消 pending[/running]） |
| POST | `/sweep-timeouts` | 扫描并标记超时任务 |

### 执行器（进程内策略，非 HTTP）

`POST /{task_id}` 之后由**进程内调用方**（调度器 tick、事件处理器、测试）
通过 `QueueWorkerEngine.execute_task(task, executor, context)` 驱动实际执行，
`executor` 是可插拔策略对象：
- `EchoExecutor`：默认无副作用双份（测试/演示用）
- 真实集成（`t_wf_006` 对话、`t_wf_007` CRM）提供自己的 Executor 适配器

> 执行器是代码对象（策略），不序列化为 JSON，故**不作为 HTTP 端点**暴露；
> 状态与结果通过上面的 complete/fail/claim 端点持久化与追踪。

## 错误语义

- 404：`TaskNotFoundError`（任务不存在 / `/{task_id}` 未命中）
- 409：`TaskStateError`（非法状态转移，body 含 from_state/to_state/reason）
- 422：schema 校验失败（非法 status/pattern 不符）
- 200：入队/出队成功；`/queues/{id}/claim` 空队列返回 `null`（JSON）

## 测试

- `tests/test_workflow_task.py`：47 用例全部通过，DB 会话以 `AsyncMock` mock
  （与 `test_workflow_execution_log` 约定一致，独立于活的 Postgres）。
- 覆盖率（`pytest-cov --cov-branch`）：model 96% / schema 100% / service 89%，
  合计 **92%** ≥ 80% 验收线。

## 已知事项 / 风险

- 依赖 `t_wf_001` 的 `WorkflowQueue` 实体（`workflow_runtime.py`）做超时回退
  查询；`sweep_timeouts` 延迟导入，缺该表时回退为“无超时回退”，不影响任务
  级 `timeout_seconds` 判定。
- `alembic` 迁移树当前存在多 head（`016_workflow_task` 与 `016_scheduler_due_index`
  同挂 `015_workflow_framework`；另有 `015_workflow_config` 与
  `015_workflow_framework` 双建 `workflow` 表的冲突）。本卡迁移已正确挂在
  框架 head 上并可用 `alembic upgrade` 应用；多头/重复表冲突属 `t_wf_001`/
  `t_wf_003` 集成范围，需在合并时由 orchestrator 指定唯一 head（详见
  `WORKFLOW-DB-SCHEMA.md` 冲突注记）。
