"""Conversation Router - CRUD API endpoints"""
import json
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationListResponse,
    MessageCreate,
    MessageUpdate,
    MessageResponse,
    MessageListResponse,
    ConversationStats,
    RedoResponse,
)
from app.services.conversation_service import ConversationService
from app.services.ai.agent_service import AIAgentService, TokenUsage
from app.services.ai.exceptions import ProviderError, ProviderUnavailableError
from app.events.domain_events import DomainEvent, get_event_bus
import logging
from uuid import UUID

logger = logging.getLogger(__name__)


async def _publish_domain_event(
    event_type: str,
    entity_type: str,
    entity_id: Optional[UUID],
    payload: dict,
) -> None:
    """Publish a conversation domain event on the shared bus.

    The bus isolates subscribers (a handler crash never breaks the
    publisher's request); this wrapper additionally guards the publish
    call itself so the business response is never lost to a bus hiccup.
    Payloads carry ids, roles, intent type/confidence and channel — never
    message text or credentials (ARCHITECTURE.md #16).
    """
    try:
        event = DomainEvent(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
        await get_event_bus().publish(event)
    except Exception:
        logger.exception("Failed to publish %s domain event", event_type)


router = APIRouter(prefix="/conversations", tags=["Conversations"])


def get_conversation_service(
    db: AsyncSession = Depends(get_db),
) -> ConversationService:
    """Dependency for ConversationService"""
    return ConversationService(db)


class BatchDeleteRequest(BaseModel):
    """Request body for batch delete messages"""
    message_ids: List[UUID]


# ========== Conversation Endpoints ==========

@router.get("/", response_model=ConversationListResponse)
async def list_conversations(
    customer_id: Optional[UUID] = Query(None, description="Filter by customer ID"),
    status: Optional[str] = Query(None, description="Filter by status (active/closed/archived/deleted)"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    search: Optional[str] = Query(None, description="Fuzzy search on conversation subject (ILIKE)"),
    sort: str = Query("last_message_at", description="Sort field: created_at or last_message_at"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    service: ConversationService = Depends(get_conversation_service),
):
    """List conversations with pagination, filtering, search and sorting.

    - ``status=deleted`` returns soft-deleted conversations; otherwise only
      live conversations are returned.
    - Default order: ``last_message_at`` descending, conversations with no
      messages (NULL) sorted last.
    """
    if sort not in ("created_at", "last_message_at"):
        raise HTTPException(status_code=400, detail="Invalid sort field: use created_at or last_message_at")
    if order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="Invalid order: use asc or desc")

    conversations, total = await service.list_conversations(
        customer_id=customer_id,
        status=status,
        channel=channel,
        search=search,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )
    return ConversationListResponse(
        items=conversations,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: ConversationCreate,
    service: ConversationService = Depends(get_conversation_service),
):
    """Create a new conversation"""
    conv = await service.create_conversation(data)
    # Emit the domain event so event-triggered workflows can react
    # (follow-up, auto-conversation branches). Payload carries no message
    # text — only ids, customer and channel context.
    await _publish_domain_event(
        "conversation.created",
        entity_type="conversation",
        entity_id=conv.id,
        payload={
            "customer_id": str(conv.customer_id),
            "channel": conv.channel,
        },
    )
    return conv


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    service: ConversationService = Depends(get_conversation_service),
):
    """Get conversation by ID"""
    conversation = await service.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.put("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: UUID,
    data: ConversationUpdate,
    service: ConversationService = Depends(get_conversation_service),
):
    """Update conversation"""
    conversation = await service.update_conversation(conversation_id, data)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    service: ConversationService = Depends(get_conversation_service),
):
    """Soft delete a conversation"""
    success = await service.delete_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return None


@router.post("/{conversation_id}/restore", response_model=ConversationResponse)
async def restore_conversation(
    conversation_id: UUID,
    service: ConversationService = Depends(get_conversation_service),
):
    """Restore a soft-deleted conversation (is_deleted=False, status=active)"""
    conversation = await service.restore_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("/{conversation_id}/stats", response_model=ConversationStats)
