"""Chat completion routes."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.responses import StreamingResponse

from app.auth.dependencies import get_current_project
from app.db.models.project import Project
from app.errors import map_openai_provider_error
from app.providers.base import ChatMessage, CompletionRequest
from app.providers.exceptions import OpenAIProviderError
from app.schemas.chat import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessageResponse,
    Usage,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _to_completion_request(body: ChatCompletionRequest) -> CompletionRequest:
    return CompletionRequest(
        model=body.model,
        messages=[ChatMessage(role=m.role, content=m.content) for m in body.messages],
        temperature=body.temperature,
        max_tokens=body.max_tokens,
    )


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    body: ChatCompletionRequest,
    request: Request,
    project: Annotated[Project, Depends(get_current_project)],
) -> ChatCompletionResponse | StreamingResponse:
    """Proxy a chat completion to the configured LLM provider (JSON or SSE)."""
    provider = request.app.state.llm_provider
    completion_request = _to_completion_request(body)

    logger.info(
        "Chat completion project_id=%s model=%s messages=%d stream=%s",
        project.id,
        body.model,
        len(body.messages),
        body.stream,
    )

    if body.stream:
        stream_iter = provider.stream(completion_request)
        try:
            first_chunk = await stream_iter.__anext__()
        except StopAsyncIteration:
            first_chunk = None
        except OpenAIProviderError as exc:
            logger.warning("Provider stream error for project_id=%s: %s", project.id, exc.message)
            raise map_openai_provider_error(exc) from exc

        async def event_generator() -> AsyncIterator[str]:
            if first_chunk is not None:
                yield first_chunk
            try:
                async for sse_event in stream_iter:
                    yield sse_event
            except OpenAIProviderError as exc:
                logger.warning(
                    "Provider stream interrupted for project_id=%s: %s",
                    project.id,
                    exc.message,
                )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    try:
        result = await provider.complete(completion_request)
    except OpenAIProviderError as exc:
        logger.warning("Provider error for project_id=%s: %s", project.id, exc.message)
        raise map_openai_provider_error(exc) from exc

    return ChatCompletionResponse(
        id=result.id,
        created=result.created,
        model=result.model,
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessageResponse(content=result.content),
                finish_reason=result.finish_reason,
            )
        ],
        usage=Usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
        ),
    )
