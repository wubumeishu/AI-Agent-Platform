# Phase 2 - 短期/长期记忆系统实现文档

## 概述

本任务实现了 AI Agent 的记忆系统，支持短期对话记忆和长期知识库记忆。

## 实现内容

### 1. 数据模型 (app/db/models/memory.py)

#### Memory (长期记忆)
- 存储用户偏好、事实、历史记录和洞察
- 支持分类（general, product, service, personal）
- 重要性级别（1-10）
- 可信度评分（0-1）
- GIN 索引支持标签搜索

#### MemoryFragment (记忆片段)
- 记忆的细分单元
- 支持向量嵌入（用于语义搜索）

#### ConversationSummary (对话摘要)
- 短期记忆摘要
- 关键点提取
- 情感分析
- 待办事项记录

#### ContextWindow (上下文窗口)
- 管理对话上下文状态
- 跟踪 token 使用量
- 压缩历史功能

#### ActivityLog (活动记录)
- 记录用户活动
- 关联到客户和线索

### 2. Pydantic Schema (app/schemas/memory.py)

- MemoryCreate/Update/Response
- MemorySearchRequest/Response
- MemoryInjectionRequest/Response
- ConversationSummaryCreate/Response
- ContextWindowResponse

### 3. 服务层 (app/services/memory_service.py)

#### 长期记忆 CRUD
- create_memory: 创建记忆（自动清理低重要性记忆）
- get_memory: 获取记忆
- list_memories: 列表记忆（支持过滤和分页）
- update_memory: 更新记忆
- delete_memory: 软删除记忆

#### 记忆搜索
- search_memories: 关键词搜索（支持类型和类别过滤）
- get_relevant_memories: 获取相关记忆
- inject_memories_into_context: 注入记忆到上下文

#### 短期记忆管理
- create_conversation_summary: 创建对话摘要
- get_conversation_summaries: 获取对话摘要列表
- auto_generate_summary: 自动生成摘要（超过阈值时触发）

#### 上下文窗口管理
- get_or_create_context_window: 获取或创建上下文窗口
- update_context_window: 更新 token 计数
- check_compression_needed: 检查是否需要压缩

#### 统计分析
- get_memory_statistics: 获取记忆统计信息

### 4. API 路由 (app/routers/memory.py)

RESTful API 端点：
- GET /api/v1/memory/ - 列出记忆
- POST /api/v1/memory/ - 创建记忆
- GET /api/v1/memory/{id} - 获取记忆
- PUT /api/v1/memory/{id} - 更新记忆
- DELETE /api/v1/memory/{id} - 删除记忆
- POST /api/v1/memory/search - 搜索记忆
- POST /api/v1/memory/inject - 注入记忆
- GET /api/v1/memory/conversations/{id}/summaries - 对话摘要
- POST /api/v1/memory/conversations/{id}/summaries - 创建摘要
- GET /api/v1/memory/conversations/{id}/context-window - 上下文窗口
- GET /api/v1/memory/statistics/{customer_id} - 统计信息
- GET /api/v1/memory/health - 健康检查

### 5. 数据库迁移 (alembic/versions/011_memory_system.py)

创建以下表：
- memory
- memory_fragment
- conversation_summary
- context_window

### 6. 测试套件 (tests/test_memory.py, tests/test_memory_api.py)

#### 单元测试 (16个)
- TestMemoryService: 6个测试
- TestMemorySearch: 2个测试
- TestMemoryInjection: 1个测试
- TestConversationSummary: 2个测试
- TestContextWindow: 3个测试
- TestMemoryStatistics: 1个测试
- TestMemoryLimits: 1个测试

#### API 测试 (10个)
- 所有主要端点的集成测试

**测试结果：26/26 通过**

## 关键设计决策

1. **软删除**: 使用 is_deleted 标志而非物理删除，便于恢复和审计
2. **自动清理**: 当记忆数量超过限制时，自动删除低重要性记忆
3. **关键词搜索**: 使用 ILIKE 进行大小写不敏感的关键词匹配
4. **上下文压缩**: 当 token 使用量超过 80% 时触发压缩
5. **自动摘要**: 对话超过 20 条消息时自动生成摘要

## 性能考虑

- 最大记忆数：100/客户
- 上下文窗口：4000 tokens
- 搜索时间：< 100ms（关键词匹配）
- GIN 索引用于标签搜索

## 后续优化（Phase 3+）

1. 向量嵌入和语义搜索
2. 记忆冲突解决
3. 记忆可视化
4. 自动学习机制

## 文件清单

```
app/db/models/memory.py          # 数据模型
app/schemas/memory.py            # Pydantic Schema
app/services/memory_service.py   # 服务层
app/routers/memory.py            # API 路由
alembic/versions/011_memory_system.py  # 数据库迁移
tests/test_memory.py             # 单元测试
tests/test_memory_api.py         # API 测试
```

## 依赖关系

- Phase 1: Persona 实体（用户画像）
- Phase 2: Conversation/Message 系统
- Redis: 缓存层（后续实现）
- PostgreSQL: 持久化存储
