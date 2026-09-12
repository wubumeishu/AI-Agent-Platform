# AI 智能获客与私域运营平台
## 产品与系统设计书 V1.0

**产品定位：** AI Agent 驱动的公域获客、智能对话、客户沉淀、私域培育与成交转化平台  
**产品形态：** Windows 桌面应用为主，后续可扩展云端服务  
**第一阶段浏览器：** 比特浏览器（BitBrowser）  
**第一阶段目标：** 建立从“公域发现潜客 → AI 判断 → 对话 → 客户沉淀 → 私域经营 → 成交分析”的完整闭环

---

# 一、项目总览

## 1.1 产品愿景

不是制作一个简单的“自动点击 / 自动私信 / 群控”工具，而是构建一个：

> **能够管理多个 AI Agent、多个账号、多个平台，并具备记忆、判断、策略、工作流、客户管理和持续优化能力的 AI Agent 操作平台。**

系统核心闭环：

```text
公域流量
   ↓
发现目标用户
   ↓
内容理解
   ↓
意向判断
   ↓
建立对话
   ↓
AI理解上下文
   ↓
用户画像与记忆
   ↓
阶段判断
   ↓
策略选择
   ↓
对话 / 跟进
   ↓
高意向识别
   ↓
进入私域
   ↓
CRM沉淀
   ↓
持续培育
   ↓
商机
   ↓
成交
   ↓
数据分析
   ↓
策略优化
```

---

# 二、产品核心定位

## 2.1 产品不是“自动引流软件”

产品正式定位为：

> **AI Agent 获客与客户经营平台**

“自动引流”只是其中一个能力。

平台真正的核心能力为：

```text
Persona
+
Account
+
Platform
+
Browser
+
AI
+
Memory
+
Knowledge
+
Intent
+
Strategy
+
Workflow
+
Conversation
+
CRM
+
Private Domain
+
Analytics
```

---

# 三、产品总体架构

## 3.1 顶层架构

```text
                     AI Agent Platform
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
      身份资源              AI智能               执行系统
        │                    │                    │
     Persona              AI Engine            Automation
     Account              Memory               Browser
     Platform             Knowledge            Scheduler
     Channel              Intent               Workflow
     Browser              Strategy             Task Queue
     Proxy                Decision             Events
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                       Conversation
                             │
                 ┌───────────┼───────────┐
                 │           │           │
                CRM        Leads      Messages
                 │           │           │
                 └───────────┼───────────┘
                             │
                       Private Domain
                             │
                    ┌────────┼────────┐
                    │        │        │
                 Content  Nurture   Deals
                    │        │        │
                    └────────┼────────┘
                             │
                         Analytics
                             │
                     Experiment / Optimize
```

---

# 四、桌面应用总体架构

## 4.1 技术方向

第一版建议：

```text
Windows Desktop
        │
      Tauri
        │
     Vue 3
        │
   Application API
        │
     FastAPI
        │
 ┌──────┼─────────────┐
 │      │             │
AI   Automation     Database
 │      │             │
 │   Playwright    PostgreSQL
 │      │
 │  BitBrowser
 │
LLM Providers
```

## 4.2 推荐技术栈

### 前端

```text
Vue 3
TypeScript
Vite
Pinia
Vue Router
```

### 桌面

```text
Tauri 2
```

### 后端

```text
Python
FastAPI
Pydantic
SQLAlchemy
```

### 数据库

第一阶段：

```text
PostgreSQL
Redis
```

如果为了极简本地 MVP，可先：

```text
SQLite + Redis
```

但正式架构建议 PostgreSQL。

### 浏览器自动化

```text
Playwright
```

### 指纹浏览器

V1：

```text
BitBrowser Adapter
```

后续：

```text
BrowserProvider
├── BitBrowser
├── AdsPower
└── LocalChromium
```

---

# 五、产品模块总表

正式产品由以下模块组成：

```text
01  工作台 Dashboard
02  Agent 管理
03  人设 Persona
04  账号 Account
05  平台 Platform
06  比特浏览器 Browser
07  代理 Proxy
08  AI 中心 AI
09  Memory 记忆
10  Knowledge 知识库
11  Intent 意图
12  Strategy 策略
13  Workflow 自动化
14  Scheduler 调度
15  Message 消息
16  CRM / Lead
17  私域中心
18  内容中心
19  商机 / 成交
20  数据分析
21  实验与优化
22  安全中心
23  日志与审计
24  系统设置
25  插件 / API
```