async def get_conversation_stats(
    conversation_id: UUID,
    service: ConversationService = Depends(get_conversation_service),
):
    """Get conversation statistics"""
    stats = await service.get_conversation_stats(conversation_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return stats


# ========== Message Endpoints ==========

@router.post("/{conversation_id}/messages", response_model=MessageResponse, status_code=201)
async def create_message(
    conversation_id: UUID,
    data: MessageCreate,
    service: ConversationService = Depends(get_conversation_service),
):
    """Create a new message in a conversation"""
    if data.conversation_id != conversation_id:
        raise HTTPException(status_code=400, detail="Conversation ID mismatch")
    try:
        msg = await service.create_message(data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    # Emit the domain event so event-triggered workflows can react
    # (auto-reply, follow-up, intent-driven branches). The payload carries
    # no message text — only ids, role and channel context.
    await _publish_domain_event(
        "message.created",
        entity_type="message",
        entity_id=msg.id,
        payload={
            "conversation_id": str(conversation_id),
            "message_id": str(msg.id),
            "role": msg.role,
        },
    )
    return msg


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: UUID,
    role: Optional[str] = Query(None, description="Filter by role (user/assistant/system)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Page size"),
    start_time: Optional[datetime] = Query(None, description="Filter messages after this time"),
    end_time: Optional[datetime] = Query(None, description="Filter messages before this time"),
    service: ConversationService = Depends(get_conversation_service),
):
    """List messages in a conversation with pagination and filtering"""
    try:
        messages, total = await service.list_messages(
            conversation_id=conversation_id,
            role=role,
            page=page,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
        )
        return MessageListResponse(
            items=messages,
            total=total,
            page=page,
            page_size=page_size,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{conversation_id}/messages", response_model=dict)
async def batch_delete_messages(
    conversation_id: UUID,
    data: BatchDeleteRequest,
    service: ConversationService = Depends(get_conversation_service),
):
    """Batch delete messages in a conversation"""
    try:
        deleted_count = await service.batch_delete_messages(conversation_id, data.message_ids)
        return {"deleted": deleted_count, "message_ids": data.message_ids}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/messages/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: UUID,
    service: ConversationService = Depends(get_conversation_service),
):
    """Get message by ID"""
    message = await service.get_message(message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


@router.put("/messages/{message_id}", response_model=MessageResponse)
async def update_message(
    message_id: UUID,
    data: MessageUpdate,
    service: ConversationService = Depends(get_conversation_service),
):
    """Update message (max 3 edits, user role only)"""
    try:
        message = await service.update_message(message_id, data)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        return message
    except ValueError as e:
        error_detail = str(e)
        if "only be edited" in error_detail:
            raise HTTPException(status_code=400, detail=error_detail)
        elif "Only user messages" in error_detail:
            raise HTTPException(status_code=403, detail=error_detail)
        raise HTTPException(status_code=404, detail=error_detail)


@router.delete("/messages/{message_id}", status_code=204)
async def delete_message(
    message_id: UUID,
    service: ConversationService = Depends(get_conversation_service),
):
    """Soft delete a message"""
    success = await service.delete_message(message_id)
    if not success:
        raise HTTPException(status_code=404, detail="Message not found")
    return None


@router.post("/{conversation_id}/messages/{message_id}/redo", response_model=RedoResponse)
async def redo_message(
    conversation_id: UUID,
    message_id: UUID,
    service: ConversationService = Depends(get_conversation_service),
):
    """Redo (regenerate) an assistant message"""
    try:
        result = await service.redo_message(conversation_id, message_id)
        return result
    except ValueError as e:
        error_detail = str(e)
        if "not found" in error_detail:
            raise HTTPException(status_code=404, detail=error_detail)
        elif "Only assistant messages" in error_detail:
            raise HTTPException(status_code=400, detail=error_detail)
        raise HTTPException(status_code=404, detail=error_detail)


# ========== History & Context Window ==========

@router.get("/{conversation_id}/messages/history", response_model=List[MessageResponse])
async def get_conversation_history(
    conversation_id: UUID,
    limit: int = Query(20, ge=1, le=100, description="Number of recent messages"),
    include_summary: bool = Query(True, description="Include conversation summary"),
    service: ConversationService = Depends(get_conversation_service),
):
    """Get conversation history within context window"""
    try:
        messages = await service.get_conversation_history(
            conversation_id=conversation_id,
            limit=limit,
            include_summary=include_summary,
        )
        return messages
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{conversation_id}/context-window")
async def get_context_window(
    conversation_id: UUID,
    max_tokens: int = Query(4000, ge=100, le=10000, description="Maximum tokens"),
    service: ConversationService = Depends(get_conversation_service),
):
    """Get current context window status"""
    try:
        return await service.get_context_window(
            conversation_id=conversation_id,
            max_tokens=max_tokens,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{conversation_id}/compress")
async def compress_conversation_history(
    conversation_id: UUID,
    max_tokens: int = Query(4000, ge=100, le=10000, description="Maximum tokens"),
    service: ConversationService = Depends(get_conversation_service),
):
    """Compress conversation history"""
    try:
        return await service.compress_conversation_history(
            conversation_id=conversation_id,
            max_tokens=max_tokens,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ========== Chat Endpoints (AI Provider integration, P1-003) ==========


def _new_agent_service() -> AIAgentService:
    """Create the agent service for this request.

    Isolated helper so tests can patch ``chat_stream``/``chat``'s reference
    to the service factory without touching the global config files.
    """
    return AIAgentService()


def _build_provider_messages(
    history: List[MessageResponse],
    user_message_text: str,
) -> List[Dict[str, str]]:
    """Chronological provider transcript: existing history + the new user message.

    ``history`` is returned by ``ConversationService.list_messages`` in
    ascending (oldest-first) order, so it is used as-is.  Synthetic
    context-window summary markers (``metadata_["is_summary"]``) are
    skipped; the new user message is appended last.
    """
    provider_messages: List[Dict[str, str]] = []
    for msg in history:
        if msg.role not in ("user", "assistant", "system"):
            continue
        if (msg.metadata_ or {}).get("is_summary"):
            # synthetic context-window summary marker — not a real transcript message
            continue
        provider_messages.append({"role": msg.role, "content": msg.content or ""})
    provider_messages.append({"role": "user", "content": user_message_text})
    return provider_messages


class ChatRequest(BaseModel):
    """Body for the non-stream chat endpoint: the user message plus an
    optional provider/model override."""

    message: str = Field(..., min_length=1, description="User message")
    provider: Optional[str] = Field(None, description="Override the default provider")
    model: Optional[str] = Field(None, description="Override the provider model")


def _sse(event: Dict[str, Any]) -> str:
    """Frame an event dict as a single SSE data line."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _usage_from_dict(usage: Dict[str, Any]) -> Dict[str, int]:
    """Normalise a TokenUsage.as_dict() payload for the response body."""
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total": int(usage.get("total") or 0),
    }


@router.post("/{conversation_id}/chat/stream")
async def chat_stream(
    conversation_id: UUID,
    message: str = Query(..., description="User message to process"),
    provider: Optional[str] = Query(None, description="Override the default provider"),
    model: Optional[str] = Query(None, description="Override the provider model"),
    service: ConversationService = Depends(get_conversation_service),
):
    """Stream an AI response via SSE backed by the configured AI providers.

    Event sequence (compatible with the pre-P1-003 SSE contract):
    ``conversation_id → chunk(s) → message_saved → done``.  On failure an
    ``{"type": "error", "error": ...}`` event is emitted and the assistant
    message is persisted with ``status=error`` in its metadata (or the
    partial result with ``status=error`` annotation when a timeout left
    partial content).  The user message is persisted first with
    ``status=pending`` before the stream is triggered.
    """
    try:
        conversation = await service._get_by_id(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    agent_service = _new_agent_service()

    # Build the provider transcript from PRE-EXISTING history first, so the
    # transcript does not duplicate the user message we persist below.
    try:
        history, _ = await service.list_messages(
            conversation_id, page=1, page_size=20,
        )
    except ValueError:
        history = []
    provider_messages = _build_provider_messages(history, message)

    # Persist the user message (status=pending), then trigger the stream.
    user_message_data = MessageCreate(
        conversation_id=conversation_id,
        role="user",
        content=message,
        metadata={"status": "pending", "stream": True},
    )
    user_message = await service.create_message(user_message_data)

    async def generate_events() -> AsyncGenerator[str, None]:
        yield _sse({"type": "conversation_id", "id": str(conversation_id)})

        # Stream chunks from the provider (AIAgentService handles selection,
        # token accounting, backoff and degradation).
        result_meta: Dict[str, Any] = {}
        emitted_chunk_count = 0
        async for event in agent_service.generate_stream(
            conversation,
            provider_messages,
            provider=provider,
            model=model,
        ):
            if event.get("type") == "chunk":
                emitted_chunk_count += 1
                yield _sse({
                    "type": "chunk",
                    "content": event["content"],
                    "index": event["index"],
                })
            elif event.get("type") == "result":
                result_meta = event

        accumulated = result_meta.get("accumulated_content") or ""
        usage = TokenUsage(
            prompt_tokens=result_meta.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=result_meta.get("usage", {}).get("completion_tokens", 0),
        ) if result_meta.get("usage") else None
        stream_error = result_meta.get("error")
        partial = bool(accumulated)

        if stream_error and not partial:
            # Complete failure: emit the error event and persist the
            # assistant message with status=error.
            yield _sse({"type": "error", "error": stream_error})
            error_metadata = AIAgentService.build_message_metadata(
                status="error",
                provider=result_meta.get("provider"),
                model=result_meta.get("model") or model,
                usage=usage,
                latency_ms=result_meta.get("latency_ms", 0),
                stream=True,
                error=stream_error,
            )
            if emitted_chunk_count:
                saved_content = accumulated
            else:
                saved_content = f"[ai-error] {stream_error}"
            saved_message = await service.create_message(MessageCreate(
                conversation_id=conversation_id,
                role="assistant",
                content=saved_content,
                metadata=error_metadata,
            ))
            event = {
                "type": "message_saved",
                "id": str(saved_message.id),
                "content": saved_message.content,
                "created_at": saved_message.created_at.isoformat(),
            }
            yield _sse(event)
            yield _sse({"type": "done"})
            return

        # Success (or timeout with partial content): persist the assistant
        # message, then finalize the user message's status.  If a timeout
        # or error left NO content, fall back to a placeholder body so the
        # MessageCreate min_length=1 constraint holds.
        assistant_metadata = AIAgentService.build_message_metadata(
            status="error" if stream_error else "success",
            provider=result_meta.get("provider"),
            model=result_meta.get("model") or model,
            usage=usage,
            latency_ms=result_meta.get("latency_ms", 0),
            stream=True,
            error=stream_error,
        )
        assistant_content = accumulated or (
            "[ai-timeout] stream ended without content" if stream_error else "[ai-error] no response"
        )
        saved_message = await service.create_message(MessageCreate(
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_content,
            metadata=assistant_metadata,
        ))
        event = {
            "type": "message_saved",
            "id": str(saved_message.id),
            "content": saved_message.content,
            "created_at": saved_message.created_at.isoformat(),
        }
        yield _sse(event)

        # Finalize the user message's metadata: pending → success.
        try:
            await service.update_message(
                user_message.id,
                MessageUpdate(metadata={"status": "success", "stream": True}),
            )
        except Exception:
            logger.exception("Failed to finalize user message %s status", user_message.id)

        yield _sse({"type": "done"})

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{conversation_id}/chat")
async def chat(
    conversation_id: UUID,
    data: ChatRequest,
    service: ConversationService = Depends(get_conversation_service),
):
    """Non-streaming chat: send a user message and get the complete response.

    Body (both optional): ``{"provider": "...", "model": "..."}``.  Returns
    the persisted user/assistant messages plus provider, model and token
    usage.  When no provider is usable or all providers fail, returns 502
    with the provider error detail.
    """
    try:
        conversation = await service._get_by_id(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        history, _ = await service.list_messages(conversation_id, page=1, page_size=20)
    except ValueError:
        history = []
    provider_messages = _build_provider_messages(history, data.message)

    # User message first (status=pending), then the provider call.
    user_message_data = MessageCreate(
        conversation_id=conversation_id,
        role="user",
        content=data.message,
        metadata={"status": "pending", "stream": False},
    )
    user_message = await service.create_message(user_message_data)

    agent_service = _new_agent_service()
    try:
        result = await agent_service.generate_response(
            conversation,
            provider_messages,
            provider=data.provider,
            model=data.model,
            stream=False,
        )
    except (ProviderError, ProviderUnavailableError) as exc:
        # Provider layer failure (unavailable / all providers failed).
        raise HTTPException(status_code=502, detail=f"AI provider error: {exc.message}")

    assistant_metadata = AIAgentService.build_message_metadata(
        status="error" if result.error else "success",
        provider=result.provider,
        model=result.model,
        usage=result.usage,
        latency_ms=result.latency_ms,
        stream=False,
        error=result.error,
    )
    assistant_message = await service.create_message(MessageCreate(
        conversation_id=conversation_id,
        role="assistant",
        content=result.content or ("[ai-error]" if result.error else ""),
        metadata=assistant_metadata,
    ))
    # Finalize the user message's status (the schema's alias is ``metadata``).
    user_final_meta = {"status": "success", "stream": False}
    try:
        await service.update_message(
            user_message.id,
            MessageUpdate(metadata=user_final_meta),
        )
        # Mirror the persisted status onto the held object so the response is
        # coherent (the DB row was just updated to ``success``).
        user_message.metadata_ = user_final_meta
    except Exception:
        logger.exception("Failed to finalize user message %s status", user_message.id)

    return {
        "conversation_id": str(conversation_id),
        "user_message": user_message.model_dump(by_alias=True),
        "assistant_message": assistant_message.model_dump(by_alias=True),
        "provider": result.provider,
        "model": result.model,
        "usage": result.usage.as_dict() if result.usage else {
            "prompt_tokens": 0, "completion_tokens": 0, "total": 0,
        },
        "latency_ms": result.latency_ms,
        "error": result.error,
    }
