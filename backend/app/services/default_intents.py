"""Default intent schemas for the system"""
from datetime import datetime
from typing import List, Dict, Any


# ========== Intent Type Definitions ==========
# These are the 10+ predefined intent types required by acceptance criteria

INTENT_TYPES: Dict[str, Dict[str, Any]] = {
    "greeting": {
        "intent_type": "greeting",
        "intent_name": "问候",
        "description": "用户打招呼或问候",
        "keywords": ["你好", "您好", "早上好", "晚上好", "嗨", "hello", "hi", "hey", "在吗"],
        "category": "social",
        "priority": 10,
        "pattern_weight": 2.0,  # 高权重用于精确匹配
    },
    "question": {
        "intent_type": "question",
        "intent_name": "提问",
        "description": "用户提出问题或寻求信息",
        "keywords": ["是什么", "怎么做", "为什么", "如何", "怎样", "什么", "哪里", "多少", "?"],
        "category": "inquiry",
        "priority": 9,
    },
    "command": {
        "intent_type": "command",
        "intent_name": "指令",
        "description": "用户下达明确指令",
        "keywords": ["帮我", "请", "执行", "创建", "删除", "修改", "更新", "查找"],
        "category": "action",
        "priority": 8,
    },
    "complaint": {
        "intent_type": "complaint",
        "intent_name": "投诉",
        "description": "用户表达不满或投诉",
        "keywords": ["投诉", "不满意", "太差", "失望", "糟糕", "bug", "错误"],
        "category": "feedback",
        "priority": 7,
        "pattern_weight": 2.0,
    },
    "thanks": {
        "intent_type": "thanks",
        "intent_name": "感谢",
        "description": "用户表达感谢",
        "keywords": ["谢谢", "感谢", "多谢", "辛苦了", "费心了"],
        "category": "social",
        "priority": 6,
    },
    "farewell": {
        "intent_type": "farewell",
        "intent_name": "告别",
        "description": "用户结束对话",
        "keywords": ["再见", "拜拜", "下次见", "告辞", "bye", "goodbye"],
        "category": "social",
        "priority": 5,
    },
    "clarification": {
        "intent_type": "clarification",
        "intent_name": "澄清",
        "description": "用户要求澄清或确认信息",
        "keywords": ["确认", "确定", "是不是", "对吗", "意思是", "解释一下", "再说一遍"],
        "category": "inquiry",
        "priority": 8,
        "pattern_weight": 2.0,
    },
    "escalation": {
        "intent_type": "escalation",
        "intent_name": "升级",
        "description": "用户要求转接人工或升级处理",
        "keywords": ["人工", "客服", "升级", "主管", "负责人", "真人"],
        "category": "action",
        "priority": 9,
        "pattern_weight": 2.5,
    },
    "callback_request": {
        "intent_type": "callback_request",
        "intent_name": "回电请求",
        "description": "用户请求回电或联系",
        "keywords": ["回电", "打电话", "联系我", "联系我", "方便时"],
        "category": "action",
        "priority": 7,
    },
    "follow_up": {
        "intent_type": "follow_up",
        "intent_name": "跟进",
        "description": "用户跟进之前的话题或查询",
        "keywords": ["之前", "刚才", "再说", "继续", "接着", "补充"],
        "category": "inquiry",
        "priority": 6,
    },
    "feedback": {
        "intent_type": "feedback",
        "intent_name": "反馈",
        "description": "用户提供建议或反馈",
        "keywords": ["建议", "意见", "反馈", "改进", "希望", "应该"],
        "category": "feedback",
        "priority": 5,
    },
    "task_completion": {
        "intent_type": "task_completion",
        "intent_name": "任务完成",
        "description": "用户确认任务完成",
        "keywords": ["好了", "完成", "可以了", "没问题", "搞定"],
        "category": "action",
        "priority": 4,
        "pattern_weight": 2.0,
    },
}


# ========== Intent to Action Mapping ==========
# Maps each intent type to appropriate actions

INTENT_ACTION_MAP: Dict[str, Dict[str, Any]] = {
    "greeting": {
        "action_type": "respond_greeting",
        "response_template": "您好！有什么我可以帮您的吗？",
        "requires_action": False,
    },
    "question": {
        "action_type": "answer_question",
        "response_template": "我来为您解答...",
        "requires_action": True,
        "action_params": {
            "search_knowledge_base": True,
            "provide_citations": True,
        },
    },
    "command": {
        "action_type": "execute_command",
        "response_template": "正在为您执行操作...",
        "requires_action": True,
        "action_params": {
            "validate_permissions": True,
            "log_execution": True,
        },
    },
    "complaint": {
        "action_type": "handle_complaint",
        "response_template": "很抱歉给您带来不便，我来帮您处理...",
        "requires_action": True,
        "action_params": {
            "escalate_to_human": True,
            "create_ticket": True,
            "priority": "high",
        },
    },
    "thanks": {
        "action_type": "acknowledge_thanks",
        "response_template": "不客气！还有其他问题吗？",
        "requires_action": False,
    },
    "farewell": {
        "action_type": "respond_farewell",
        "response_template": "再见！祝您有美好的一天！",
        "requires_action": False,
    },
    "clarification": {
        "action_type": "provide_clarification",
        "response_template": "让我为您详细说明...",
        "requires_action": True,
        "action_params": {
            "provide_examples": True,
            "break_down_steps": True,
        },
    },
    "escalation": {
        "action_type": "escalate",
        "response_template": "我理解您的需求，正在为您转接人工客服...",
        "requires_action": True,
        "action_params": {
            "transfer_to_human": True,
            "notify_supervisor": True,
            "priority": "urgent",
        },
    },
    "callback_request": {
        "action_type": "schedule_callback",
        "response_template": "好的，我会安排回电。请问什么时间方便？",
        "requires_action": True,
        "action_params": {
            "schedule_callback": True,
            "collect_phone": True,
        },
    },
    "follow_up": {
        "action_type": "continue_conversation",
        "response_template": "好的，我们继续之前的话题...",
        "requires_action": True,
        "action_params": {
            "retrieve_context": True,
            "continue_thread": True,
        },
    },
    "feedback": {
        "action_type": "collect_feedback",
        "response_template": "感谢您的反馈！我们会认真考虑...",
        "requires_action": True,
        "action_params": {
            "save_feedback": True,
            "send_thank_you": True,
        },
    },
    "task_completion": {
        "action_type": "confirm_completion",
        "response_template": "好的，任务已完成！还有其他需要帮助的吗？",
        "requires_action": False,
    },
}


# ========== Default Templates ==========

INTENT_CLASSIFICATION_PROMPT_TEMPLATE = """
你是一个专业的意图识别助手。请分析以下用户消息，识别其意图类型。

## 可选意图类型
{intent_types}

## 用户消息
"{user_message}"

## 对话上下文
{conversation_context}

## 之前的意图记录
{previous_intents}

## 输出格式
请以JSON格式返回：
{{
  "intent_type": "意图类型",
  "intent_name": "意图名称",
  "confidence": 0.xx,
  "entities": {{}},
  "explanation": "简要说明判断理由"
}}
"""


# ========== Default Intent Types List ==========

DEFAULT_INTENT_TYPES_LIST = [
    {**t, "id": None, "created_at": None, "updated_at": None, "usage_count": 0}
    for t in INTENT_TYPES.values()
]
