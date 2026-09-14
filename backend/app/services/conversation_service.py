"""Conversation Service - CRUD and history management"""
import asyncio
from datetime import datetime, timezone
from typing import List, Literal, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func, update, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.conversation import Conversation, Message
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    MessageUpdate,
    ConversationResponse,
    MessageResponse,
    ConversationStats,
    RedoResponse,
)


class ConversationService:
    """Service for managing conversations and messages"""

    # Context window limits
    MAX_MESSAGES_PER_CONVERSATION = 100  # Maximum messages to keep in context
    MAX_CONTEXT_TOKENS = 4000  # Maximum tokens in context window
    MAX_EDIT_COUNT = 3  # 最大编辑次数

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========== Conversation CRUD ==========

    async def create_conversation(self, data: ConversationCreate) -> ConversationResponse:
        """Create a new conversation"""
        conversation = Conversation(
            customer_id=data.customer_id,
            channel=data.channel,
            subject=data.subject,
            status=data.status,
            summary=data.summary,
            sentiment=data.sentiment,
            tags=data.tags or [],
            metadata_=data.metadata_,
        )
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)

        # Initialize message count
        conversation.message_count = 0
        await self.db.commit()

        return self._to_conversation_response(conversation)

    async def get_conversation(self, conversation_id: UUID) -> Optional[ConversationResponse]:
        """Get conversation by ID"""
        conversation = await self._get_by_id(conversation_id)
        if not conversation:
            return None
        return self._to_conversation_response(conversation)

    async def list_conversations(
        self,
        customer_id: Optional[UUID] = None,
        status: Optional[str] = None,
        channel: Optional[str] = None,
        search: Optional[str] = None,
        sort: str = "last_message_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[ConversationResponse], int]:
        """List conversations with pagination, filtering, search and sorting.

        - ``status="deleted"`` queries soft-deleted conversations (is_deleted=True);
          any other value filters by real status and implicitly is_deleted=False.
        - ``search`` performs an ILIKE fuzzy match on ``subject``.
        - ``sort`` is ``created_at`` or ``last_message_at`` (default last_message_at);
          ``order`` is ``asc`` or ``desc`` (default desc). NULL sort values
          (conversations with no messages) always sort to the end.
        """
        is_deleted_filter = True if status == "deleted" else False
        query = select(Conversation).where(Conversation.is_deleted == is_deleted_filter)

        if customer_id:
            query = query.where(Conversation.customer_id == customer_id)
        if status and status != "deleted":
            query = query.where(Conversation.status == status)
        if channel:
            query = query.where(Conversation.channel == channel)
        if search:
            query = query.where(text("LOWER(conversation.subject) LIKE LOWER(:search)")).params(search=f"%{search}%")

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # Get paginated results with configurable sort (NULLs last)
        sort_col = Conversation.last_message_at if sort == "last_message_at" else Conversation.created_at
        if order == "asc":
            query = query.order_by(sort_col.asc().nulls_last())
        else:
            query = query.order_by(sort_col.desc().nulls_last())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        conversations = result.scalars().all()

        return [self._to_conversation_response(conv) for conv in conversations], total

    async def update_conversation(
        self, conversation_id: UUID, data: ConversationUpdate
    ) -> Optional[ConversationResponse]:
        """Update conversation fields"""
        conversation = await self._get_by_id(conversation_id)
        if not conversation:
            return None

        if data.subject is not None:
            conversation.subject = data.subject
        if data.status is not None:
            conversation.status = data.status
        if data.summary is not None:
            conversation.summary = data.summary
        if data.sentiment is not None:
            conversation.sentiment = data.sentiment
        if data.duration_seconds is not None:
            conversation.duration_seconds = data.duration_seconds
        if data.tags is not None:
            conversation.tags = data.tags
        if data.metadata_ is not None:
            conversation.metadata_ = data.metadata_

        conversation.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(conversation)

        return self._to_conversation_response(conversation)

    async def delete_conversation(self, conversation_id: UUID) -> bool:
        """Soft delete a conversation and all its messages"""
        conversation = await self._get_by_id(conversation_id)
        if not conversation:
            return False

        conversation.is_deleted = True
        await self.db.commit()
        return True

    async def restore_conversation(self, conversation_id: UUID) -> Optional[ConversationResponse]:
        """Restore a soft-deleted conversation.

        Reverts ``is_deleted`` to False and sets ``status`` back to active.
        Returns None if the conversation does not exist (caller raises 404).
        """
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            return None

        conversation.is_deleted = False
        conversation.status = "active"
        conversation.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(conversation)

        return self._to_conversation_response(conversation)

    async def update_conversation_message_stats(self, conversation_id: UUID) -> None:
        """Update conversation message_count and last_message_at"""
        # Update message count
        count_result = await self.db.execute(
            select(func.count()).select_from(Message).where(
                Message.conversation_id == conversation_id,
                Message.is_deleted == False
            )
        )
        message_count = count_result.scalar_one()

        # Update last message time
        last_result = await self.db.execute(
            select(func.max(Message.created_at)).where(
                Message.conversation_id == conversation_id,
                Message.is_deleted == False
            )
        )
        last_message_at = last_result.scalar_one()

        # Update conversation
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(message_count=message_count, last_message_at=last_message_at)
        )
        await self.db.commit()

    # ========== Message CRUD ==========

    async def create_message(self, data: MessageCreate) -> MessageResponse:
        """Create a new message"""
        # Verify conversation exists
        conversation = await self._get_by_id(data.conversation_id)
        if not conversation:
            raise ValueError(f"Conversation not found: {data.conversation_id}")

        # Validate role
        if data.role not in ("user", "assistant", "system"):
            raise ValueError(f"Invalid role: {data.role}")

        # Sanitize content (already done in schema validator)
        message = Message(
            conversation_id=data.conversation_id,
            parent_id=data.parent_id,
            role=data.role,
            content=data.content,
            metadata_=data.metadata_,
        )
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)

        # Auto-subject: if the conversation has no subject and this is a user
        # message, use the first 80 characters of content as the title.
        if not conversation.subject and data.role == "user":
            conversation.subject = data.content[:80]
            await self.db.commit()

        # Update conversation stats
        await self.update_conversation_message_stats(data.conversation_id)

        return self._to_message_response(message)

    async def get_message(self, message_id: UUID) -> Optional[MessageResponse]:
        """Get message by ID"""
        result = await self.db.execute(
            select(Message).where(
                Message.id == message_id,
                Message.is_deleted == False
            )
        )
        message = result.scalar_one_or_none()
        return self._to_message_response(message) if message else None

    async def list_messages(
        self,
        conversation_id: UUID,
        role: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Tuple[List[MessageResponse], int]:
        """List messages with pagination and filtering"""
        # Verify conversation exists
        conversation = await self._get_by_id(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation not found: {conversation_id}")

        query = select(Message).where(
            Message.conversation_id == conversation_id,
            Message.is_deleted == False
        )

        if role:
            query = query.where(Message.role == role)
        if start_time:
            query = query.where(Message.created_at >= start_time)
        if end_time:
            query = query.where(Message.created_at <= end_time)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # Get paginated results - order by time ascending
        query = query.order_by(Message.created_at.asc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        messages = result.scalars().all()

        return [self._to_message_response(m) for m in messages], total

    async def update_message(
        self, message_id: UUID, data: MessageUpdate
    ) -> Optional[MessageResponse]:
        """Update message content with edit count limit"""
        result = await self.db.execute(
            select(Message).where(
                Message.id == message_id,
                Message.is_deleted == False
            )
        )
        message = result.scalar_one_or_none()
        if not message:
            return None

        # Check edit count limit
        if message.edit_count >= self.MAX_EDIT_COUNT:
            raise ValueError(f"Message can only be edited {self.MAX_EDIT_COUNT} times")

        # Validate role - only user messages can be edited
        if message.role != "user":
            raise ValueError("Only user messages can be edited")

        if data.content is not None:
            message.content = data.content
            message.edit_count += 1
        if data.metadata_ is not None:
            message.metadata_ = data.metadata_

        message.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(message)

        return self._to_message_response(message)

    async def delete_message(self, message_id: UUID) -> bool:
        """Soft delete a message"""
        result = await self.db.execute(
            select(Message).where(
                Message.id == message_id,
                Message.is_deleted == False
            )
        )
        message = result.scalar_one_or_none()
        if not message:
            return False

        message.is_deleted = True
        await self.db.commit()

        # Update conversation stats
        await self.update_conversation_message_stats(message.conversation_id)
        return True

    async def batch_delete_messages(
        self, conversation_id: UUID, message_ids: List[UUID]
    ) -> int:
        """Batch soft delete messages"""
        # Verify conversation exists
        conversation = await self._get_by_id(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation not found: {conversation_id}")

        if not message_ids:
            return 0

        result = await self.db.execute(
            update(Message)
            .where(
                Message.id.in_(message_ids),
                Message.conversation_id == conversation_id,
                Message.is_deleted == False
            )
            .values(is_deleted=True)
        )
        deleted_count = result.rowcount
        await self.db.commit()

        if deleted_count > 0:
            await self.update_conversation_message_stats(conversation_id)

        return deleted_count

    async def redo_message(
        self, conversation_id: UUID, message_id: UUID
    ) -> RedoResponse:
        """Redo (regenerate) an assistant message"""
        # Verify conversation exists
        conversation = await self._get_by_id(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation not found: {conversation_id}")

        # Get the message to redo
        result = await self.db.execute(
            select(Message).where(
                Message.id == message_id,
                Message.conversation_id == conversation_id,
                Message.is_deleted == False
            )
        )
        message = result.scalar_one_or_none()
        if not message:
            raise ValueError(f"Message not found: {message_id}")

        # Only assistant messages can be redone
        if message.role != "assistant":
            raise ValueError("Only assistant messages can be redone")

        # Soft delete the old message
        message.is_deleted = True
        await self.db.commit()

        # Create new message with same content but as new
        new_message = Message(
            conversation_id=conversation_id,
            parent_id=message_id,  # Link to original
            role=message.role,
            content=message.content,  # Same content, will be regenerated by AI
            metadata_={**message.metadata_, "redo_of": str(message_id)} if message.metadata_ else {"redo_of": str(message_id)},
        )
        self.db.add(new_message)
        await self.db.commit()
        await self.db.refresh(new_message)

        # Update conversation stats
        await self.update_conversation_message_stats(conversation_id)

        return RedoResponse(
            original_id=message_id,
            new_id=new_message.id,
            original_role=message.role,
            new_content=message.content,
            status="success",
            created_at=new_message.created_at,
        )

    # ========== Conversation History & Context Window ==========

    async def get_conversation_history(
        self,
        conversation_id: UUID,
        limit: int = 20,
        include_summary: bool = True,
    ) -> List[MessageResponse]:
        """
        Get conversation history within context window limits.
        Returns the most recent messages up to the limit.
        """
        messages, total = await self.list_messages(conversation_id, page_size=limit)

        # If we have more messages than the limit, apply context window logic
        if total > limit:
            # Get the oldest message we're keeping
            oldest_message = messages[0] if messages else None

            # Build history with summary if needed
            if include_summary and oldest_message:
                # Get summary from conversation
                conversation = await self._get_by_id(conversation_id)
                if conversation and conversation.summary:
                    # Insert summary as a system message at the beginning
                    summary_message = MessageResponse(
                        id=UUID(int=0),  # Special ID for synthetic message
                        conversation_id=conversation_id,
                        role="system",
                        content=f"[Conversation Summary]\n{conversation.summary}",
                        metadata_={"is_summary": True},
                        created_at=conversation.created_at,
                    )
                    messages = [summary_message] + messages

        return messages

    async def compress_conversation_history(
        self, conversation_id: UUID, max_tokens: int = 4000
    ) -> dict:
        """
        Compress conversation history by summarizing older messages.
        Returns compression stats.
        """
        # Get all messages
        messages, total = await self.list_messages(conversation_id, page_size=1000)

        if len(messages) <= self.MAX_MESSAGES_PER_CONVERSATION:
            return {
                "compressed": False,
                "reason": "Already within limits",
                "total_messages": total,
            }

        # Calculate how many messages to keep
        keep_count = min(self.MAX_MESSAGES_PER_CONVERSATION, len(messages))
        compress_count = len(messages) - keep_count

        # Mark old messages for archival (not deletion)
        old_messages = messages[:compress_count]
        for msg in old_messages:
            # Store compressed reference in metadata
            if msg.metadata_ is None:
                msg.metadata_ = {}
            msg.metadata_["archived"] = True
            msg.metadata_["compressed_at"] = datetime.now(timezone.utc).isoformat()

        # Update conversation summary
        conversation = await self._get_by_id(conversation_id)
        if conversation:
            # Create a brief summary of compressed messages
            summary = f"[Compressed {compress_count} older messages]"
            if not conversation.summary:
                conversation.summary = summary
            else:
                conversation.summary = f"{conversation.summary}\n{summary}"

        await self.db.commit()

        return {
            "compressed": True,
            "compressed_count": compress_count,
            "remaining_messages": keep_count,
            "total_messages": total,
        }

    async def get_context_window(
        self,
        conversation_id: UUID,
        max_tokens: int = 4000,
    ) -> dict:
        """
        Get current context window status.
        Returns context information and available space.
        """
        messages, total = await self.list_messages(conversation_id, page_size=100)

        # Estimate token count (rough approximation: 4 chars per token)
        estimated_tokens = sum(len(m.content) // 4 for m in messages)

        return {
            "conversation_id": conversation_id,
            "total_messages": total,
            "context_messages": len(messages),
            "estimated_tokens": estimated_tokens,
            "max_tokens": max_tokens,
            "available_tokens": max(0, max_tokens - estimated_tokens),
            "needs_compression": estimated_tokens > max_tokens,
        }

    # ========== Conversation Stats ==========

    async def get_conversation_stats(self, conversation_id: UUID) -> Optional[ConversationStats]:
        """Get conversation statistics"""
        conversation = await self._get_by_id(conversation_id)
        if not conversation:
            return None

        # Count messages by role
        user_count = await self._count_messages(conversation_id, "user")
        assistant_count = await self._count_messages(conversation_id, "assistant")
        system_count = await self._count_messages(conversation_id, "system")

        # Get first and last message timestamps
        first_result = await self.db.execute(
            select(func.min(Message.created_at)).where(
                Message.conversation_id == conversation_id,
                Message.is_deleted == False
            )
        )
        first_message_at = first_result.scalar_one()

        last_result = await self.db.execute(
            select(func.max(Message.created_at)).where(
                Message.conversation_id == conversation_id,
                Message.is_deleted == False
            )
        )
        last_message_at = last_result.scalar_one()

        # Calculate average response time (time between user and assistant messages)
        avg_response_time = await self._calculate_avg_response_time(conversation_id)

        return ConversationStats(
            conversation_id=conversation_id,
            total_messages=user_count + assistant_count + system_count,
            user_messages=user_count,
            assistant_messages=assistant_count,
            system_messages=system_count,
            first_message_at=first_message_at,
            last_message_at=last_message_at,
            avg_response_time_seconds=avg_response_time,
        )

    # ========== Private Methods ==========

    async def _get_by_id(self, conversation_id: UUID) -> Optional[Conversation]:
        """Get conversation by ID"""
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.is_deleted == False
            )
        )
        return result.scalar_one_or_none()

    async def _count_messages(
        self, conversation_id: UUID, role: Optional[str] = None
    ) -> int:
        """Count messages for a conversation, optionally filtered by role"""
        query = select(func.count()).select_from(Message).where(
            Message.conversation_id == conversation_id,
            Message.is_deleted == False
        )
        if role:
            query = query.where(Message.role == role)

        result = await self.db.execute(query)
        return result.scalar_one()

    async def _calculate_avg_response_time(
        self, conversation_id: UUID
    ) -> Optional[float]:
        """Calculate average response time between user and assistant messages"""
        # Get ordered messages
        result = await self.db.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.is_deleted == False
            ).order_by(Message.created_at.asc())
        )
        messages = result.scalars().all()

        if len(messages) < 2:
            return None

        # Calculate response times
        response_times = []
        for i in range(len(messages) - 1):
            if messages[i].role == "user" and messages[i + 1].role == "assistant":
                delta = (messages[i + 1].created_at - messages[i].created_at).total_seconds()
                response_times.append(delta)

        if not response_times:
            return None

        return sum(response_times) / len(response_times)

    def _to_conversation_response(
        self, conversation: Conversation
    ) -> ConversationResponse:
        """Convert model to response schema"""
        return ConversationResponse(
            id=conversation.id,
            customer_id=conversation.customer_id,
            channel=conversation.channel,
            subject=conversation.subject,
            status=conversation.status,
            summary=conversation.summary,
            sentiment=conversation.sentiment,
            duration_seconds=conversation.duration_seconds,
            tags=conversation.tags,
            metadata=conversation.metadata_,
            message_count=conversation.message_count,
            last_message_at=conversation.last_message_at,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )

    def _to_message_response(self, message: Message) -> MessageResponse:
        """Convert model to response schema"""
        return MessageResponse(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            parent_id=message.parent_id,
            edit_count=message.edit_count,
            metadata=message.metadata_,
            created_at=message.created_at,
            updated_at=message.updated_at,
        )
