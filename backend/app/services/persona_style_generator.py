"""Persona Style Generator - Conversation Style from Persona Entity

Turns a Persona entity (name + description + personality JSON) into an
executable conversation style: a system prompt, style directives, tone
keywords, and example responses.

Design principles:
- Pure Python: deterministic, no LLM or DB dependency → fully testable.
- Input/output contracts defined in app.schemas.decision.
- Degrades gracefully: a minimal persona (just a name) still yields a valid style.
- Reusable: output feeds the Context Builder (system_instruction) and the
  Decision Engine (style directives).

This is the "Persona" half of the core pipeline:
    Persona → [Style Generator] → System Prompt + Directives
"""
import logging
from typing import List, Dict, Any, Optional

from app.schemas.decision import PersonaStyleRequest, PersonaStyleResponse

logger = logging.getLogger(__name__)


# Canonical persona personality axes. Each maps a persona trait (in
# personality JSON) to concrete style directives the response should honor.
# Keys are normalized trait names; values are directive fragments.
_TRAIT_DIRECTIVES: Dict[str, str] = {
    "friendly": "Be warm, friendly, and approachable; use the customer's name when known.",
    "professional": "Keep the tone professional and precise; avoid slang or excessive emoji.",
    "casual": "Use a relaxed, conversational tone; keep sentences short and natural.",
    "empathetic": "Acknowledge the customer's feelings first; show empathy before giving solutions.",
    "concise": "Be concise; lead with the answer, then add details only if helpful.",
    "detailed": "Be thorough; provide step-by-step detail and context as needed.",
    "authoritative": "Speak confidently and decisively; present clear recommendations.",
    "playful": "Add light, playful energy while still being clear and accurate.",
    "polite": "Always be polite and respectful; thank the customer and close courteously.",
    "patient": "Be patient and unhurried; restate requests to confirm understanding.",
}

# Sentiment-aware tone keywords. Keyed by a coarse sentiment hint that a
# persona personality block may carry ({"sentiment_bias": "warm"|"neutral"|"firm"}).
_TONE_KEYWORDS: Dict[str, List[str]] = {
    "warm": ["warm", "friendly", "empathetic", "encouraging"],
    "neutral": ["calm", "clear", "helpful", "neutral"],
    "firm": ["firm", "decisive", "professional", "reassuring"],
}


