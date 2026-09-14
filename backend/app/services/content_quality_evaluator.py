"""Content Quality Evaluator - deterministic quality + relevance scoring.

Mirrors the ResponseValidator idiom (Phase 2): pure Python, no LLM, fully
testable offline, explainable. Scores a generated content piece against its
intended context across five dimensions and produces an overall 0-5 score plus
a pass/fail verdict against a configurable threshold.

Dimensions (each 0.0-1.0, weighted into a 0-5 overall):
    relevance        - does the content address the objective / segment / stage?
    personalization  - does it reference the customer's name / tags / segment?
    completeness     - is it complete enough (title + body + CTA when asked)?
    consistency      - is the title coherent with the body?
    safety           - does it avoid fabricated / harmful claims?

Design principles:
- No LLM dependency, deterministic and fully testable offline.
- Explainable: each dimension carries a score; overall is a fixed weighted sum.
- Threshold-configurable: callers tighten/loosen the pass bar.
"""
import re
from typing import Dict, List, Any, Optional

from app.schemas.content_generation import ContentEvaluationRequest, QualityEvaluation


class ContentQualityEvaluator:
    """Deterministic quality + relevance validator for generated content."""

    DIMENSION_WEIGHTS: Dict[str, float] = {
        "relevance": 0.30,
        "personalization": 0.20,
        "completeness": 0.25,
        "consistency": 0.10,
        "safety": 0.15,
    }

    DEFAULT_THRESHOLD = 4.0

    # Patterns that indicate a fabricated / unverifiable claim.
    HALLUCINATION_PATTERNS: List[str] = [
        r"我(已经|刚才|已)\s*为您\s*(创建|删除|修改|发送|退款|办理|预约|执行)",
        r"(已|刚)(为您|帮你|帮您)(创建|删除|修改|发送|退款|办理)",
        r"100%\s*(保证|成功|有效|提升)",
        r"据(统计|数据显示)\s*\d+\s*(万|亿|%?)\s*增长",
    ]

    # Objective keywords that, when present in the content, signal relevance.
    OBJECTIVE_KEYWORDS: Dict[str, List[str]] = {
        "welcome": ["欢迎", "wel", "新", "第一次", "开始", "开启", "guide", "onboard"],
        "reactivation": ["回归", "回来", "久违", "好久", "重新", "再次", "welcome back", "miss you", "回来"],
        "nurture": ["干货", "指南", "技巧", "价值", "成长", "进阶", "案例", "更新"],
        "cross_sell": ["搭配", "推荐", "升级", "加购", "优惠", "专属", "搭配", "bundle", "upgrad"],
        "support": ["帮助", "支持", "客服", "解答", "问题", "联系", "help", "support"],
    }

    CTA_MARKERS: List[str] = [
        "点击", "立即", "马上", "扫码", "回复", "领取", "查看", "报名",
        "了解更多", "预约", "开始", "get started", "click", "sign up", "learn more",
    ]

    # ---------- Public API ----------

    def evaluate(self, request: ContentEvaluationRequest) -> QualityEvaluation:
        """Score the content against its intended context."""
        body = (request.content or "").strip()

        relevance = self._score_relevance(request, body)
        personalization = self._score_personalization(request, body)
        completeness = self._score_completeness(request, body)
        consistency = self._score_consistency(request.title, body)
        safety = self._score_safety(body)

        dimensions = {
            "relevance": round(relevance, 3),
            "personalization": round(personalization, 3),
            "completeness": round(completeness, 3),
            "consistency": round(consistency, 3),
            "safety": round(safety, 3),
        }

        overall = self._compute_overall({
            "relevance": relevance,
            "personalization": personalization,
            "completeness": completeness,
            "consistency": consistency,
            "safety": safety,
        })

        issues = self._collect_issues(request, body, dimensions)
        passed = overall >= self.DEFAULT_THRESHOLD and dimensions["safety"] >= 0.5

        return QualityEvaluation(
            score=round(overall, 2),
            passed=passed,
            threshold=self.DEFAULT_THRESHOLD,
            dimensions=dimensions,
            issues=issues,
        )

    # ---------- Dimension scorers (each 0.0-1.0) ----------

    def _score_relevance(self, req: ContentEvaluationRequest, body: str) -> float:
        """Does the content address the objective / segment / stage?"""
        if not body:
            return 0.0
        lowered = body.lower()
        score = 0.5  # a non-empty piece is at least minimally relevant
        objective = (req.objective or "").lower()
        if objective:
            keywords = self.OBJECTIVE_KEYWORDS.get(objective, [])
            if keywords and any(k.lower() in lowered for k in keywords):
                score = 1.0
            else:
                score = 0.4  # objective declared but content doesn't signal it
        # A segment or stage narrows the intent; content that acknowledges it is
        # more relevant. Absent context → neutral, no penalty.
        if req.segment_name and req.segment_name.lower() in lowered:
            score = min(1.0, score + 0.1)
        return min(1.0, score)

    def _score_personalization(self, req: ContentEvaluationRequest, body: str) -> float:
        """Does the content use the customer's name / declared tags / segment?"""
        if not body:
            return 0.0
        lowered = body.lower()
        # No personalization context at all → neutral full score (nothing to check).
        has_context = bool(req.persona_name or req.expected_tags or req.segment_name)
        if not has_context:
            return 1.0

        matched = 0
        if req.persona_name and req.persona_name in body:
            matched += 1
        if req.expected_tags:
            hit = sum(1 for t in req.expected_tags if t.lower() in lowered)
            if hit:
                matched += 1
        if req.segment_name and req.segment_name.lower() in lowered:
            matched += 1
        total = sum(
            1 for c in (req.persona_name, req.expected_tags, req.segment_name) if c
        )
        return (matched / total) if total else 1.0

    def _score_completeness(self, req: ContentEvaluationRequest, body: str) -> float:
        """Is it complete enough (length, CTA when a CTA is expected)?"""
        if not body:
            return 0.0
        if len(body) < 8:
            return 0.3
        score = 1.0
        # Content bounded by max_length → not over-long.
        if len(body) > req.max_length:
            score -= 0.2
        # CTA expectation: for most nurture content a call-to-action is expected.
        # Absent one, mild penalty; present one, no penalty.
        has_cta = any(m.lower() in body.lower() for m in self.CTA_MARKERS)
        if not has_cta:
            score -= 0.2
        return max(0.0, min(1.0, score))

    def _score_consistency(self, title: Optional[str], body: str) -> float:
        """Is the title coherent with the body?"""
        if not title or not body:
            # No title to check → neutral.
            return 1.0
        title_tokens = self._tokenize(title)
        body_tokens = self._tokenize(body)
        if not title_tokens or not body_tokens:
            return 0.8
        overlap = sum(1 for t in title_tokens if t in body_tokens)
        # A title that shares some terms with the body is coherent.
        ratio = overlap / len(title_tokens)
        return max(0.4, min(1.0, 0.4 + ratio))

    def _score_safety(self, body: str) -> float:
        """Does it avoid fabrication / harmful content?"""
        if not body:
            return 1.0
        score = 1.0
        for pattern in self.HALLUCINATION_PATTERNS:
            if re.search(pattern, body):
                score -= 0.4
        lowered = body.lower()
        for bad in ["滚", "去死", "废物", "stupid", "shut up"]:
            if bad in lowered:
                score -= 0.5
        return max(0.0, min(1.0, score))

    # ---------- Helpers ----------

    def _compute_overall(self, scores: Dict[str, float]) -> float:
        total = sum(self.DIMENSION_WEIGHTS.get(k, 0.0) * scores.get(k, 0.0) for k in scores)
        return total * 5.0

    def _collect_issues(self, req, body: str, dims: Dict[str, float]) -> List[str]:
        issues: List[str] = []
        if not body:
            issues.append("content body is empty")
        if dims.get("completeness", 1.0) < 0.5:
            issues.append("content appears incomplete or missing a call-to-action")
        if dims.get("relevance", 1.0) < 0.4:
            issues.append("content may not match the declared objective")
        if dims.get("personalization", 1.0) < 0.5:
            issues.append("content does not reference the customer's personalization context")
        if dims.get("safety", 1.0) < 0.5:
            issues.append("content may contain unverifiable or unsafe claims")
        return issues

    def _tokenize(self, text: str) -> set:
        """Cheap bilingual token set (latin words + CJK bigrams/chars)."""
        tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
        cjk = re.findall(r"[\u4e00-\u9fff]", text)
        for i in range(len(cjk) - 1):
            tokens.add(cjk[i] + cjk[i + 1])
        for ch in cjk:
            tokens.add(ch)
        return tokens