---

# 六、01 工作台 Dashboard

工作台不是简单统计几个数字。

核心目标：

> 让用户打开软件后 10 秒内知道现在发生了什么。

显示：

```text
今日新增线索
高意向客户
待处理消息
AI自动处理
待人工确认
进入私域
新增商机
成交金额
```

示例：

```text
今日概览

新增线索       126
高意向          34
新消息          58
AI处理          42
待人工审核       9
进入私域         7
新增商机         4
成交             2
```

下面展示：

```text
实时任务
实时消息
高价值客户
系统异常
AI异常
账号异常
```

---

# 七、02 Agent 管理

Agent 是产品最重要的抽象对象。

## 7.1 Agent ≠ Persona

Persona：

> “我是谁、怎么说话。”

Agent：

> “一个完整的 AI 数字员工。”

一个 Agent 由：

```text
Agent
├── Persona
├── Accounts
├── Platforms
├── Knowledge
├── Memory
├── Strategy
├── Workflow
├── Goals
├── Tools
└── Permissions
```

组成。

---

# 八、Agent 示例

```text
Agent：

东京房产顾问

Persona：
专业、温和、低销售感

平台：
X
Instagram

账号：
2个

知识库：
东京房产
购房流程
投资房资料

策略：
咨询型

目标：
发现潜在购房客户

工作流：
发现 → 判断 → 对话 → 筛选 → 转私域
```

---

# 九、03 Persona 人设中心

Persona 必须支持：

```text
基础身份
性格
背景
语言
兴趣
价值观
说话方式
回复长度
Emoji
主动程度
情绪
幽默
专业程度
销售倾向
禁止内容
```

## 9.1 语气参数

例如：

```text
正式度       30%
亲和力       80%
幽默         25%
主动性       60%
销售感       15%
Emoji        30%
回复长度     35%
```

---

# 十、Persona 模板

允许创建：

```text
日常社交型
专业顾问型
客服型
销售型
品牌型
内容运营型
```

并支持版本：

```text
Persona v1
Persona v2
Persona v3
```

任何重要变更都保留历史版本。

---

# 十一、04 Account 账号中心

每一个账号记录：

```text
账号名称
平台
平台账号ID
登录状态
绑定Agent
绑定Persona
Browser Profile
Proxy
运行状态
异常状态
最后活动
创建时间
```

账号生命周期：

```text
创建
↓
连接
↓
登录
↓
验证
↓
运行
↓
暂停
↓
异常
↓
恢复
↓
归档
```

---

# 十二、05 Platform 平台中心

平台采用 Adapter 架构。

```text
Platform
    ↓
Adapter
    ↓
Capabilities
```

每个平台声明自己的能力：

```text
读取内容
读取用户
消息
回复
发布
搜索
评论
媒体
API
Browser Automation
```

业务层不能直接写平台逻辑。

---

# 十三、06 Browser 浏览器中心

第一阶段：

> **仅支持比特浏览器。**

架构：

```text
BrowserProvider
      │
      └── BitBrowserProvider
```

以后再扩展：

```text
BitBrowserProvider
AdsPowerProvider
LocalBrowserProvider
```

## 13.1 Browser Profile

```text
Profile ID
浏览器状态
账号绑定
代理绑定
登录态
时区
语言
User Agent
Cookie
Local Storage
```

核心原则：

> 浏览器环境是资源，不属于业务逻辑。

---

# 十四、07 Proxy 代理中心

代理池：

```text
Proxy
├── 类型
├── 地址
├── 端口
├── 地区
├── 供应商
├── 状态
├── 延迟
└── 当前绑定
```

关系：

```text
Account
 ↓
BrowserProfile
 ↓
Proxy
```

代理模块主要用于网络隔离和环境管理，不作为规避平台限制的工具。

---

# 十五、08 AI 中心

AI 中心不是简单配置 API Key。

应该有：

```text
Provider
Model
Router
Prompt
Context
Tool Calling
Cost
Usage
Fallback
```

支持：