class PersonaStyleGenerator:
    """Generate an executable conversation style from a persona definition."""

    def generate(
        self,
        request: Optional[PersonaStyleRequest] = None,
        *,
        persona_id: Optional[Any] = None,
        persona_name: str = "Assistant",
        description: Optional[str] = None,
        personality: Optional[Dict[str, Any]] = None,
    ) -> PersonaStyleResponse:
        """Build a style response.

        Accepts either a prebuilt PersonaStyleRequest or raw fields, so callers
        can pass a service object (PersonaService) result or plain data.
        """
        if request is None:
            request = PersonaStyleRequest(
                persona_id=persona_id,
                persona_name=persona_name,
                description=description,
                personality=personality or {},
            )

        personality = request.personality or {}
        directives = self._build_directives(request.persona_name, request.description, personality)
        tone_keywords = self._build_tone_keywords(personality, directives)
        system_prompt = self._build_system_prompt(request, directives)
        examples = self._build_examples(request, directives)

        logger.debug("Generated style for persona '%s' (%d directives)", request.persona_name, len(directives))

        return PersonaStyleResponse(
            persona_name=request.persona_name,
            system_prompt=system_prompt,
            tone_keywords=tone_keywords,
            style_directives=directives,
            example_responses=examples,
        )

    # ---------- Builders ----------

    def _build_directives(
        self,
        name: str,
        description: Optional[str],
        personality: Dict[str, Any],
    ) -> List[str]:
        """Derive concrete style directives from the persona definition."""
        directives: List[str] = []

        # 1. Explicit trait directives (normalized to lowercase keys).
        seen = set()
        for key, value in personality.items():
            norm_key = str(key).strip().lower()
            if norm_key in seen:
                continue
            # Traits may be expressed as bool flags, scalar values, or nested dicts.
            if isinstance(value, dict):
                # e.g. {"empathetic": {"weight": 0.8}} → honor if weight > 0
                weight = value.get("weight", value.get("value"))
                if weight in (None, 0, 0.0, False):
                    continue
                trait_key = norm_key
                for inner in value:
                    if isinstance(inner, str) and inner.lower() in _TRAIT_DIRECTIVES:
                        trait_key = inner.lower()
                        break
                if trait_key in _TRAIT_DIRECTIVES and trait_key not in seen:
                    directives.append(_TRAIT_DIRECTIVES[trait_key])
                    seen.add(trait_key)
            else:
                # bool / scalar flag: honor truthy values
                if value in (True, 1, 1.0) or (isinstance(value, str) and value.lower() in _TRAIT_DIRECTIVES):
                    trait_key = str(value).strip().lower() if isinstance(value, str) else norm_key
                    if trait_key in _TRAIT_DIRECTIVES and trait_key not in seen:
                        directives.append(_TRAIT_DIRECTIVES[trait_key])
                        seen.add(trait_key)

        # 2. Description-derived guidance (kept as a soft directive).
        if description and description.strip():
            directives.append(
                f"Persona profile: {description.strip()[:200]}. Reflect this in your replies."
            )

        # 3. Always-on baseline so a minimal persona still behaves.
        if not directives:
            directives = [
                "Be helpful, clear, and respectful.",
                "Reply in the customer's language.",
                f"Identify consistently as {name} when asked who you are.",
            ]

        # Deduplicate while preserving order.
        unique: List[str] = []
        for d in directives:
            if d not in unique:
                unique.append(d)
        return unique

    def _build_tone_keywords(
        self,
        personality: Dict[str, Any],
        directives: List[str],
    ) -> List[str]:
        """Pick a tone keyword set from an optional sentiment bias trait."""
        bias = str(personality.get("sentiment_bias", "neutral")).strip().lower()
        if bias not in _TONE_KEYWORDS:
            # Infer from directives when no explicit bias is present.
            if any("empathetic" in d.lower() or "warm" in d.lower() for d in directives):
                bias = "warm"
            elif any("decisive" in d.lower() or "confident" in d.lower() for d in directives):
                bias = "firm"
            else:
                bias = "neutral"
        return _TONE_KEYWORDS.get(bias, _TONE_KEYWORDS["neutral"])

    def _build_system_prompt(
        self,
        request: PersonaStyleRequest,
        directives: List[str],
    ) -> str:
        """Compose the final system prompt from name + directives."""
        lines = [
            f"You are {request.persona_name}, an AI assistant."
        ]
        if request.description and request.description.strip():
            lines.append(f"Profile: {request.description.strip()}")
        lines.append("")
        lines.append("Follow these style directives:")
        for i, d in enumerate(directives, 1):
            lines.append(f"{i}. {d}")
        lines.append(
            "Stay in character, be accurate, and never fabricate facts. "
            "If unsure or LLM assistance is unavailable, fall back to a safe, "
            "helpful default response."
        )
        return "\n".join(lines)

    def _build_examples(
        self,
        request: PersonaStyleRequest,
        directives: List[str],
    ) -> List[str]:
        """Produce short example responses reflecting the directives."""
        name = request.persona_name
        examples = [
            f"{name}: 您好！很高兴为您服务，请问有什么可以帮您？",
        ]
        any_warm = any("warm" in d.lower() or "friendly" in d.lower() for d in directives)
        any_concise = any("concise" in d.lower() for d in directives)
        any_empathy = any("empathy" in d.lower() or "empathetic" in d.lower() for d in directives)
        if any_warm:
            examples.append(f"{name}: 收到～别担心，我来帮您一步步处理，有什么随时说。")
        if any_concise:
            examples.append(f"{name}: 结论：可以。细节需要的话我再补充。")
        if any_empathy:
            examples.append(f"{name}: 听起来确实不太舒服，很理解您的心情。我们先把问题理清。")
        return examples
