"""Chat completion routes."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_project
from app.db.models.project import Project
from app.errors import map_openai_provider_error, streaming_not_supported_error
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


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    body: ChatCompletionRequest,
    request: Request,
    project: Annotated[Project, Depends(get_current_project)],
) -> ChatCompletionResponse:
    """Proxy a non-streaming chat completion to the configured LLM provider."""
    if body.stream:
        raise streaming_not_supported_error()

    provider = request.app.state.llm_provider

    completion_request = CompletionRequest(
        model=body.model,
        messages=[ChatMessage(role=m.role, content=m.content) for m in body.messages],
        temperature=body.temperature,
        max_tokens=body.max_tokens,
    )

    logger.info(
        "Chat completion project_id=%s model=%s messages=%d",
        project.id,
        body.model,
        len(body.messages),
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
