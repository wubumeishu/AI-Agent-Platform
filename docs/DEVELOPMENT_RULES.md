# DEVELOPMENT_RULES.md
## Engineering Rules v1.0

## 1. General Rule

先理解，再修改；先小步，再扩展；先验证，再宣称完成。

---

## 2. Inspect Before Edit

任何 Agent 开始修改代码前必须：

1. 读取 PROJECT.md
2. 阅读相关 ARCHITECTURE.md / ADR
3. 读取当前任务卡
4. 搜索现有实现
5. 了解调用关系
6. 再开始修改

---

## 3. Reuse Before Create

优先：

现有组件 > 新组件
现有服务 > 新服务
现有 API > 新 API
现有模型 > 新模型

避免重复实现同一个概念。

---

## 4. Small Changes

除非任务明确要求：

- 不大规模重写
- 不顺便重构
- 不删除未知代码
- 不改变无关模块

---

## 5. Scope Control

每张任务卡只有明确的范围。

发现额外需求：

创建新任务。

不要把新需求混入当前任务。

---

## 6. Frontend Rules

- Vue 3 + TypeScript
- 使用现有 Design System
- 组件保持单一职责
- API 调用统一管理
- 处理 loading / empty / error 状态
- 不直接访问数据库

---

## 7. Backend Rules

- FastAPI
- Pydantic
- SQLAlchemy
- 明确 service 边界
- API 不承载过多业务逻辑
- 错误可追踪
- 敏感信息不进入日志

---

## 8. Database Rules

新增表前必须检查：

- 是否已有等价概念
- 是否可以复用已有实体
- 是否破坏现有关系

Schema 改动必须可追踪。

---

## 9. AI Rules

AI 行为必须尽量结构化。

重要 AI 能力应该明确：

Input
→ Context
→ Decision
→ Action
→ Expected Output
→ Failure Case

不得只依靠一段 Prompt 隐式承担整个业务系统。

---

## 10. Automation Rules

Automation 负责执行，不负责制定业务目标。

业务决策：Agent / Strategy / Workflow

执行动作：Automation

浏览器连接：BrowserProvider

平台差异：PlatformAdapter

---

## 11. BitBrowser Rule

V1 只有 BitBrowser。

不得把 BitBrowser 调用散落到业务模块。

统一通过 BrowserProvider / BitBrowserProvider。

---

## 12. Logging Rules

日志必须有：

- 时间
- 模块
- 操作
- 状态
- 错误上下文

不得记录：

- 密码
- API Key
- Cookie
- Token
- 完整敏感客户资料

---

## 13. Error Handling

不得静默吞掉错误。

错误必须：

- 可发现
- 可定位
- 可复现
- 对用户有合理提示

---

## 14. Testing Rules

对于重要功能：

1. Build
2. Start
3. Execute real flow
4. Test normal path
5. Test failure path
6. Inspect runtime logs
7. Record result

---

## 15. UI Completion Rule

“页面出现”不等于“功能完成”。

必须验证：

- 输入
- 保存
- 加载
- 修改
- 删除（如适用）
- API 状态
- 错误显示

---

## 16. Mock Data Rule

Mock 数据可以用于 UI 开发，但必须清晰标记。

禁止把 Mock 成功当成后端功能完成。

---

## 17. Security Rules

任何敏感凭据不得硬编码进代码。

不要在仓库提交：

- API Key
- 密码
- Cookie
- Token
- 私有代理凭据

---

## 18. Dependency Rules

新依赖必须说明：

- 为什么需要
- 是否已有替代
- 维护成本
- 对构建大小的影响
- 对安全的影响

不为小需求引入大型框架。

---

## 19. Completion Rule

开发者必须报告：

- 做了什么
- 改了哪些文件
- 如何运行
- 如何验证
- 已知问题

然后进入 QA / Review。

---

## 20. Golden Rule

如果无法证明功能真实可用，就不要声称功能完成。
