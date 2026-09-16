"""Response Validator - Quality Check on AI Responses

Scores a generated response across five dimensions and produces an overall
0-5 quality score. A response "passes" when its overall score is at or above
the configured threshold (default 4.0).

Design principles:
- Pure Python: no LLM dependency, deterministic and fully testable offline.
- Explainable: each dimension carries its own score + human-readable reason.
- Threshold-configurable: callers can tighten/loosen the pass bar.

Dimensions (each 0-1, weighted into a 0-5 overall):
    relevance     — does the response address the user's message?
    persona_fit   — does the response honor the persona's style?
    tone          — is the tone appropriate and safe?
    completeness  — is it complete enough (not truncated/empty)?
    safety        — does it avoid fabrication or harmful content?
"""
import logging
import re
from typing import List, Dict, Any, Optional

from app.schemas.decision import (
    ValidationRequest,
    ValidationResponse,
    ValidationDimension,
)

logger = logging.getLogger(__name__)


class ResponseValidator:
    """Deterministic quality validator for AI responses."""

    # Dimension weights that sum to 1.0; overall score = Σ(weight * dim) * 5.
    DIMENSION_WEIGHTS: Dict[str, float] = {
        "relevance": 0.30,
        "persona_fit": 0.20,
        "tone": 0.20,
        "completeness": 0.20,
        "safety": 0.10,
    }

    DEFAULT_THRESHOLD = 4.0
    MAX_LENGTH = 500
    MIN_USEFUL_LENGTH = 8

    # Patterns that indicate a fabricated / hallucinated answer — these push the
    # safety score down and flag the response.
    HALLUCINATION_PATTERNS: List[str] = [
        # Unverifiable "I have already done X for you" claims (no trailing space needed).
        r"我(已经|刚才|已)\s*为您\s*(创建|删除|修改|发送|退款|办理|预约|执行)",
        r"(已|刚)(为您|帮你|帮您)(创建|删除|修改|发送|退款|办理)",
        r"据(我|统计|数据显示)\s*20\d\d\s*年",  # invented statistics
    ]

    # Patterns that indicate a response is unacceptably vague/empty.
    VAGUE_PATTERNS: List[str] = [
        r"^(好的|嗯|ok|okay|谢谢)[。！!]?$",
        r"^(我(不|没)知道)[。！!]?$",
    ]

    def __init__(self, threshold: Optional[float] = None):
        self.threshold = threshold if threshold is not None else self.DEFAULT_THRESHOLD

    def validate(self, request: ValidationRequest) -> ValidationResponse:
        """Score the response against the user message + persona context."""
        text = (request.response_text or "").strip()

        relevance = self._score_relevance(request.user_message, text)
        persona_fit = self._score_persona_fit(request, text)
        tone = self._score_tone(text)
        completeness = self._score_completeness(text)
        safety = self._score_safety(text)

        dimensions = [
            ValidationDimension(name="relevance", score=relevance, reason=self._reason("relevance", relevance, text)),
            ValidationDimension(name="persona_fit", score=persona_fit, reason=self._reason("persona_fit", persona_fit, text)),
            ValidationDimension(name="tone", score=tone, reason=self._reason("tone", tone, text)),
            ValidationDimension(name="completeness", score=completeness, reason=self._reason("completeness", completeness, text)),
            ValidationDimension(name="safety", score=safety, reason=self._reason("safety", safety, text)),
        ]

        overall = self._compute_overall(
            {
                "relevance": relevance,
                "persona_fit": persona_fit,
                "tone": tone,
                "completeness": completeness,
                "safety": safety,
            }
        )

        issues = self._collect_issues(text, safety, completeness, relevance)

        passed = overall >= self.threshold and not any(
            d.name == "safety" and d.score < 0.5 for d in dimensions
        )

        logger.debug("Validated response: overall=%.2f passed=%s", overall, passed)

        return ValidationResponse(
            overall_score=round(overall, 2),
            passed=passed,
            threshold=self.threshold,
            dimensions=dimensions,
            issues=issues,
        )

    # ---------- Dimension scorers (each returns 0.0-1.0) ----------

    def _score_relevance(self, user_message: str, response: str) -> float:
        """How well the response addresses the user's message."""
        if not response:
            return 0.0
        # Heuristic: shared word overlap between user message and response.
        user_tokens = self._tokenize(user_message)
        resp_tokens = self._tokenize(response)
        if not user_tokens:
            return 0.4  # nothing to align against; neutral
        overlap = sum(1 for t in user_tokens if t in resp_tokens)
        ratio = overlap / len(user_tokens)
        # Cap and floor: a response that at least answers in the user's language
        # gets a reasonable base; high overlap boosts it.
        score = 0.4 + min(0.6, ratio)
        return min(1.0, score)

    def _score_persona_fit(self, request: ValidationRequest, response: str) -> float:
        """Does the response reflect the persona's declared style?"""
        if not request.personality and not request.persona_name:
            # No persona constraints to check → neutral full score.
            return 1.0
        base = 1.0
        # If a persona name is declared, a response that never names itself but
        # is still coherent is fine; we only penalize when persona traits are
        # explicitly declared and the response contradicts them (heuristic).
        if request.personality.get("professional") in (True, 1):
            if any(ch in response for ch in ["哇", "哈哈", "超级", "超萌", "🎉"]):
                base -= 0.3
        if request.personality.get("concise") in (True, 1) and len(response) > self.MAX_LENGTH:
            base -= 0.2
        return max(0.0, min(1.0, base))

    def _score_tone(self, response: str) -> float:
        """Is the tone safe, non-offensive, and appropriate?"""
        if not response:
            return 0.0
        score = 1.0
        lowered = response.lower()
        for bad in ["滚", "去死", "废物", "shut up", "stupid"]:
            if bad in lowered:
                score -= 0.5
        return max(0.0, min(1.0, score))

    def _score_completeness(self, response: str) -> float:
        """Is the response complete enough (not empty/truncated)?"""
        if not response:
            return 0.0
        if len(response) < self.MIN_USEFUL_LENGTH:
            return 0.3
        # Ends mid-sentence without punctuation?
        stripped = response.rstrip()
        if stripped and stripped[-1] not in "。！？!?…":
            return 0.85
        return 1.0

    def _score_safety(self, response: str) -> float:
        """Does the response avoid fabrication/harmful content?"""
        if not response:
            return 1.0  # nothing unsafe in an empty response (completeness catches that)
        score = 1.0
        for pattern in self.HALLUCINATION_PATTERNS:
            if re.search(pattern, response):
                score -= 0.4
        return max(0.0, min(1.0, score))

    # ---------- Helpers ----------

    def _compute_overall(self, scores: Dict[str, float]) -> float:
        """Weighted overall score scaled to 0-5."""
        total = sum(self.DIMENSION_WEIGHTS.get(k, 0.0) * scores.get(k, 0.0) for k in scores)
        return total * 5.0

    def _reason(self, dim: str, score: float, text: str) -> str:
        if score >= 0.8:
            return f"{dim}: strong ({score:.2f})"
        if score >= 0.5:
            return f"{dim}: acceptable ({score:.2f})"
        return f"{dim}: weak ({score:.2f}) — '({text[:40]})'"

    def _collect_issues(
        self, text: str, safety: float, completeness: float, relevance: float
    ) -> List[str]:
        issues: List[str] = []
        if not text:
            issues.append("response is empty")
        if completeness < 0.5:
            issues.append("response appears incomplete or too short")
        if safety < 0.5:
            issues.append("response may contain unverifiable claims")
        if relevance < 0.3:
            issues.append("response may not address the user's message")
        return issues

    def _tokenize(self, text: str) -> set:
        """Cheap bilingual token set for overlap heuristics.

        Splits on whitespace/punctuation, keeps CJK bigrams + latin words.
        """
        tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
        # CJK bigrams
        cjk = re.findall(r"[\u4e00-\u9fff]", text)
        for i in range(len(cjk) - 1):
            tokens.add(cjk[i] + cjk[i + 1])
        # Also add individual CJK chars for short messages
        for ch in cjk:
            tokens.add(ch)
        return tokens