```text
OpenAI
Anthropic
Gemini
Local/Ollama
其他兼容模型
```

## 15.1 Model Router

例如：

```text
简单分类 → 低成本模型
普通对话 → 标准模型
复杂策略 → 高能力模型
本地敏感任务 → Local Model
```

---

# 十六、09 Memory 记忆系统

分层：

```text
短期记忆
会话记忆
用户记忆
Persona记忆
事件记忆
长期记忆
```

例如：

```text
客户：张先生

长期：
东京
投资
预算3000万

近期：
准备看房

当前：
关注山手线附近项目
```

---

# 十七、10 Knowledge 知识中心

Knowledge 不等于 Memory。

Knowledge：

```text
公司
产品
行业
FAQ
案例
政策
培训资料
内部资料
销售资料
```

AI回复前组合：

```text
当前消息
+
Conversation
+
Memory
+
Knowledge
+
Persona
+
Strategy
```

再生成回复。

---

# 十八、11 Intent 意图引擎

AI实时判断：

```text
闲聊
咨询
好奇
询价
比较
犹豫
拒绝
投诉
兴趣
购买
求助
```

并生成：

```text
Intent Score
```

例如：

```text
购买意向       87
紧迫度         72
信任度         61
价格敏感       54
```

---

# 十九、12 Conversation State 对话状态

对话生命周期：

```text
陌生
↓
建立联系
↓
了解兴趣
↓
发现需求
↓
确认需求
↓
提供帮助
↓
产生兴趣
↓
行动
↓
成交
```

Agent 每次回复都知道自己处在哪个阶段。

---

# 二十、13 Strategy 策略系统

策略定义：

> “我应该如何完成目标？”

例如：

### 社交策略

```text
低销售
高互动
多倾听
```

### 咨询策略

```text
快速识别需求
提供信息
建立专业信任
```

### 转化策略

```text
识别意向
确认需求
给出下一步
```

---

# 二十一、14 Workflow 工作流

工作流是自动运行的逻辑。

基本结构：

```text
Trigger
↓
Condition
↓
Action
↓
Delay
↓
Branch
↓
Action
```

例：

```text
收到新消息
↓
AI分析
↓
判断用户意向
↓
高意向？
↓
读取记忆
↓
生成回复
↓
人工确认 / 按平台允许的自动流程执行
↓
发送
↓
等待
↓
重新分析
```

---

# 二十二、15 Scheduler 调度

支持：

```text
立即任务
定时任务
周期任务
事件触发
失败重试
优先级
队列
并发
暂停
恢复
```

架构：

```text
Scheduler
 ↓
Queue
 ↓
Worker
 ↓
Automation
```

---

# 二十三、16 Message 消息中心

这是使用频率最高的页面之一。

左：

```text
全部
待处理
AI处理
人工处理
高意向
异常
```

中：

```text
聊天
```

右：

```text
用户画像
Intent
Memory
标签
当前阶段
Agent
AI建议
下一步
```

核心能力：

```text
AI生成
重新生成
修改
人工接管
恢复AI
查看上下文
查看来源
查看客户历史
```

---

# 二十四、17 CRM / Lead 中心

Lead：

```text
客户
来源
平台
Agent
关键词
首次接触
意向评分
标签
当前阶段
最后联系
负责人
备注
```

客户漏斗：

```text
陌生
↓
潜客
↓
有效线索
↓
高意向
↓
商机
↓
成交
```

---

# 二十五、18 私域中心

这是本项目重要模块。

私域不是“微信号管理”。

而是：

> **客户进入长期经营阶段后的完整生命周期系统。**

包括：

```text
私域联系人
渠道
客户画像
客户标签
跟进
培育
内容
活动
会话
自动化
商机
成交
```

---

# 二十六、19 Customer 360

每个客户进入详情页以后：

```text
基本信息
↓
所有平台身份
↓
来源
↓
首次接触
↓
所有历史对话
↓
Memory
↓
Intent
↓
标签
↓
客户阶段
↓
私域状态
↓
商机
↓
订单
↓
下一步行动
```

例如：

```text
张先生

来源：
Instagram / 东京买房

平台账号：
@xxxxx

预算：
3000万

需求：
投资

意向：
92

当前阶段：
高意向

私域：
已建立

下一步：
安排咨询
```

