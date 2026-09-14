"""Pure, provider-agnostic AI content generator core (Phase 5).

This is the reusable, testable heart of AI nurture-content generation. It knows
nothing about the database or any specific LLM vendor — an LLM provider is an
*optional injected dependency* (the same idiom as Phase 2's ``DecisionEngine``).
When no provider is wired, or the provider is unhealthy, or it returns output
that fails the quality bar, the generator transparently falls back to the
deterministic template path, so content generation **always** returns a usable,
quality-scored result.

Architecture (mirrors the DecisionEngine layering):
    1. Strategy selection  (llm | template)
    2. Generation          (LLM completion OR deterministic template)
    3. Quality evaluation  (ContentQualityEvaluator, always on)
    4. Reproducible output (GeneratedContent with strategy + fallback flags)

Design principles
-----------------
- Provider-agnostic: any object exposing ``healthy()`` +
  ``async complete(system, messages) -> str`` can be injected.
- Deterministic core: with no provider the same input always yields the same
  output — fully offline-testable.
- Explainable: every result carries ``strategy`` and, on fallback, a
  ``fallback_reason``.
- Quality-gated: the LLM path only wins if it parses to valid content *and*
  passes the quality evaluator; otherwise the template result is kept.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.schemas.content_generation import (
    ContentEvaluationRequest,
    ContentGenerationRequest,
    GeneratedContent,
    QualityEvaluation,
)
from app.services.content_quality_evaluator import ContentQualityEvaluator
from app.services.content_templates import generate_template_content

logger = logging.getLogger(__name__)


# Target lengths (chars) used to steer the LLM and to trim the template output.
_LENGTH_BUDGETS: Dict[str, int] = {"short": 140, "medium": 320, "long": 680}


class ContentGenerator:
    """Provider-agnostic generator: optional LLM + deterministic template fallback."""

    # Objectives we recognise; unknown ones still get a sane template.
    KNOWN_OBJECTIVES: List[str] = [
        "welcome",
        "nurture",
        "reactivation",
        "cross_sell",
        "support",
    ]

    def __init__(
        self,
        *,
        evaluator: Optional[ContentQualityEvaluator] = None,
        llm_provider: Optional[Any] = None,
        threshold: Optional[float] = None,
    ) -> None:
        self.evaluator = evaluator or ContentQualityEvaluator()
        self.llm_provider = llm_provider
        self.threshold = threshold

    # ---------- Public API ----------

    async def generate(self, request: ContentGenerationRequest) -> GeneratedContent:
        """Produce a personalised, quality-scored content piece.

        Tries the LLM path only when a healthy provider is wired; otherwise (or
        on any LLM failure / quality miss) returns the deterministic template
        result. Either way the outcome is a complete ``GeneratedContent``.
        """
        strategy, _ = self._select_strategy()

        # Baseline: the deterministic template is always available.
        template_result = self._template_result(request)

        if strategy == "llm":
            if not self._llm_healthy():
                quality = self._evaluate(request, template_result)
                return self._build(
                    request, template_result, quality, "template", True,
                    "LLM provider unavailable or unhealthy; using deterministic template",
                )
            llm_result = await self._llm_result(request)
            if llm_result is not None:
                # Only trust the LLM if it parses AND clears the quality bar.
                quality = self._evaluate(request, llm_result)
                if self._passes(quality):
                    return self._build(request, llm_result, quality, "llm", False, None)
                logger.info(
                    "LLM content failed quality bar (score=%.2f) → template fallback",
                    quality.score,
                )
                template_quality = self._evaluate(request, template_result)
                return self._build(
                    request, template_result, template_quality, "template", True,
                    "LLM output failed quality evaluation; using deterministic template",
                )
            # Provider healthy but produced no usable content.
            quality = self._evaluate(request, template_result)
            return self._build(
                request, template_result, quality, "template", True,
                "LLM returned no usable content; using deterministic template",
            )

        # No provider wired: the template path is primary (documented fallback).
        quality = self._evaluate(request, template_result)
        return self._build(
            request, template_result, quality, "template", True,
            "No LLM provider wired; using deterministic template",
        )

    # ---------- Strategy ----------

    def _select_strategy(self) -> tuple[str, Optional[str]]:
        """Pick a strategy. LLM only when a provider is actually injected."""
        if self.llm_provider is None:
            return "template", None
        return "llm", None

    def _llm_healthy(self) -> bool:
        healthy = getattr(self.llm_provider, "healthy", None)
        if healthy is None:
            # No health check exposed → optimistically assume usable.
            return True
        try:
            return bool(healthy())
        except Exception:  # noqa: BLE001
            logger.warning("LLM provider health check raised; treating as unhealthy")
            return False

    # ---------- Generation paths ----------

    def _template_result(self, request: ContentGenerationRequest) -> Dict[str, Any]:
        """Deterministic, offline-testable content from the customer context."""
        result = generate_template_content(
            content_type=request.content_type,
            objective=request.objective,
            persona_name=request.persona_name,
            segment_name=request.segment_name,
            stage_name=request.stage_name,
            customer_name=request.customer_name,
            customer_tags=request.customer_tags,
            tone=request.tone,
            channel=request.channel,
            include_cta=request.include_cta,
            extra_tags=request.tags,
        )
        # Light length steering: trim the body for a "short" target.
        result = self._apply_length(request.length, result)
        return result

    async def _llm_result(self, request: ContentGenerationRequest) -> Optional[Dict[str, Any]]:
        """Ask the LLM provider for structured content; return None on failure."""
        try:
            system, user = self._build_prompt(request)
            raw = await self.llm_provider.complete(system, user)
            if not raw or not raw.strip():
                return None
            parsed = self._parse_llm_content(raw, request.content_type)
            if parsed is None:
                return None
            parsed = self._apply_length(request.length, parsed)
            return parsed
        except Exception as exc:  # noqa: BLE001 — LLM must never break generation
            logger.warning("LLM content generation failed, falling back to template: %s", exc)
            return None

    # ---------- Prompt building ----------

    @staticmethod
    def _build_prompt(request: ContentGenerationRequest) -> tuple[str, List[Dict[str, Any]]]:
        """Build the LLM system + user messages for structured content."""
        objective = request.objective or "nurture"
        length_hint = _LENGTH_BUDGETS.get(request.length, _LENGTH_BUDGETS["medium"])
        system = (
            "You are a private-domain (私域) nurture copywriter for a customer "
            "engagement platform. Given the customer's personalization context, write "
            "warm, concise, on-brand marketing copy in the requested language. "
            "Never invent specific statistics, prices, or commitments the business "
            "did not provide. Respond with ONLY a valid JSON object: "
            '{"title": string, "body": string, "summary": string, "tags": [string]}. '
            "The body must be roughly " + str(length_hint) + " characters."
        )
        user_payload = {
            "objective": objective,
            "content_type": request.content_type,
            "language": request.language,
            "tone": request.tone,
            "persona_name": request.persona_name,
            "segment_name": request.segment_name,
            "stage_name": request.stage_name,
            "customer_name": request.customer_name,
            "customer_tags": request.customer_tags,
            "extra_tags": request.tags,
            "include_cta": request.include_cta,
        }
        user = [
            {
                "role": "system",
                "content": "You respond with valid JSON only, no commentary.",
            },
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        return system, user

    @staticmethod
    def _parse_llm_content(raw: str, content_type: str) -> Optional[Dict[str, Any]]:
        """Defensively parse an LLM reply into a content dict. None if unusable."""
        text = raw.strip()
        # Strip markdown code fences if the model wrapped the JSON.
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        data: Optional[Dict[str, Any]] = None
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            # Try to recover the first {...} object embedded in the text.
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                except (ValueError, TypeError):
                    data = None
        if not isinstance(data, dict):
            return None

        title = str(data.get("title") or "").strip()
        body = str(data.get("body") or "").strip()
        if not body:
            # A bodyless reply is not usable content.
            return None
        summary = str(data.get("summary") or "").strip()
        tags = data.get("tags")
        if not isinstance(tags, list):
            tags = []
        tags = [str(t) for t in tags if str(t).strip()]
        return {
            "title": title or body[:40],
            "body": body,
            "summary": summary or body[:60],
            "content_type": content_type,
            "tags": tags,
        }

    # ---------- Helpers ----------

    @staticmethod
    def _apply_length(length: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """Steer body length. 'short' keeps the opening paragraph + the trailing
        CTA line, dropping the middle content so the body is actually shorter."""
        if length != "short":
            return result
        body = result.get("body", "")
        paragraphs = [p for p in body.split("\n\n") if p.strip()]
        if len(paragraphs) <= 2:
            return result  # already short enough
        first = paragraphs[0]
        # Find a trailing call-to-action line (or a short closing line) to keep.
        cta_markers = ("→", "点击", "查看", "立即", "联系", "扫码", "回复", "报名")
        cta = ""
        for p in reversed(paragraphs[1:]):
            if any(m in p for m in cta_markers) or len(p) < 30:
                cta = p
                break
        trimmed = first
        if cta and cta not in first:
            trimmed = f"{first}\n\n{cta}"
        result = dict(result)
        result["body"] = trimmed
        result["summary"] = first[:60]
        return result

    def _evaluate(self, request: ContentGenerationRequest, result: Dict[str, Any]) -> QualityEvaluation:
        """Run the deterministic quality + relevance evaluation on the result."""
        ev_req = ContentEvaluationRequest(
            content=result.get("body", ""),
            title=result.get("title"),
            objective=request.objective,
            segment_name=request.segment_name,
            stage_name=request.stage_name,
            expected_tags=list(request.customer_tags) + list(request.tags),
            persona_name=request.persona_name,
        )
        return self.evaluator.evaluate(ev_req)

    def _passes(self, quality: QualityEvaluation) -> bool:
        threshold = self.threshold if self.threshold is not None else quality.threshold
        return quality.score >= threshold

    @staticmethod
    def _build(
        request: ContentGenerationRequest,
        result: Dict[str, Any],
        quality: QualityEvaluation,
        strategy: str,
        fallback_used: bool,
        fallback_reason: Optional[str],
    ) -> GeneratedContent:
        return GeneratedContent(
            title=result.get("title", ""),
            body=result.get("body", ""),
            summary=result.get("summary"),
            content_type=result.get("content_type", request.content_type),
            tags=result.get("tags", []),
            category=request.category,
            quality=quality,
            strategy=strategy,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
