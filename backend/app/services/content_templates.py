"""Deterministic Nurture Content Templates.

The template half of the AI content generator: a pure, offline-testable function
that turns a customer context (segment / lifecycle stage / tags / persona /
objective / channel) into a personalized content piece. This is the safe,
deterministic path used when no LLM provider is wired in (mirrors the
DecisionEngine "rule_based" path) — so the generation API always returns usable
content, and quality remains reproducible.

Design principles:
- Pure Python: no DB / LLM / external deps; fully testable offline.
- Explainable: the same input always yields the same output.
- Persona-aware: layers the persona / customer name and segment context in.
- Channel-aware: adjusts formatting (plain text vs rich) per channel.
"""
from typing import Optional, List, Dict, Any
import re

# Per-objective template specs. Each defines a title, a body (with placeholders),
# and a call-to-action. Placeholders: {name} {segment} {stage} {product} {cta}
OBJECTIVE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "welcome": {
        "title": "欢迎加入 {product}，你的专属指南来了",
        "body": (
            "{greeting}\n\n"
            "很高兴认识你{name}！{segment_intro}\n\n"
            "作为「{product}」的新伙伴，这里有一份为你准备的入门指南，"
            "帮你快速上手、解锁核心功能。"
        ),
        "cta": "点击这里开始你的第一步 →",
        "tags": ["welcome", "onboarding", "指南"],
    },
    "nurture": {
        "title": "为你精选：{product} 进阶干货",
        "body": (
            "{greeting}\n\n"
            "看到你最近很活跃{name}，我们特意为你整理了一批{segment_intro}进阶内容，"
            "从技巧到案例，帮你用得更顺手。"
        ),
        "cta": "查看精选内容 →",
        "tags": ["nurture", "干货", "进阶"],
    },
    "reactivation": {
        "title": "{product} 回来了，好久不见{name}",
        "body": (
            "{greeting}\n\n"
            "好久不见{name}！我们也很想念你。{segment_intro}这段时间我们上线了不少新功能，"
            "特别为「{stage}」阶段的你优化了体验。"
        ),
        "cta": "立即回归，看看有什么不同 →",
        "tags": ["reactivation", "召回", "回归"],
    },
    "cross_sell": {
        "title": "搭配套餐：让{product}更给力",
        "body": (
            "{greeting}\n\n"
            "根据你近期的使用情况{name}，我们为你搭配了{segment_intro}专属升级方案，"
            "补齐短板、一步到位。"
        ),
        "cta": "查看专属搭配方案 →",
        "tags": ["cross_sell", "搭配", "升级"],
    },
    "support": {
        "title": "{product} 专属支持，随时为你解答",
        "body": (
            "{greeting}\n\n"
            "使用中遇到任何问题{name}，都可以找我们。{segment_intro}专属客服已就位，"
            "帮你快速解决。"
        ),
        "cta": "联系专属支持 →",
        "tags": ["support", "客服", "帮助"],
    },
}

# Generic fallback when objective is None / unknown.
_DEFAULT_TEMPLATE: Dict[str, Any] = {
    "title": "{product}：为你准备了一份新内容",
    "body": "{greeting}\n\n{name}，这里有一条为你精选的内容。{segment_intro}",
    "cta": "点击查看详情 →",
    "tags": ["nurture", "更新"],
}


def _segment_intro(segment_name: Optional[str]) -> str:
    """A short clause that folds the segment context into the copy."""
    if segment_name:
        return f"面向「{segment_name}」的"
    return ""


def _greeting(tone: Optional[str], persona_name: Optional[str]) -> str:
    """Opening greeting, tone- and persona-aware."""
    who = f"{persona_name}：" if persona_name else ""
    if tone == "professional":
        return f"{who}您好！"
    if tone == "playful":
        return f"{who}嗨～"
    # warm (default)
    return f"{who}你好！"


def _render_cta(include_cta: bool, cta: str) -> str:
    """Append the call-to-action on its own line when requested."""
    return cta if include_cta else ""


def generate_template_content(
    *,
    content_type: str = "text",
    objective: Optional[str] = None,
    persona_name: Optional[str] = None,
    segment_name: Optional[str] = None,
    stage_name: Optional[str] = None,
    customer_name: Optional[str] = None,
    customer_tags: Optional[List[str]] = None,
    tone: Optional[str] = None,
    channel: Optional[str] = None,
    product: str = "产品",
    include_cta: bool = True,
    extra_tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Render a personalized content piece from the customer context.

    Returns a dict with title, body, summary, tags, objective — ready to be
    persisted as a ContentItem or returned directly.
    """
    template = OBJECTIVE_TEMPLATES.get(objective or "", _DEFAULT_TEMPLATE)

    # Personalized name slot: use customer name, degrade gracefully.
    name = customer_name or "用户"

    # Stage: prefer explicit name, else code, else a neutral phrase.
    stage = stage_name or (objective or "通用")

    greeting = _greeting(tone, persona_name)
    seg_intro = _segment_intro(segment_name)

    title = template["title"].format(
        name=name, segment=segment_name or "", stage=stage, product=product
    )
    body = template["body"].format(
        name=name,
        segment=segment_name or "",
        stage=stage,
        product=product,
        greeting=greeting,
        segment_intro=seg_intro,
    )
    cta_line = _render_cta(include_cta, template["cta"])
    full_body = f"{body}\n\n{cta_line}" if cta_line else body

    # Summary: first ~60 chars of the body, trimmed at a sentence boundary.
    first_sentence = re.split(r"[。！!]", body.strip(), maxsplit=1)[0]
    summary = first_sentence[:60]

    # Tags: template base tags + customer tags + optional extra, deduped.
    base_tags = list(template["tags"])
    merged: List[str] = []
    seen = set()
    for t in base_tags + (customer_tags or []) + (extra_tags or []) + ([objective] if objective else []):
        key = t.lower()
        if t and key not in seen:
            seen.add(key)
            merged.append(t)

    # HTML channel: wrap in a minimal structure; others stay plain text.
    if content_type == "html":
        rendered_body = (
            f"<p>{body}</p>" + (f"<p>{cta_line}</p>" if cta_line else "")
        )
    else:
        rendered_body = full_body

    return {
        "title": title,
        "body": rendered_body,
        "summary": summary,
        "content_type": content_type,
        "tags": merged,
        "objective": objective,
        "channel": channel,
        "persona_name": persona_name,
        "customer_name": customer_name,
    }