---

# 二十七、20 Identity Resolution 身份统一

同一个人可能：

```text
X
Instagram
WhatsApp
LINE
Email
CRM
```

系统需要允许将多个平台身份归并到：

```text
Customer
```

最终实现：

> 一个客户，多平台身份。

---

# 二十八、21 内容中心

私域运营不能只聊天。

内容中心管理：

```text
文章
图片
视频
案例
FAQ
产品资料
活动
课程
资料包
```

支持：

```text
内容标签
适用客户阶段
适用行业
适用Persona
```

Agent 根据客户状态选择适合的内容。

---

# 二十九、22 Nurture 客户培育

例如：

```text
客户进入私域
↓
建立画像
↓
选择培育策略
↓
定期提供有价值内容
↓
客户行为变化
↓
重新评分
↓
高意向
↓
进入销售
```

目标不是无脑发送消息。

目标是：

> **在合适的时间给合适的人合适的信息。**

---

# 三十、23 Sales / Deal 商机中心

记录：

```text
商机
商品
服务
金额
报价
阶段
负责人
来源
预计成交
实际成交
```

漏斗：

```text
线索
↓
机会
↓
需求确认
↓
报价
↓
谈判
↓
成交
```

---

# 三十一、24 Analytics 数据中心

至少分析：

```text
平台效果
关键词效果
Agent效果
Persona效果
策略效果
AI模型效果
回复率
意向率
私域进入率
转化率
成交率
成本
ROI
```

---

# 三十二、25 Experiment 实验中心

支持：

```text
Persona A vs B
Strategy A vs B
Prompt A vs B
Model A vs B
```

指标：

```text
回复率
互动率
高意向率
私域进入率
转化率
成交
成本
```

最终让系统知道：

> 什么方法最有效。

---

# 三十三、26 Security 安全中心

系统处理大量敏感数据，因此必须单独设计。

包括：

```text
API Key
Cookie
账号凭据
代理
数据库
聊天记录
客户资料
```

要求：

```text
加密存储
权限控制
操作审计
敏感数据脱敏
导出
删除
备份
恢复
```

---

# 三十四、27 Audit / Logs

所有重要行为留下日志：

```text
谁
什么时候
哪个Agent
哪个账号
哪个平台
做了什么
结果是什么
是否成功
```

例如：

```text
Agent：东京房产顾问
Account：Account-02
Action：收到消息
AI：识别意向 87
Action：生成回复
Result：等待人工审核
```

---

# 三十五、28 Permission System

以后支持多个用户：

```text
Owner
Admin
Operator
Sales
Reviewer
Analyst
```

Agent 也有权限：

```text
Read
Generate
Send
Create Lead
Modify CRM
Execute Workflow
```

敏感操作可以：

```text
AI请求
↓
人工审批
↓
执行
```

---

# 三十六、29 Plugin / Adapter System

未来平台扩展必须插件化：

```text
Platform Plugin
Browser Plugin
AI Provider Plugin
Storage Plugin
CRM Plugin
Webhook Plugin
```

例如：

```text
platform-x/
platform-instagram/
browser-bitbrowser/
browser-adspower/
ai-openai/
ai-claude/
```

---

# 三十七、30 API 层

未来支持：

```text
REST API
Webhook
External Integration
```

其他软件可以：

```text
创建Lead
查询客户
获取消息
启动Workflow
获取统计
```

---

# 三十八、完整核心数据模型

建议至少存在以下核心实体：

```text
User
Workspace
Agent
Persona

Account
Platform
Channel

BrowserProfile
Proxy

AIProvider
AIModel
Prompt

Conversation
Message
Participant

Customer
CustomerIdentity
CustomerMemory

KnowledgeBase
KnowledgeDocument

Intent
Strategy
Goal

Lead
LeadScore
LeadTag

Workflow
WorkflowNode
WorkflowExecution

Task
Job
Scheduler

Content
Campaign
NurturePlan

Deal
Order

AnalyticsEvent
Experiment

AuditLog
SystemLog
```

---

# 三十九、核心关系

