"""Context Builder - Conversation Context Construction

Builds optimized, token-budgeted conversation context for AI responses.

Design principles:
- Pure Python: no DB or LLM dependency — all context is passed in explicitly.
- Explainable: every section is clearly labeled and accounted for in tokens.
- Degrades gracefully: works with any subset of inputs (message, history, memory).
- Token-budgeted: fits within max_tokens, trimming least-important sections first.

The builder is the "Context" half of the core pipeline:
    Understand → Remember → [Context Builder] → Strategy → Action
"""
import logging
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID

from app.schemas.decision import ContextBuildRequest, ContextBuildResponse

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Assemble a structured, token-budgeted context block for the LLM."""

    # Fraction of the token budget allocated to each section.
    # The builder trims sections in this priority order when over budget:
    # summary (0.10) → memories (0.15) → recent messages (0.50) → user message (kept whole).
    SECTION_BUDGETS: Dict[str, float] = {
        "system_instruction": 0.15,
        "summary": 0.10,
        "memories": 0.15,
        "recent_messages": 0.50,
        "user_message": 0.10,
    }

    MAX_RECENT_MESSAGES = 10
    MAX_MEMORY_ITEMS = 5
    MAX_MEMORY_CONTENT_CHARS = 200
    MAX_SUMMARY_CHARS = 500

    # CJK characters are ~1 token each; latin ~4 chars/token. Use a blended estimate.
    CJK_TOKEN_RATIO = 1.0      # chars treated as ~1 token
    LATIN_TOKEN_RATIO = 0.25   # chars treated as ~0.25 token

    def build_context(self, request: ContextBuildRequest) -> ContextBuildResponse:
        """Build the context response, respecting the token budget."""
        # 1. Build each section independently.
        system_instruction = request.system_instruction or self._default_system_instruction(request)
        summary = self._format_summary(request.conversation_summary)
        memories, memory_count = self._format_memories(request.relevant_memories)
        recent = self._format_recent_messages(request.recent_messages)
        user_message = f"User: {request.current_message}"

        sections = {
            "system_instruction": system_instruction,
            "summary": summary,
            "memories": memories,
            "recent_messages": recent,
            "user_message": user_message,
        }

        # 2. If over budget, trim in priority order (keep user message + system anchor).
        total = self._total_tokens(sections)
        truncated = False
        if total > request.max_tokens:
            for key in ("summary", "memories", "recent_messages"):
                remaining = request.max_tokens - self._total_tokens(sections)
                if remaining >= 0:
                    break
                sections[key] = self._shrink(sections[key], key, request.max_tokens)
                truncated = True

        final_total = self._total_tokens(sections)

        logger.debug(
            "Built context for %s: %d tokens (budget %d, truncated=%s)",
            request.conversation_id, final_total, request.max_tokens, truncated,
        )

        return ContextBuildResponse(
            conversation_id=request.conversation_id,
            system_context=sections["system_instruction"],
            user_context=self._compose_user_context(sections, request),
            recent_messages=recent,
            memories_included=memory_count,
            summary_included=bool(summary),
            total_tokens=final_total,
            token_budget=request.max_tokens,
            truncated=truncated,
        )

    # ---------- Section formatters ----------

    def _default_system_instruction(self, request: ContextBuildRequest) -> str:
        name = request.persona_name or "a helpful AI assistant"
        return f"You are {name}. Reply in the user's language and follow the persona's style."

    def _format_summary(self, summary: Optional[str]) -> str:
        if not summary:
            return ""
        trimmed = summary[: self.MAX_SUMMARY_CHARS]
        return f"Earlier in this conversation:\n{trimmed}"

    def _format_memories(self, memories: List[Dict[str, Any]]) -> Tuple[str, int]:
        if not memories:
            return "", 0
        included = memories[: self.MAX_MEMORY_ITEMS]
        lines = []
        for m in included:
            content = str(m.get("content", ""))[: self.MAX_MEMORY_CONTENT_CHARS]
            mtype = m.get("memory_type", m.get("type", "memory"))
            lines.append(f"[{mtype}] {content}")
        return "Relevant memories:\n" + "\n".join(lines), len(included)

    def _format_recent_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return the most recent messages (already structured for the LLM)."""
        recent = list(messages[-self.MAX_RECENT_MESSAGES:])
        # Normalize to {role, content}
        return [
            {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
            for m in recent
        ]

    def _compose_user_context(
        self, sections: Dict[str, str], request: ContextBuildRequest
    ) -> str:
        """Flatten all sections into a single prompt body (without the system line)."""
        parts: List[str] = []
        if sections.get("summary"):
            parts.append(sections["summary"])
        if sections.get("memories"):
            parts.append(sections["memories"])
        if sections.get("recent_messages"):
            parts.append("Recent conversation:\n" + "\n".join(
                f"{m['role']}: {m['content']}" for m in sections["recent_messages"]
            ))
        if sections.get("user_message"):
            parts.append(sections["user_message"])
        return "\n\n".join(parts)

    # ---------- Token accounting ----------

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        other = len(text) - cjk
        return int(cjk * self.CJK_TOKEN_RATIO + other * self.LATIN_TOKEN_RATIO) + 1

    def _total_tokens(self, sections: Dict[str, Any]) -> int:
        total = 0
        for key, value in sections.items():
            if key == "recent_messages":
                total += self._estimate_tokens(
                    "\n".join(f"{m['role']}: {m['content']}" for m in value)
                )
            else:
                total += self._estimate_tokens(value)
        return total

    def _shrink(self, value: Any, key: str, max_tokens: int) -> Any:
        """Shrink a single section toward its budgeted slice of the total."""
        budget = int(max_tokens * self.SECTION_BUDGETS.get(key, 0.1))
        if key == "recent_messages":
            # Keep the most recent messages that fit the budget.
            kept: List[Dict[str, Any]] = []
            running = 0
            for m in reversed(value):
                msg_tokens = self._estimate_tokens(f"{m['role']}: {m['content']}")
                if running + msg_tokens > budget and kept:
                    break
                kept.insert(0, m)
                running += msg_tokens
            return kept
        # string section
        if isinstance(value, str):
            return value[: budget * 4]
        return value
