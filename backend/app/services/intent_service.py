"""Intent Service - Intent classification, history, and action mapping"""
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.intent import Intent, IntentActionLog
from app.schemas.intent import (
    IntentClassificationRequest,
    IntentClassificationResponse,
    IntentResult,
    IntentHistoryResponse,
    IntentActionRequest,
    IntentActionResponse,
    IntentStatistics,
    IntentHistoryItem,
)
from app.services.default_intents import INTENT_TYPES, INTENT_ACTION_MAP, INTENT_CLASSIFICATION_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


class IntentService:
    """Service for intent classification, history tracking, and action mapping"""

    def __init__(self, db: AsyncSession, llm_provider: Optional[Any] = None):
        self.db = db
        # Injectable LLM provider for the intent layer. When None (the router
        # default) it is resolved lazily to the configured default provider,
        # keeping the AI layer provider-agnostic and testable.
        self._llm_provider = llm_provider
        # The "no LLM configured" notice is emitted at most once per service
        # instance so a keyless deployment falls back to rules without spamming
        # the log on every request.
        self._llm_unavailable_logged = False

    def _get_provider(self):
        """Return the backing LLM provider (injected, or lazily resolved)."""
        if self._llm_provider is None:
            from app.providers.openai_provider import OpenAIProvider
            self._llm_provider = OpenAIProvider()
        return self._llm_provider

    # ========== Intent Classification ==========

    async def classify_intent(
        self,
        request: IntentClassificationRequest,
    ) -> IntentClassificationResponse:
        """
        Classify user intent using LLM + rule-based fallback
        Returns classification result with confidence score
        """
        start_time = time.time()

        try:
            # Step 1: Rule-based keyword matching (fast fallback)
            keyword_result = self._classify_by_keywords(request.message, request.context)

            # Step 2: Try LLM-based classification if available
            llm_result = await self._classify_with_llm(request)

            # Step 3: Merge results - prefer LLM if confidence >= threshold
            best_intent = self._merge_results(keyword_result, llm_result)

            processing_time = (time.time() - start_time) * 1000

            return IntentClassificationResponse(
                success=True,
                intent=best_intent,
                alternatives=self._get_alternatives(keyword_result, llm_result),
                confidence_threshold=0.7,
                processing_time_ms=processing_time,
            )

        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return IntentClassificationResponse(
                success=False,
                message=f"Intent classification failed: {str(e)}",
                processing_time_ms=(time.time() - start_time) * 1000,
            )

    async def _classify_with_llm(
        self,
        request: IntentClassificationRequest,
    ) -> Optional[IntentResult]:
        """
        Use LLM to classify intent (graceful rule-based fallback if the LLM
        path is unavailable or fails). Returns None when the LLM produced no
        usable classification so the caller merges with the keyword result.
        """
        provider = self._get_provider()

        # Fast, network-free availability check: when no LLM is configured we
        # fall back to rules quietly. The notice is emitted at most once per
        # service instance (a keyless deployment does NOT spam an error line
        # on every classify call).
        if not provider.is_available():
            if not self._llm_unavailable_logged:
                logger.debug(
                    "No LLM provider configured; intent classification "
                    "falling back to rule-based matching."
                )
                self._llm_unavailable_logged = True
            return None

        try:
            # Build prompt for intent classification
            prompt = self._build_intent_prompt(request)

            # Call LLM
            response = await provider.chat_completion(
                model="gpt-4o-mini",  # Use fast model for classification
                messages=[
                    {"role": "system", "content": "You are an intent classification assistant. Always respond with valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,  # Low temperature for deterministic output
            )

            # Parse response
            import json
            result_text = response.content
            parsed = json.loads(result_text)

            return IntentResult(
                intent_type=parsed.get("intent_type", "unknown"),
                intent_name=parsed.get("intent_name", "未知意图"),
                confidence=float(parsed.get("confidence", 0.5)),
                entities=parsed.get("entities", {}),
                explanation=parsed.get("explanation", ""),
            )

        except Exception as e:
            # Provider call failed (network / model / parse): log once, degrade
            # to the rule-based result. Not an error-state that should surface
            # on every request.
            if not self._llm_unavailable_logged:
                logger.warning(f"LLM classification failed, falling back to rule-based: {e}")
                self._llm_unavailable_logged = True
            return None

    def _classify_by_keywords(
        self,
        message: str,
        context: Dict[str, Any],
    ) -> Optional[IntentResult]:
        """
        Rule-based keyword matching for intent classification
        Fast fallback when LLM is unavailable
        """
        message_lower = message.lower()
        scores = []

        for intent_type, definition in INTENT_TYPES.items():
            matched_keywords = []
            keyword_count = len(definition.get("keywords", []))

            for keyword in definition.get("keywords", []):
                if keyword.lower() in message_lower:
                    matched_keywords.append(keyword)

            if matched_keywords:
                # Calculate score based on:
                # 1. Ratio of matched keywords to total keywords
                # 2. Priority of the intent type (higher = more important)
                # 3. Pattern weight from intent definition
                pattern_weight = definition.get("pattern_weight", 1.0)
                match_ratio = len(matched_keywords) / keyword_count if keyword_count > 0 else 0
                priority_weight = definition.get("priority", 5) / 10.0

                # Combined score: heavily weight match ratio, with priority and pattern as boosters
                combined_score = (match_ratio * 0.5) + (priority_weight * 0.3) + (pattern_weight * 0.2)

                scores.append({
                    "intent_type": intent_type,
                    "intent_name": definition["intent_name"],
                    "confidence": combined_score,
                    "matched_keywords": matched_keywords,
                })

        if not scores:
            return None

        # Return the highest scoring match
        best_match = max(scores, key=lambda x: x["confidence"])

        # Calculate final confidence with boost for good matches
        keywords_matched = len(best_match["matched_keywords"])
        total_keywords = len(INTENT_TYPES[best_match["intent_type"]]["keywords"])
        match_ratio = keywords_matched / total_keywords if total_keywords > 0 else 0

        # Boost confidence: scale from 0.65 to 0.95 based on match ratio
        # Single keyword match: ~0.65, full match: 0.95
        boosted_confidence = round(0.65 + (match_ratio * 0.30), 2)

        return IntentResult(
            intent_type=best_match["intent_type"],
            intent_name=best_match["intent_name"],
            confidence=boosted_confidence,
            entities={"matched_keywords": best_match["matched_keywords"]},
        )

    def _merge_results(
        self,
        keyword_result: Optional[IntentResult],
        llm_result: Optional[IntentResult],
    ) -> IntentResult:
        """Merge keyword and LLM results, preferring LLM if confident enough"""
        if llm_result and llm_result.confidence >= 0.7:
            return llm_result

        if keyword_result and keyword_result.confidence >= 0.7:
            return keyword_result

        # Return whichever has higher confidence
        if llm_result and keyword_result:
            return llm_result if llm_result.confidence > keyword_result.confidence else keyword_result
        elif llm_result:
            return llm_result
        elif keyword_result:
            return keyword_result
        else:
            # Default to question intent
            return IntentResult(
                intent_type="question",
                intent_name="提问",
                confidence=0.5,
                entities={},
                explanation="无法识别意图，默认为提问",
            )

    def _get_alternatives(
        self,
        keyword_result: Optional[IntentResult],
        llm_result: Optional[IntentResult],
    ) -> List[IntentResult]:
        """Get alternative intent classifications"""
        alternatives = []
        if keyword_result:
            alternatives.append(keyword_result)
        if llm_result and llm_result != keyword_result:
            alternatives.append(llm_result)
        return alternatives[:3]  # Return top 3

    def _build_intent_prompt(self, request: IntentClassificationRequest) -> str:
        """Build prompt for LLM intent classification"""
        # Format intent types
        intent_types_str = "\n".join([
            f"- {info['intent_type']}: {info['intent_name']} ({info['description']})"
            for info in INTENT_TYPES.values()
        ])

        # Format previous intents
        prev_intents_str = "无"
        if request.previous_intents:
            prev_intents_str = "\n".join([
                f"{i.get('created_at', '')}: {i.get('intent_name', 'unknown')}"
                for i in request.previous_intents[-5:]
            ])

        # Format context
        context_str = "无"
        if request.context:
            context_str = str(request.context)

        return INTENT_CLASSIFICATION_PROMPT_TEMPLATE.format(
            intent_types=intent_types_str,
            user_message=request.message,
            conversation_context=context_str,
            previous_intents=prev_intents_str,
        )

    # ========== Intent History ==========

    async def save_intent(
        self,
        conversation_id: UUID,
        intent_type: str,
        intent_name: str,
        confidence: float,
        raw_input: str,
        extracted_entities: Dict[str, Any],
        context: Dict[str, Any],
        matched_action: Optional[str] = None,
    ) -> Intent:
        """Save intent classification to database"""
        intent = Intent(
            conversation_id=conversation_id,
            intent_type=intent_type,
            intent_name=intent_name,
            confidence=confidence,
            raw_input=raw_input,
            extracted_entities=extracted_entities,
            context=context,
            matched_action=matched_action,
        )
        self.db.add(intent)
        await self.db.commit()
        await self.db.refresh(intent)
        logger.info(f"Saved intent: {intent.id} - {intent_type} (confidence: {confidence})")
        return intent

    async def get_intent_history(
        self,
        conversation_id: UUID,
        limit: int = 50,
    ) -> IntentHistoryResponse:
        """Get intent history for a conversation"""
        query = select(Intent).where(
            Intent.conversation_id == conversation_id,
            Intent.is_deleted == False,
        ).order_by(Intent.created_at.desc()).limit(limit)

        result = await self.db.execute(query)
        intents = result.scalars().all()

        items = [
            IntentHistoryItem(
                id=i.id,
                conversation_id=i.conversation_id,
                intent_type=i.intent_type,
                intent_name=i.intent_name,
                confidence=i.confidence,
                raw_input=i.raw_input,
                extracted_entities=i.extracted_entities,
                matched_action=i.matched_action,
                created_at=i.created_at,
            )
            for i in intents
        ]

        # Calculate summary statistics
        summary = await self._calculate_intent_summary(conversation_id)

        return IntentHistoryResponse(
            conversation_id=conversation_id,
            intents=items,
            total=len(items),
            summary=summary,
        )

    async def _calculate_intent_summary(
        self,
        conversation_id: UUID,
    ) -> Dict[str, Any]:
        """Calculate summary statistics for intent history"""
        query = select(Intent).where(
            Intent.conversation_id == conversation_id,
            Intent.is_deleted == False,
        )
        result = await self.db.execute(query)
        intents = result.scalars().all()

        if not intents:
            return {"total": 0, "avg_confidence": 0.0, "top_intent": None}

        # Calculate statistics
        total = len(intents)
        avg_confidence = sum(i.confidence for i in intents) / total

        # Find top intent
        intent_counts: Dict[str, int] = {}
        for intent in intents:
            intent_counts[intent.intent_type] = intent_counts.get(intent.intent_type, 0) + 1

        top_intent = max(intent_counts.items(), key=lambda x: x[1])[0] if intent_counts else None

        return {
            "total": total,
            "avg_confidence": round(avg_confidence, 2),
            "top_intent": top_intent,
            "intent_distribution": intent_counts,
        }

    # ========== Intent to Action Mapping ==========

    async def map_intent_to_action(
        self,
        request: IntentActionRequest,
    ) -> IntentActionResponse:
        """Map intent to appropriate action"""
        action_config = INTENT_ACTION_MAP.get(request.intent_type)

        if not action_config:
            return IntentActionResponse(
                success=False,
                fallback_message=f"No action mapped for intent type: {request.intent_type}",
            )

        # Build action response
        response = IntentActionResponse(
            success=True,
            action_type=action_config["action_type"],
            action_target=request.entities.get("target"),
            action_params={**action_config.get("action_params", {}), **request.context},
        )

        # Save action log
        await self._save_action_log(
            intent_id=None,  # Will be set after intent is saved
            action_type=response.action_type,
            action_target=response.action_target,
            action_params=response.action_params,
        )

        return response

    async def _save_action_log(
        self,
        intent_id: Optional[UUID],
        action_type: str,
        action_target: Optional[str],
        action_params: Dict[str, Any],
    ) -> IntentActionLog:
        """Save intent-to-action mapping to database"""
        action_log = IntentActionLog(
            intent_id=intent_id,
            action_type=action_type,
            action_target=action_target,
            action_params=action_params,
            executed=False,
        )
        self.db.add(action_log)
        await self.db.commit()
        await self.db.refresh(action_log)
        return action_log

    # ========== Intent Statistics ==========

    async def get_intent_statistics(
        self,
        days: int = 30,
    ) -> IntentStatistics:
        """Get intent statistics for analytics"""
        from datetime import timedelta
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        query = select(Intent).where(
            Intent.is_deleted == False,
            Intent.created_at >= cutoff_date,
        )
        result = await self.db.execute(query)
        intents = result.scalars().all()

        if not intents:
            return IntentStatistics()

        # Calculate statistics
        total = len(intents)
        avg_confidence = sum(i.confidence for i in intents) / total

        # Intent distribution
        intent_counts: Dict[str, int] = {}
        for intent in intents:
            intent_counts[intent.intent_type] = intent_counts.get(intent.intent_type, 0) + 1

        # Sort by count
        top_intents = sorted(
            [{"intent_type": k, "count": v} for k, v in intent_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        # Confidence distribution
        confidence_buckets = {"high (0.8-1.0)": 0, "medium (0.6-0.8)": 0, "low (0.4-0.6)": 0, "very_low (<0.4)": 0}
        for intent in intents:
            conf = intent.confidence
            if conf >= 0.8:
                confidence_buckets["high (0.8-1.0)"] += 1
            elif conf >= 0.6:
                confidence_buckets["medium (0.6-0.8)"] += 1
            elif conf >= 0.4:
                confidence_buckets["low (0.4-0.6)"] += 1
            else:
                confidence_buckets["very_low (<0.4)"] += 1

        return IntentStatistics(
            total_classifications=total,
            avg_confidence=round(avg_confidence, 2),
            top_intents=top_intents,
            intent_distribution=intent_counts,
            confidence_distribution=confidence_buckets,
        )