```text
Workspace
   │
   ├── Agent
   │     │
   │     ├── Persona
   │     ├── Strategy
   │     ├── Knowledge
   │     ├── Memory
   │     ├── Workflow
   │     └── Accounts
   │
   ├── Accounts
   │      │
   │      ├── Platform
   │      ├── BrowserProfile
   │      └── Proxy
   │
   └── Customers
          │
          ├── Identities
          ├── Conversations
          ├── Messages
          ├── Memory
          ├── Leads
          ├── Deals
          └── Activities
```

---

# 四十、完整业务闭环

最终系统最重要的一条链：

```text
                    公域
                     │
                     ↓
              Discover Agent
                     │
                     ↓
                内容发现
                     │
                     ↓
                AI筛选
                     │
                     ↓
               Intent Engine
                     │
                     ↓
              Qualification
                     │
                     ↓
              Engagement Agent
                     │
                     ↓
                 对话
                     │
                     ↓
                Customer
                     │
                     ↓
                 CRM
                     │
                     ↓
              Private Domain
                     │
                     ↓
              Nurture Agent
                     │
                     ↓
                 商机
                     │
                     ↓
               Sales Agent
                     │
                     ↓
                  成交
                     │
                     ↓
                Analytics
                     │
                     ↓
             Experiment / Optimize
                     │
                     └──────→ 反哺 Agent
```

---

# 四十一、Agent 决策链

每次产生动作之前：

```text
收到事件
 ↓
读取平台
 ↓
读取账号
 ↓
读取Persona
 ↓
读取Conversation
 ↓
读取Customer Memory
 ↓
读取Knowledge
 ↓
判断Intent
 ↓
判断Conversation State
 ↓
读取Strategy
 ↓
判断Goal
 ↓
选择Action
 ↓
生成内容
 ↓
风险 / 权限检查
 ↓
人工审批或执行
 ↓
记录结果
 ↓
更新Memory
```

这才是整个系统最核心的“智能循环”。

---

# 四十二、V1.0 第一阶段开发范围

虽然设计书完整，但实际开发绝对不要一次做完。

## Phase 0：桌面壳

实现：

```text
Tauri
Vue
导航
主题
基础设置
```

页面先全部可点击。

---

## Phase 1：基础资源

实现：

```text
Workspace
Agent
Persona
Account
Platform
BitBrowser
Proxy
```

这阶段先解决：

> 软件到底能不能管理这些资源。

---

## Phase 2：AI

实现：

```text
AI Provider
Model
Prompt
Persona
Conversation
AI Generate
```

实现第一个真正可见的：

> “像这个人说话。”

---

## Phase 3：消息

实现：

```text
Conversation
Message
AI Reply
Memory
Intent
```

做到：

> 收到消息 → AI理解 → 生成回复建议。

---

## Phase 4：自动化

实现：

```text
Scheduler
Task
Workflow
Worker
BitBrowser
Playwright
```

先实现**一条真实、可控制的工作流**。

---

## Phase 5：CRM

实现：

```text
Customer
Lead
Tags
Pipeline
Customer 360
```

---

## Phase 6：私域

实现：

```text
Private Domain
Nurture
Content
Follow-up
Deal
```

---

## Phase 7：数据

实现：

```text
Dashboard
Analytics
Conversion
ROI
Experiment
```

---

# 四十三、V1.0 第一阶段建议只支持一个平台

不要一次做：

```text
X
Instagram
TikTok
Facebook
Reddit
YouTube
Telegram
WhatsApp
LINE
```

第一阶段：

```text
一个平台
+
BitBrowser
+
3个账号
+
一个Agent
+
一个获客场景
```

先真正跑通。

---

# 四十四、V1.0 “成功标准”

不是代码写了多少。

而是：

```text
1. 软件可以正常安装
2. Agent可以创建
3. Persona可以创建
4. BitBrowser账号可以连接
5. 账号可以执行任务
6. 收到消息后能够进入系统
7. AI能够读取上下文
8. AI能够读取Memory
9. AI能够模仿Persona生成回复
10. Intent能够判断
11. 用户可以人工接管
12. Customer能够自动创建
13. Lead能够自动创建
14. 客户能够进入CRM
15. 能够看到完整对话
16. 能够查看客户来源
17. 能够查看客户阶段
18. 能够执行至少一个Workflow
19. 能看到完整数据统计
```

