"""Default prompt templates for the system"""
from uuid import uuid4


SYSTEM_PROMPT_TEMPLATE = {
    "id": "system-default",
    "name": "系统提示词模板",
    "description": "默认系统提示词，定义AI助手的基本行为和角色",
    "content": """你是一个专业的AI助手。你的任务是帮助用户解决问题、提供信息和完成任务。

## 基本原则
- 保持专业、友好和耐心的态度
- 提供准确、有用的信息
- 当不确定时，诚实地说明
- 尊重用户隐私和安全

## 能力范围
- 回答问题和分析问题
- 协助代码编写和调试
- 提供建议和解决方案
- 处理日常任务和查询

## 限制
- 不提供医疗、法律或财务建议
- 不生成有害或不当内容
- 不泄露敏感信息

## 输出格式
- 使用清晰的组织结构
- 适当使用列表和分段
- 代码块使用正确的语法高亮
- 重要信息加以强调""",
    "template_type": "system",
    "category": "system",
    "variables": [
        {"name": "user_context", "description": "用户上下文信息", "default": ""},
        {"name": "task_description", "description": "任务描述", "default": ""},
    ],
    "is_baseline": True,
}


GREETING_TEMPLATE = {
    "id": "greeting-default",
    "name": "开场白模板",
    "description": "对话开始时的问候语模板",
    "content": """你好，{{user_name}}！👋

我是你的AI助手 {{assistant_name}}，很高兴为你服务！

## 我可以帮助你：
- 回答各类问题
- 协助完成工作任务
- 提供专业建议
- 处理日常事务

有什么我可以帮你的吗？""",
    "template_type": "greeting",
    "category": "conversation",
    "variables": [
        {"name": "user_name", "description": "用户名称"},
        {"name": "assistant_name", "description": "助手名称"},
    ],
    "is_baseline": True,
}


CONVERSATION_TEMPLATE = {
    "id": "conversation-default",
    "name": "对话模板",
    "description": "标准对话流程模板",
    "content": """## 当前对话上下文
{{context}}

## 用户问题
{{question}}

## 助手回应
""",
    "template_type": "conversation",
    "category": "dialogue",
    "variables": [
        {"name": "context", "description": "对话上下文"},
        {"name": "question", "description": "用户问题"},
    ],
    "is_baseline": True,
}


CODE_REVIEW_TEMPLATE = {
    "id": "code-review-default",
    "name": "代码审查模板",
    "description": "用于代码审查的标准模板",
    "content": """## 代码审查请求

### 文件
{{file_path}}

### 变更摘要
{{change_summary}}

### 审查要点
1. **代码质量**: 检查代码可读性和维护性
2. **性能**: 识别潜在的性能问题
3. **安全性**: 检查安全漏洞
4. **最佳实践**: 是否符合团队规范

### 发现的问题

| 级别 | 位置 | 描述 |
|------|------|------|
{{issues_table}}

### 总体评价
{{overall_assessment}}

### 建议
{{suggestions}}""",
    "template_type": "custom",
    "category": "development",
    "variables": [
        {"name": "file_path", "description": "文件路径"},
        {"name": "change_summary", "description": "变更摘要"},
        {"name": "issues_table", "description": "问题表格"},
        {"name": "overall_assessment", "description": "总体评价"},
        {"name": "suggestions", "description": "建议"},
    ],
    "is_baseline": True,
}


DOCUMENTATION_TEMPLATE = {
    "id": "documentation-default",
    "name": "文档模板",
    "description": "用于生成技术文档的模板",
    "content": """# {{document_title}}

## 概述
{{overview}}

## 功能特性
{{features}}

## 使用方法
\`\`\`{{language}}
{{code_example}}
\`\`\`

## API 参考
{{api_reference}}

## 常见问题
{{faq}}

## 更新日志
{{changelog}}""",
    "template_type": "custom",
    "category": "documentation",
    "variables": [
        {"name": "document_title", "description": "文档标题"},
        {"name": "overview", "description": "概述"},
        {"name": "features", "description": "功能特性"},
        {"name": "language", "description": "代码语言"},
        {"name": "code_example", "description": "代码示例"},
        {"name": "api_reference", "description": "API参考"},
        {"name": "faq", "description": "常见问题"},
        {"name": "changelog", "description": "更新日志"},
    ],
    "is_baseline": True,
}


DEFAULT_TEMPLATES = [
    SYSTEM_PROMPT_TEMPLATE,
    GREETING_TEMPLATE,
    CONVERSATION_TEMPLATE,
    CODE_REVIEW_TEMPLATE,
    DOCUMENTATION_TEMPLATE,
]


def get_default_templates() -> list:
    """Get all default templates"""
    return DEFAULT_TEMPLATES
