"""Memory Service - Short-term and Long-term Memory System"""
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.memory import Memory, MemoryFragment, ConversationSummary, ContextWindow
from app.schemas.memory import (
    MemoryCreate,
    MemoryUpdate,
    MemoryResponse,
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryInjectionRequest,
    MemoryInjectionResponse,
    ConversationSummaryCreate,
    ConversationSummaryResponse,
)
from app.services.default_intents import INTENT_TYPES

logger = logging.getLogger(__name__)


class MemoryService:
    """Service for managing short-term and long-term memory"""

    # Configuration constants
    MAX_MEMORY_PER_CUSTOMER = 100  # Maximum memories per customer
    MAX_IMPORTANCE_FOR_AUTO_DELETE = 3  # Auto-delete low importance memories
    SUMMARIZATION_TRIGGER_MESSAGES = 20  # Trigger summary after N messages
    CONTEXT_WINDOW_TOKENS = 4000  # Default context window size

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========== Long-term Memory CRUD ==========

    async def create_memory(self, data: MemoryCreate) -> MemoryResponse:
        """Create a new long-term memory"""
        # Check memory limit
        count_result = await self.db.execute(
            select(func.count()).select_from(Memory).where(
                Memory.customer_id == data.customer_id,
                Memory.is_deleted == False
            )
        )
        current_count = count_result.scalar_one()
        
        if current_count >= self.MAX_MEMORY_PER_CUSTOMER:
            # Auto-delete lowest importance memory
            await self._auto_cleanup_old_memories(data.customer_id)

        memory = Memory(
            customer_id=data.customer_id,
            memory_type=data.memory_type,
            category=data.category,
            content=data.content,
            source=data.source,
            importance=data.importance,
            confidence=data.confidence,
            tags=data.tags or [],
            metadata_=data.metadata_,
        )
        self.db.add(memory)
        await self.db.commit()
        await self.db.refresh(memory)
        
        logger.info(f"Created memory: {memory.id} for customer {data.customer_id}")
        return self._to_memory_response(memory)

    async def get_memory(self, memory_id: UUID) -> Optional[MemoryResponse]:
        """Get memory by ID"""
        result = await self.db.execute(
            select(Memory).where(
                Memory.id == memory_id,
                Memory.is_deleted == False
            )
        )
        memory = result.scalar_one_or_none()
        return self._to_memory_response(memory) if memory else None

    async def list_memories(
        self,
        customer_id: UUID,
        memory_type: Optional[str] = None,
        category: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[MemoryResponse], int]:
        """List memories with pagination and filtering"""
        query = select(Memory).where(
            Memory.customer_id == customer_id,
            Memory.is_deleted == False
        )

        if memory_type:
            query = query.where(Memory.memory_type == memory_type)
        if category:
            query = query.where(Memory.category == category)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # Get paginated results
        query = query.order_by(Memory.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        memories = result.scalars().all()

        return [self._to_memory_response(m) for m in memories], total

    async def update_memory(
        self, memory_id: UUID, data: MemoryUpdate
    ) -> Optional[MemoryResponse]:
        """Update memory fields"""
        memory = await self.get_memory(memory_id)
        if not memory:
            return None

        if data.memory_type is not None:
            memory.memory_type = data.memory_type
        if data.category is not None:
            memory.category = data.category
        if data.content is not None:
            memory.content = data.content
        if data.importance is not None:
            memory.importance = data.importance
        if data.confidence is not None:
            memory.confidence = data.confidence
        if data.tags is not None:
            memory.tags = data.tags
        if data.metadata_ is not None:
            memory.metadata_ = data.metadata_

        memory.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(memory)
        
        return self._to_memory_response(memory)

    async def delete_memory(self, memory_id: UUID) -> bool:
        """Soft delete a memory"""
        # Get the actual model, not the response
        result = await self.db.execute(
            select(Memory).where(
                Memory.id == memory_id,
                Memory.is_deleted == False
            )
        )
        memory = result.scalar_one_or_none()
        if not memory:
            return False

        memory.is_deleted = True
        await self.db.commit()
        logger.info(f"Deleted memory: {memory_id}")
        return True

    # ========== Memory Search & Retrieval ==========

    async def search_memories(
        self, request: MemorySearchRequest
    ) -> MemorySearchResponse:
        """Search memories using keyword matching (fallback for vector search)"""
        start_time = time.time()
        
        # Build search query
        query = select(Memory).where(
            Memory.customer_id == request.customer_id,
            Memory.is_deleted == False,
            Memory.content.op('ILIKE')(f"%{request.query}%")
        )

        if request.memory_type:
            query = query.where(Memory.memory_type == request.memory_type)
        if request.category:
            query = query.where(Memory.category == request.category)

        # Order by importance and recency
        query = query.order_by(
            Memory.importance.desc(),
            Memory.created_at.desc()
        )
        query = query.limit(request.limit)

        result = await self.db.execute(query)
        memories = result.scalars().all()

        # Calculate relevance scores (simple keyword matching)
        results = []
        query_terms = request.query.lower().split()
        
        for memory in memories:
            content_lower = memory.content.lower()
            score = sum(1 for term in query_terms if term in content_lower) / len(query_terms)
            
            # Boost by importance
            score *= (memory.importance / 10.0)
            
            # Boost by confidence
            score *= memory.confidence

            if score >= request.relevance_threshold:
                results.append({
                    "id": str(memory.id),
                    "memory_type": memory.memory_type,
                    "category": memory.category,
                    "content": memory.content,
                    "importance": memory.importance,
                    "confidence": memory.confidence,
                    "tags": memory.tags,
                    "created_at": memory.created_at.isoformat(),
                    "relevance_score": round(score, 3),
                })

        search_time_ms = (time.time() - start_time) * 1000

        return MemorySearchResponse(
            query=request.query,
            results=results,
            total=len(results),
            search_time_ms=search_time_ms,
        )

    async def get_relevant_memories(
        self,
        customer_id: UUID,
        conversation_context: str,
        max_count: int = 5,
    ) -> List[Dict[str, Any]]:
        """Get relevant memories for a conversation context"""
        # Defensive: an empty/whitespace-only context has no usable search
        # query (MemorySearchRequest.query has min_length=1), so skip the
        # semantic search instead of raising a ValidationError.
        if not conversation_context or not conversation_context.strip():
            logger.debug(
                "get_relevant_memories: empty context for customer %s, "
                "skipping semantic search",
                customer_id,
            )
            return []

        # First try semantic search with keywords from context
        query = conversation_context[:200].strip()
        if not query:
            return []

        search_request = MemorySearchRequest(
            customer_id=customer_id,
            query=query,  # Use first 200 chars
            limit=max_count * 2,  # Get more to rank
        )
        
        search_result = await self.search_memories(search_request)
        
        # Return top results
        return search_result.results[:max_count]

    # ========== Memory Injection ==========

    async def inject_memories_into_context(
        self, request: MemoryInjectionRequest
    ) -> MemoryInjectionResponse:
        """Inject relevant memories into conversation context"""
        # Get recent messages to understand context
        recent_context = " ".join([
            (msg.get("content", "") or "").strip() for msg in request.recent_messages[-5:]
        ]).strip()

        # Empty / whitespace-only context (e.g. first-round conversation with
        # no recent messages yet) is a legal boundary: there is nothing to
        # search on, so skip the semantic search and return an empty
        # injection instead of letting an empty query hit validation (500).
        if not recent_context:
            logger.debug(
                "memory inject: empty context for conversation %s customer %s, "
                "returning empty injection",
                request.conversation_id,
                request.customer_id,
            )
            return MemoryInjectionResponse(
                conversation_id=request.conversation_id,
                injected_memories=[],
                injection_count=0,
                context_tokens_added=0,
            )

        # Find relevant memories
        relevant_memories = await self.get_relevant_memories(
            customer_id=request.customer_id,
            conversation_context=recent_context,
            max_count=request.max_memory_count,
        )

        # Format memories for injection
        injected_memories = []
        total_tokens = 0
        
        for memory in relevant_memories:
            memory_text = f"[MEMORY] {memory['memory_type']}: {memory['content']}"
            # Rough token estimation (4 chars per token)
            tokens = len(memory_text) // 4
            total_tokens += tokens
            
            injected_memories.append({
                "source": "memory",
                "type": memory["memory_type"],
                "content": memory_text,
                "relevance_score": memory.get("relevance_score", 0),
            })

        return MemoryInjectionResponse(
            conversation_id=request.conversation_id,
            injected_memories=injected_memories,
            injection_count=len(injected_memories),
            context_tokens_added=total_tokens,
        )

    # ========== Short-term Memory (Conversation Summary) ==========

    async def create_conversation_summary(
        self, data: ConversationSummaryCreate
    ) -> ConversationSummaryResponse:
        """Create a conversation summary"""
        summary = ConversationSummary(
            conversation_id=data.conversation_id,
            summary_type=data.summary_type,
            content=data.content,
            key_points=data.key_points or [],
            sentiment=data.sentiment,
            action_items=data.action_items or [],
        )
        self.db.add(summary)
        await self.db.commit()
        await self.db.refresh(summary)
        
        logger.info(f"Created summary: {summary.id} for conversation {data.conversation_id}")
        return self._to_summary_response(summary)

    async def get_conversation_summaries(
        self,
        conversation_id: UUID,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[List[ConversationSummaryResponse], int]:
        """Get conversation summaries with pagination"""
        query = select(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation_id,
            ConversationSummary.is_deleted == False
        ).order_by(ConversationSummary.created_at.desc())

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # Get paginated results
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        summaries = result.scalars().all()

        return [self._to_summary_response(s) for s in summaries], total

    async def auto_generate_summary(
        self,
        conversation_id: UUID,
        messages: List[Dict[str, Any]],
    ) -> Optional[ConversationSummaryResponse]:
        """Auto-generate conversation summary based on messages"""
        if len(messages) < self.SUMMARIZATION_TRIGGER_MESSAGES:
            return None

        # Extract key information
        user_messages = [m for m in messages if m.get("role") == "user"]
        assistant_messages = [m for m in messages if m.get("role") == "assistant"]

        # Create brief summary
        summary_content = f"对话摘要：用户与AI助手进行了{len(messages)}轮对话。"
        if user_messages:
            summary_content += f"\n用户主要问题：{user_messages[-3:].pop().get('content', '')[:100]}..."

        # Extract key points (simplified - in production use LLM)
        key_points = []
        for msg in user_messages[-5:]:
            content = msg.get("content", "")
            if len(content) > 20:
                key_points.append(content[:100] + "...")

        # Determine sentiment (simplified)
        sentiment = "neutral"
        negative_keywords = ["投诉", "不满意", "差", "糟糕", "问题"]
        positive_keywords = ["谢谢", "好的", "完美", "满意", "棒"]
        
        all_content = " ".join([m.get("content", "") for m in messages])
        if any(kw in all_content for kw in negative_keywords):
            sentiment = "negative"
        elif any(kw in all_content for kw in positive_keywords):
            sentiment = "positive"

        # Extract action items
        action_items = []
        for msg in assistant_messages:
            content = msg.get("content", "")
            if "请" in content or "需要" in content:
                action_items.append(content[:100])

        # Create summary
        summary_data = ConversationSummaryCreate(
            conversation_id=conversation_id,
            summary_type="brief",
            content=summary_content,
            key_points=key_points[:5],
            sentiment=sentiment,
            action_items=action_items[:3],
        )

        return await self.create_conversation_summary(summary_data)

    # ========== Context Window Management ==========

    async def get_or_create_context_window(
        self, conversation_id: UUID
    ) -> ContextWindow:
        """Get or create context window for a conversation"""
        result = await self.db.execute(
            select(ContextWindow).where(
                ContextWindow.conversation_id == conversation_id
            )
        )
        window = result.scalar_one_or_none()

        if not window:
            window = ContextWindow(
                conversation_id=conversation_id,
                max_tokens=self.CONTEXT_WINDOW_TOKENS,
            )
            self.db.add(window)
            await self.db.commit()
            await self.db.refresh(window)

        return window

    async def update_context_window(
        self, conversation_id: UUID, token_count: int
    ) -> ContextWindow:
        """Update context window token count"""
        window = await self.get_or_create_context_window(conversation_id)
        window.current_tokens = token_count
        window.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(window)
        return window

    async def check_compression_needed(
        self, conversation_id: UUID
    ) -> Dict[str, Any]:
        """Check if conversation needs compression"""
        window = await self.get_or_create_context_window(conversation_id)
        
        if not window or not hasattr(window, 'current_tokens') or not hasattr(window, 'max_tokens'):
            return {
                "conversation_id": conversation_id,
                "current_tokens": 0,
                "max_tokens": self.CONTEXT_WINDOW_TOKENS,
                "usage_percentage": 0.0,
                "needs_compression": False,
                "compressed_count": 0,
            }
        
        current_tokens = getattr(window, 'current_tokens', 0) or 0
        max_tokens = getattr(window, 'max_tokens', self.CONTEXT_WINDOW_TOKENS) or self.CONTEXT_WINDOW_TOKENS
        
        return {
            "conversation_id": conversation_id,
            "current_tokens": current_tokens,
            "max_tokens": max_tokens,
            "usage_percentage": round((current_tokens / max_tokens) * 100, 2),
            "needs_compression": current_tokens > max_tokens * 0.8,
            "compressed_count": getattr(window, 'compressed_count', 0),
        }

    # ========== Memory Statistics ==========

    async def get_memory_statistics(
        self, customer_id: UUID
    ) -> Dict[str, Any]:
        """Get memory statistics for a customer"""
        # Count by type
        type_counts = {}
        for mem_type in ["preference", "fact", "history", "insight"]:
            result = await self.db.execute(
                select(func.count()).select_from(Memory).where(
                    Memory.customer_id == customer_id,
                    Memory.memory_type == mem_type,
                    Memory.is_deleted == False
                )
            )
            type_counts[mem_type] = result.scalar_one()

        # Count by category
        category_counts = {}
        for category in ["general", "product", "service", "personal"]:
            result = await self.db.execute(
                select(func.count()).select_from(Memory).where(
                    Memory.customer_id == customer_id,
                    Memory.category == category,
                    Memory.is_deleted == False
                )
            )
            category_counts[category] = result.scalar_one()

        # Total count
        total_result = await self.db.execute(
            select(func.count()).select_from(Memory).where(
                Memory.customer_id == customer_id,
                Memory.is_deleted == False
            )
        )
        total = total_result.scalar_one()

        # Average importance
        avg_importance_result = await self.db.execute(
            select(func.avg(Memory.importance)).select_from(Memory).where(
                Memory.customer_id == customer_id,
                Memory.is_deleted == False
            )
        )
        avg_importance = avg_importance_result.scalar_one() or 0

        return {
            "customer_id": customer_id,
            "total_memories": total,
            "type_counts": type_counts,
            "category_counts": category_counts,
            "average_importance": round(avg_importance, 2),
            "memory_ratio": total / self.MAX_MEMORY_PER_CUSTOMER if self.MAX_MEMORY_PER_CUSTOMER > 0 else 0,
        }

    # ========== Private Methods ==========

    async def _auto_cleanup_old_memories(self, customer_id: UUID):
        """Auto-cleanup old/low-importance memories when limit reached"""
        # Delete lowest importance memories first
        result = await self.db.execute(
            select(Memory.id).where(
                Memory.customer_id == customer_id,
                Memory.is_deleted == False,
                Memory.importance <= self.MAX_IMPORTANCE_FOR_AUTO_DELETE
            ).order_by(Memory.importance.asc(), Memory.created_at.asc())
        )
        old_ids = [row[0] for row in result.fetchall()]

        if old_ids:
            await self.db.execute(
                update(Memory)
                .where(Memory.id.in_(old_ids[:5]))  # Delete at most 5
                .values(is_deleted=True)
            )
            await self.db.commit()
            logger.info(f"Auto-cleaned {len(old_ids[:5])} old memories for customer {customer_id}")

    def _to_memory_response(self, memory: Memory) -> MemoryResponse:
        """Convert model to response schema"""
        return MemoryResponse(
            id=memory.id,
            customer_id=memory.customer_id,
            memory_type=memory.memory_type,
            category=memory.category,
            content=memory.content,
            source=memory.source,
            importance=memory.importance,
            confidence=memory.confidence,
            tags=memory.tags,
            metadata=memory.metadata_,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )

    def _to_summary_response(self, summary: ConversationSummary) -> ConversationSummaryResponse:
        """Convert summary model to response schema"""
        return ConversationSummaryResponse(
            id=summary.id,
            conversation_id=summary.conversation_id,
            summary_type=summary.summary_type,
            content=summary.content,
            key_points=summary.key_points,
            sentiment=summary.sentiment,
            action_items=summary.action_items,
            created_at=summary.created_at,
        )