做到这里，产品才算真正进入 MVP。

---

# 四十五、安全与平台合规原则

第一版必须把下面原则写进工程规则：

```text
1. 不绕过平台验证码
2. 不破解平台安全机制
3. 不设计规避封禁 / 风控的逻辑
4. 不进行无差别垃圾群发
5. 不伪造身份进行欺诈
6. 明确自动化边界
7. 支持人工接管
8. 支持停止自动化
9. 保存完整操作日志
10. 遵循具体平台的自动化政策
```

对于不同平台：

```text
优先官方 API
↓
允许的自动化接口
↓
浏览器自动化
```

而不是反过来。

---

# 四十六、产品最重要的四个核心

从整个设计书里真正提炼出来，其实只有：

## 第一核心：Agent

```text
谁在工作？
```

## 第二核心：Memory

```text
它记得什么？
```

## 第三核心：Strategy

```text
它为什么这么做？
```

## 第四核心：Workflow

```text
它怎么持续执行？
```

浏览器、代理、账号、平台都只是：

> **Agent 的执行资源。**

---

# 四十七、最终产品定位

最终不要宣传：

> 自动点赞、自动关注、自动私信。

而应该定位成：

> **AI Agent 驱动的全链路获客与客户经营平台。**

能力链：

```text
发现客户
↓
理解客户
↓
建立关系
↓
智能对话
↓
判断需求
↓
客户沉淀
↓
进入私域
↓
持续经营
↓
商机转化
↓
成交
↓
数据分析
↓
持续优化
```

这才是我们这整个项目真正应该建设的东西。

---

# 四十八、第一版产品结构最终确认

```text
AI Agent Platform
│
├── 工作台
│
├── Agent
│   ├── Agent管理
│   ├── Persona
│   ├── Memory
│   ├── Knowledge
│   ├── Strategy
│   └── Goal
│
├── 获客
│   ├── Platform
│   ├── Account
│   ├── BitBrowser
│   ├── Proxy
│   ├── Campaign
│   └── Discovery
│
├── 对话
│   ├── Inbox
│   ├── Conversation
│   ├── AI Reply
│   ├── Human Takeover
│   └── Intent
│
├── CRM
│   ├── Customers
│   ├── Leads
│   ├── Tags
│   ├── Pipeline
│   └── Customer 360
│
├── 私域
│   ├── Contacts
│   ├── Nurture
│   ├── Content
│   ├── Follow-up
│   ├── Campaign
│   └── Deal
│
├── 自动化
│   ├── Workflow
│   ├── Scheduler
│   ├── Task
│   ├── Queue
│   └── Execution
│
├── AI
│   ├── Providers
│   ├── Models
│   ├── Prompts
│   ├── Agents
│   └── Usage
│
├── 数据
│   ├── Dashboard
│   ├── Analytics
│   ├── ROI
│   └── Experiments
│
└── 系统
    ├── Security
    ├── Permissions
    ├── Logs
    ├── Backup
    ├── API
    └── Plugins
```

---

# 四十九、项目第一条工程原则

整个项目以后所有开发，都应该遵守：

> **业务逻辑与平台逻辑分离，Agent 与执行器分离，资源与任务分离，AI 与平台分离。**

例如：

```text
Agent
  ↓
Decision
  ↓
Action
  ↓
Platform Adapter
  ↓
Browser Provider
  ↓
BitBrowser
  ↓
Playwright
```

而不是：

```text
“如果是 X，就打开 BitBrowser，然后点击某个按钮……”
```

前一种架构才能真正长期发展。

---

# 五十、项目最终愿景

第一阶段：

> **Windows AI 获客软件**

第二阶段：

> **AI Agent + CRM + 私域运营**

第三阶段：

> **多平台 Agent Platform**

第四阶段：

> **AI 数字员工平台**

最终：

```text
            AI Agent OS
                 │
      ┌──────────┼──────────┐
      │          │          │
     获客        客服       销售
      │          │          │
      └──────────┼──────────┘
                 │
             客户经营
                 │
              成交
```

最终用户购买的不是：

> “一个自动点击程序。”

而是：

> **“一个能够替我持续发现客户、理解客户、和客户沟通、管理客户并推动业务的 AI 数字员工系统。”**