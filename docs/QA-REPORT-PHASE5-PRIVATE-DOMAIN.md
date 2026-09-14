# Phase 5 私域模块 端到端 QA 验收报告

- 任务: t_6fc4a88f (Phase 5 Private Domain End-to-End QA), QA: qa-engineer
- 日期: 2026-09-14 (Tokyo)
- 项目: H:/AI-Agent-Platform (backend FastAPI + PostgreSQL 16)
- 结论: **FAIL — 3 个 P0 + 2 个 P1，已创建修复任务；端点级功能大部分通过，但 P0 阻断验收闭环**
  - 注: P0-3（main 不可导入）在 QA 会话期间被并行后端 worker 修好（当前代码 `from app.main import app` OK，348 路由，uvicorn 8104 启动成功 + health 200）。t_15dc63d6 转为"验证并防回退"任务。P0-1/P0-2 在当前代码上重新复现确认仍然 500。

## 1. 测试环境与方法

| 项 | 说明 |
|---|---|
| 数据库 | PostgreSQL 16 @ localhost:5432，`ai_agent_platform_test`（新建，全量 create_all + 种子数据：platform/account/customer/lead 各 1 条） |
| 被测服务 | 当前代码的最小可运行测试应用（`_qa_test_app.py`：private-domain + CRM + conversations + platforms 路由），因全量 `app.main` 因 P0-3（workflow 模块半成品）无法导入 |
| 主库状态 | `ai_agent_platform` 无 customer/lead/conversation 等表、无 alembic_version —— 主库从未跑过迁移（本身也是缺陷，见 P1-2 备注） |
| 用例 | 端到端旅程 43 步 + 边界/错误处理 11 步 + 单元套件（pytest，私域相关 7 个文件 189 用例） |

说明：8001 端口在线服务是**旧构建**（路由双前缀 bug 的活体证据）；8101/8103 为 QA 期间按当前代码启动的临时实例。

## 2. 证据矩阵

| 类别 | 结果 | 证据 |
|---|---|---|
| 单元/集成 Mock 测试 (pytest, 7 私域相关文件) | 178/189 PASS，11 FAIL | `tests/test_data_integrity.py` 11 个用例因 mock_db(AsyncMock) 与真实 service 接口漂移失败（`'coroutine' object has no attribute 'is_deleted'`，service 行 234/374/528/692/725）；`test_private_domain/test_integration/test_nurture_plan/test_customer_service/test_crm_lifecycle` 全部通过 |
| 端到端旅程（真实 PG + 真实 HTTP） | **39/43 PASS** | e2e_journey.py，结果存 e2e_private_domain_results.json |
| 边界/错误处理 | 9/11 PASS（2 项发现缺陷 E5/E7-E8） | edge_cases.py |
| 跨模块集成 (Lead→Customer、Channel↔Customer、NurturePlan apply、DealItem 关联) | PASS | 旅程 STAGE 1/3/4/6 均 200/201 |
| 构建/导入 | **FAIL (P0-3)** | `from app.main import app` → ModuleNotFoundError: app.schemas.workflow 缺 WorkflowCreate |
| 数据库 Schema（私域 9 表） | PASS | psql 验证 private_channel/nurture_plan/content_item/follow_up_task/customer_segment/segment_member/deal_pipeline/deal_stage/deal_item 齐全 |

### 端到端旅程通过明细（39/43）
- STAGE 1 Lead→Customer 转换: PASS (200)
- STAGE 2 Channel CRUD: PASS (201/200)
- STAGE 3 Customer↔Channel 关联: PASS
- STAGE 4 NurturePlan 全流程（创建/步骤/重排/状态迁移/统计/应用到客户）: PASS
- STAGE 5 Segment（创建/加成员/批量/列表/统计/移除）: PASS；**sync 动态分群: FAIL 500 (P0-2)**
- STAGE 6 DealPipeline（创建/统计/integration 建单/客户订单查询）: PASS；**stage 创建时未落 deal_stage 表 + 迁移 422 (P1-1)**
- STAGE 7 Follow-up（创建/迁移/逾期检查/提醒/统计）: PASS
- STAGE 8 内容库（创建/搜索/使用追踪/统计）: PASS
- STAGE 9 集成统计/一致性检查: **FAIL 500 (P0-1)**；account 级统计 3 个: PASS

## 3. 缺陷清单

### P0-1 `is_(not None)` SQL 生成错误 → 一致性/集成统计 500 〔P0, 阻断〕
- 文件: `app/services/integration_service.py` 行 560/586/610/652/674/735/746（共 7 处）
- 根因: Python 中 `not None == True`，`Column.is_(not None)` 编译为 `col IS TRUE`；PostgreSQL 对 UUID 列报错 `DatatypeMismatchError: IS TRUE 的参数必需是类型boolean, 而不是类型uuid`
- 复现: `GET /api/v1/private-domain/integration/consistency/check?account_id=<acc>` → 500；`GET .../integration/stats?account_id=<acc>` → 500（`get_integration_stats` 725/746 行同模式）
- 期望: 200 返回一致性结果；实际: 500，服务端堆栈完整落在上述 SQL
- 影响: `validate_data_consistency` 与 `get_integration_stats`（Phase 5 集成层核心端点）全不可用；同模式共 7 处

### P0-2 动态分群 sync 必 500（属性错误）
- 文件: `app/services/segment_rule_engine.py` 行 296
- 根因: `select(Customer.id)` 返回标量 UUID，代码却写成 `{row.id for row in customers_result.scalars().all()}` → `AttributeError: 'asyncpg.pgproto.pgproto.UUID' object has no attribute 'id'`
- 复现: 创建 `segment_type=dynamic` 段后 `POST /segments/{id}/sync` → 500（手工验证 3 次稳定复现）
- 期望: 200 返回成员增减；实际: 500
- 影响: CustomerSegment 动态更新能力（验收范围第 2 项）完全不可用

### P0-3 主应用无法导入/启动（模块半成品）
- 文件: `app/main.py` 行 21-23 新引入 decision/workflow/workflow_config；`app/schemas/workflow.py` 缺 `WorkflowCreate` 等类，`app/services/workflow.py:22` 导入失败
- 复现: `python -c "from app.main import app"` → `ImportError: cannot import name 'WorkflowCreate' from 'app.schemas.workflow'`；uvicorn 启动即崩
- 影响: 全量服务不可启动 → 全模块端到端无法闭环；8001 在线旧构建即此状态的历史遗留（其 CRM 路由为双前缀）
- 备注: 疑似并行后端 worker 正在补写 workflow 模块（会话中代码持续变化）。**[QA 收尾时更新] 已确认该模块被并行 worker 收口：当前代码导入 OK、uvicorn 可启动。t_15dc63d6 改为"验证 + 防回退"，不再需要补写。**

### P1-1 DealPipeline 双轨阶段模型：创建时 stages 不落 deal_stage 表
- 文件: `app/services/private_domain.py` `create_deal_pipeline`（行 ~1066）
- 现象: `POST /pipelines` 带 `stages:[...]` → 201，但 stages 仅写入 `deal_pipeline.stages`(JSON)；`GET /pipelines/{id}/stages` 返回 `[]`，`deal_stage` 表 0 行；导致 `POST /deals/{id}/transition` 422（找不到 stage_id）
- 复现: 见旅程 STAGE 6；单独建 stage（`POST /pipelines/{id}/stages`，body 需带 `pipeline_id`）后迁移 200 成功 —— 证明 deal_stage 通路正常，只是 pipeline 创建与 deal_stage 表脱钩
- 影响: DealPipeline 完整流转（验收范围第 4 项）体验断裂：用户"建管道即带阶段"的契约不成立
- 附带错误处理缺陷: `transition_deal_endpoint` 无 body（默认 None）→ `data.stage_id` 抛 AttributeError → **500**（应为 422）；对不存在的 deal 迁移返回 **200 null**（应为 404）——错误处理 2 处偏差已记入修复任务

### P1-2（路由）CRM 子路由双前缀
- 文件: `app/crm/routers/customer.py:10`、`customer_360.py:10`、`lead.py:19`、`tag.py:11` 自带 `prefix="/api/v1/..."`，`main.py` 再挂 `prefix="/api/v1"` → 实际路由为 `/api/v1/api/v1/crm/...`
- 复现: `GET /api/v1/crm/customers` → 404；`GET /api/v1/api/v1/crm/customers` → 200（当前代码 8103 上实测）。8001 旧构建上正确路径 404 同证据（CRM QA t_8119f738 曾报 0/35，根因即此）
- 影响: 前端若按文档路径 `/api/v1/crm/...` 调用将全 404；属架构层问题，移交架构评审/后端统一前缀

### 备注（非阻断）
- `test_data_integrity.py` 11 个 mock 用例失败：mock 与 service 接口漂移，需修 mock（不影响真实行为结论）
- alembic 迁移链断裂: `002_add_platform` 的 `down_revision='001_initial'` 在 versions/ 中不存在 → `alembic upgrade head` 报 KeyError；且存在多头（002/006×3/008/013 多 head）未合并；主库 `ai_agent_platform` 无 alembic_version，表为手工建。已临时补 stub `001_initial` 验证链，需后端正式补真实迁移并合并多头
- 主库缺 customer/lead/conversation 等表（`Base.metadata.create_all` 在 main.py 中已注释），即 8001 旧构建 CRM 接口全 500 的另一层原因

## 4. 验收判定

| 验收标准 | 结果 |
|---|---|
| 端到端场景测试通过 | **FAIL**（P0-1/P0-2 致 sync/一致性/集成统计 500；P1-1 致管道阶段流转断裂） |
| 跨模块集成正常 | PARTIAL（Lead→Customer、Channel↔Customer、Nurture apply、Deal 关联均 PASS；consistency/stats 不可用） |
| 无阻塞性 Bug | **FAIL**（3×P0） |
| 验收报告完成 | 本文件 |

判定: **FAIL**，修复 3 个 P0 + 2 个 P1 后回归。

## 5. 修复任务清单（已创建，QA 任务完成后派发）
- t_a60c6686 (P0): integration_service `is_(not None)` ×7 → `isnot(None)`
- t_226c42fb (P0): segment_rule_engine 行 296/后续行 标量 UUID 误用 row.id → set(...scalars().all())
- t_15dc63d6 (P0): app.main 导入/启动收口验证（并行 worker 已修好，此任务做验证 + 防回退）
- t_c721db22 (P1): deal pipeline 创建时同步落 deal_stage；修 transition 无 body→422、不存在 deal→404
- t_b6b64212 (P1): CRM 路由前缀去重（canonical URL 统一单前缀 /api/v1/...，决策已定写死在任务体）
- 回归: 全部修复完成后由 qa-engineer 重跑本报告旅程 43 步 + 边界 11 步 + pytest 私域套件

## 6. QA 工件
- e2e_journey.py / edge_cases.py / probe_*.py / map_endpoints.py: 测试脚本（workspace: I:\hermes\kanban\workspaces\t_6fc4a88f）
- 结果 JSON: e2e_private_domain_results.json, edge_results.json, flow_results.json
- 后端临时脚本: H:/AI-Agent-Platform/backend/_qa_*.py（验收后可删）
