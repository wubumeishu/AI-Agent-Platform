# CURRENT FOCUS

## 当前阶段

Phase 2 — AI & Conversation

## 当前目标

实现 AI 对话核心功能，包括 Provider 配置、Prompt 管理、Agent 上下文、对话管理、Persona 生成、记忆系统。

---

## 当前只允许处理

### Phase 2 任务

**AI Provider**
- 多模型支持（OpenAI、Anthropic、本地模型）
- Provider 适配器接口
- 模型配置管理

**Prompt Management**
- Prompt 模板系统
- 变量替换
- 版本管理

**Agent Context**
- 对话上下文管理
- 消息历史记录
- 上下文窗口控制

**Conversation**
- 会话创建/管理
- 消息发送/接收
- 流式响应支持

**Message**
- 消息模型定义
- 消息存储
- 消息查询

**Persona Generation**
- Persona 风格化生成
- 人格参数配置
- 生成质量评估

**Memory**
- 短期记忆（会话内）
- 长期记忆（跨会话）
- 记忆检索

**Knowledge**
- 知识库管理
- RAG 支持
- 文档索引

**Intent**
- 意图识别
- 意图分类
- 意图执行映射

---

## 暂时禁止

CRM
Workflow
Private Domain
Analytics
Future Features

除非当前任务明确要求。

---

## 当前成功标准

用户能够：

1. 配置 AI Provider
2. 选择模型
3. 创建对话
4. 发送消息
5. 查看回复
6. 管理 Persona
7. 使用记忆系统

---

## 当前开发原则

1. 先实现核心功能，再优化体验
2. Provider 抽象必须清晰
3. 支持多模型切换
4. 记忆系统要可观测
5. 完成后必须实际测试

---

## 当前唯一目标

让用户能够：

> "配置 AI，开启对话，获得智能回复"

其他事情全部排队。
