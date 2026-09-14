"""Content Generation Service - platform adapter over the pure generator (Phase 5).

Wires the pure, provider-agnostic ``ContentGenerator`` to the platform:
optional LLM provider injection, DB persistence of the ``ContentGeneration``
audit log, content-library persistence, and NurturePlan step injection.

Design (mirrors DecisionService):
- The service works WITHOUT a DB session (db=None): generation + evaluation
  still run in full (pure logic).
- When a DB session is provided, results are persisted for reproducibility
  and auditability, and content can be injected into NurturePlan steps.
- The LLM provider is an optional injected dependency; absent → deterministic
  template path (always a safe, usable result).

This keeps AI logic separated from platform logic: the pure
``ContentGenerator`` is the reusable, testable core; this class is the thin
platform adapter.
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.content_generation import ContentGeneration
from app.db.models.private_domain import ContentItem
from app.schemas.content_generation import (
    ContentEvaluationRequest,
    ContentGenerationRequest,
    ContentInjectionRequest,
    ContentInjectionResponse,
    GeneratedContent,
    GenerationHistoryItem,
    GenerationHistoryResponse,
    QualityEvaluation,
)
from app.schemas.private_domain import ContentItemCreate
from app.services.content_generator import ContentGenerator
from app.services.content_quality_evaluator import ContentQualityEvaluator
from app.services.nurture_plan_service import create_nurture_plan_step

logger = logging.getLogger(__name__)


class ContentGenerationService:
    """Platform adapter: generation + evaluation + persistence + injection."""

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        *,
        llm_provider: Optional[Any] = None,
        generator: Optional[ContentGenerator] = None,
        evaluator: Optional[ContentQualityEvaluator] = None,
        threshold: Optional[float] = None,
    ) -> None:
        self.db = db
        self.generator = generator or ContentGenerator(
            evaluator=evaluator,
            llm_provider=llm_provider,
            threshold=threshold,
        )
        self.evaluator = evaluator or ContentQualityEvaluator()

    # ---------- Content generation ----------

    async def generate_content(
        self, request: ContentGenerationRequest
    ) -> GeneratedContent:
        """Generate personalized content; persist the audit log when a DB is wired.

        If ``request.save_to_library`` is set and a DB is available, the result is
        also persisted as a ``ContentItem`` and linked into the audit log.
        Persistence failure must never break generation (mirrors DecisionService).
        """
        result = await self.generator.generate(request)
        if self.db is not None:
            try:
                content_item_id: Optional[UUID] = None
                if request.save_to_library:
                    content_item_id = await self.save_to_library(request, result)
                    result.content_item_id = content_item_id
                log = await self._persist_generation(
                    request, result, source="ai_content", content_item_id=content_item_id
                )
                result.generation_id = log.id
            except Exception as exc:  # noqa: BLE001 — generation must not break on audit failure
                logger.warning("Failed to persist content generation log: %s", exc)
        return result

    async def _persist_generation(
        self,
        request: ContentGenerationRequest,
        result: GeneratedContent,
        *,
        source: str,
        content_item_id: Optional[UUID] = None,
        nurture_plan_id: Optional[UUID] = None,
        plan_step_id: Optional[UUID] = None,
    ) -> ContentGeneration:
        """Write one ContentGeneration audit row (reproducibility)."""
        assert self.db is not None
        log = ContentGeneration(
            account_id=request.account_id,
            source=source,
            content_type=result.content_type,
            strategy=result.strategy,
            fallback_used=result.fallback_used,
            fallback_reason=result.fallback_reason,
            segment_id=request.segment_id,
            stage_code=request.stage_code,
            content_id=content_item_id,
            nurture_plan_id=nurture_plan_id,
            plan_step_id=plan_step_id,
            quality_score=result.quality.score,
            quality_passed=result.quality.passed,
            input_snapshot=self._input_snapshot(request),
            output_snapshot={
                "title": result.title,
                "body": result.body,
                "summary": result.summary,
                "tags": result.tags,
                "category": result.category,
            },
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log

    @staticmethod
    def _input_snapshot(request: ContentGenerationRequest) -> Dict[str, Any]:
        """Capture the personalization context that drove generation (JSON-safe)."""
        return {
            "content_type": request.content_type,
            "objective": request.objective,
            "channel": request.channel,
            "persona_name": request.persona_name,
            "segment_id": str(request.segment_id) if request.segment_id else None,
            "segment_name": request.segment_name,
            "stage_code": request.stage_code,
            "stage_name": request.stage_name,
            "customer_tags": request.customer_tags,
            "customer_name": request.customer_name,
            "tone": request.tone,
            "length": request.length,
            "language": request.language,
            "include_cta": request.include_cta,
            "save_to_library": request.save_to_library,
            "category": request.category,
            "tags": request.tags,
        }

    # ---------- Content evaluation (public) ----------

    def evaluate_content(self, request: ContentEvaluationRequest) -> QualityEvaluation:
        """Evaluate any content piece against an intended context (no generation)."""
        return self.evaluator.evaluate(request)

    # ---------- Library persistence ----------

    async def save_to_library(
        self, request: ContentGenerationRequest, result: GeneratedContent
    ) -> Optional[UUID]:
        """Persist generated content as a ContentItem; returns the new item id."""
        if self.db is None:
            return None
        data = ContentItemCreate(
            account_id=request.account_id,
            content_type=result.content_type,
            title=result.title[:200],
            summary=result.summary,
            body=result.body,
            tags=result.tags,
            category=request.category,
        )
        item = ContentItem(
            account_id=data.account_id,
            content_type=data.content_type,
            title=data.title,
            summary=data.summary,
            body=data.body,
            media_urls=[],
            tags=data.tags or [],
            category=data.category,
            usage_count=0,
            last_used_at=None,
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item.id

    # ---------- NurturePlan injection ----------

    async def inject_into_plan(
        self, request: ContentInjectionRequest
    ) -> ContentInjectionResponse:
        """Generate (or reuse) content and attach it to a NurturePlan step.

        - ``request.generate`` present → run the full generation pipeline and
          link the result to a new plan step.
        - ``request.content_id`` present (and no ``generate``) → reuse an
          existing library item for the step.
        """
        if self.db is None:
            raise ValueError("Content injection requires a DB session")

        step_order = request.step_order
        created_step = step_order is None

        if request.generate is not None:
            gen_request = request.generate
            # The plan's account owns the content, not the caller's.
            gen_request.account_id = request.account_id

            result = await self.generator.generate(gen_request)

            # A plan step must reference a real persisted content item (a dead
            # step with no content_id is unusable), so the injection path always
            # persists to the library regardless of save_to_library.
            content_item_id: Optional[UUID] = await self.save_to_library(gen_request, result)

            if step_order is None:
                step_order = await self._next_step_order(request.plan_id)

            step = await create_nurture_plan_step(
                self.db,
                request.plan_id,
                step_order,
                content_id=content_item_id,
                delay_hours=request.delay_hours,
                trigger_type=request.trigger_type,
                config={
                    **(request.config or {}),
                    "generation_strategy": result.strategy,
                    "quality_score": result.quality.score,
                    "quality_passed": result.quality.passed,
                    "title": result.title,
                    "body": result.body,
                },
            )

            await self._persist_generation(
                gen_request,
                result,
                source="ai_nurture",
                content_item_id=content_item_id,
                nurture_plan_id=request.plan_id,
                plan_step_id=step["id"],
            )

            return ContentInjectionResponse(
                generation_id=None,
                content_item_id=content_item_id,
                step_id=step["id"],
                step_order=step_order,
                content=result,
                created_step=created_step,
            )

        # Reuse path: link an existing content item to the step.
        if request.content_id is None:
            raise ValueError("Provide either 'generate' or 'content_id' to inject content")

        if step_order is None:
            step_order = await self._next_step_order(request.plan_id)

        step = await create_nurture_plan_step(
            self.db,
            request.plan_id,
            step_order,
            content_id=request.content_id,
            delay_hours=request.delay_hours,
            trigger_type=request.trigger_type,
            config=request.config or {},
        )
        return ContentInjectionResponse(
            generation_id=None,
            content_item_id=request.content_id,
            step_id=step["id"],
            step_order=step_order,
            content=await self._describe_library_item(request.content_id),
            created_step=created_step,
        )

    async def _next_step_order(self, plan_id: UUID) -> int:
        """1-based next order after the highest existing step_order for the plan."""
        from app.db.models.private_domain import NurturePlanItem as _Item

        res = await self.db.execute(
            select(func.max(_Item.step_order)).where(
                _Item.plan_id == plan_id,
                _Item.is_deleted == False,  # noqa: E712
            )
        )
        max_order = res.scalar()
        return (int(max_order) + 1) if max_order is not None else 1

    async def _describe_library_item(
        self, content_id: UUID
    ) -> GeneratedContent:
        """Build a GeneratedContent view over an existing library item."""
        res = await self.db.execute(
            select(ContentItem).where(ContentItem.id == content_id, ContentItem.is_deleted == False)  # noqa: E712
        )
        item = res.scalar_one_or_none()
        if item is None:
            raise ValueError(f"Content item {content_id} not found")
        return GeneratedContent(
            content_item_id=item.id,
            title=item.title,
            body=item.body or "",
            summary=item.summary,
            content_type=item.content_type,
            tags=item.tags or [],
            category=item.category,
            quality=QualityEvaluation(
                score=5.0,
                passed=True,
                threshold=self.evaluator.DEFAULT_THRESHOLD,
                dimensions={},
                issues=["pre-existing library item (not generated)"],
            ),
            strategy="library",
            fallback_used=False,
            fallback_reason=None,
        )

    # ---------- Generation history ----------

    async def get_history(
        self,
        account_id: UUID,
        *,
        source: Optional[str] = None,
        strategy: Optional[str] = None,
        content_id: Optional[UUID] = None,
        nurture_plan_id: Optional[UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> GenerationHistoryResponse:
        """Query the content-generation audit log for an account."""
        if self.db is None:
            raise ValueError("History query requires a DB session")

        query = select(ContentGeneration).where(
            ContentGeneration.account_id == account_id,
            ContentGeneration.is_deleted == False,  # noqa: E712
        )
        if source:
            query = query.where(ContentGeneration.source == source)
        if strategy:
            query = query.where(ContentGeneration.strategy == strategy)
        if content_id:
            query = query.where(ContentGeneration.content_id == content_id)
        if nurture_plan_id:
            query = query.where(ContentGeneration.nurture_plan_id == nurture_plan_id)

        total = (
            await self.db.execute(
                select(func.count()).select_from(query.subquery())
            )
        ).scalar()
        total = int(total or 0)

        rows = (
            await self.db.execute(
                query.order_by(desc(ContentGeneration.created_at))
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()

        items: List[GenerationHistoryItem] = [
            GenerationHistoryItem(
                id=row.id,
                account_id=row.account_id,
                source=row.source,
                content_type=row.content_type,
                strategy=row.strategy,
                fallback_used=row.fallback_used,
                fallback_reason=row.fallback_reason,
                segment_id=row.segment_id,
                stage_code=row.stage_code,
                content_id=row.content_id,
                nurture_plan_id=row.nurture_plan_id,
                plan_step_id=row.plan_step_id,
                quality_score=row.quality_score,
                quality_passed=row.quality_passed,
                input_snapshot=row.input_snapshot or {},
                output_snapshot=row.output_snapshot or {},
                processing_time_ms=row.processing_time_ms,
                created_at=row.created_at,
            )
            for row in rows
        ]
        return GenerationHistoryResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )
