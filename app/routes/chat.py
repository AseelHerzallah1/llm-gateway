"""Chat completion routes."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from starlette.responses import StreamingResponse

from app.auth.dependencies import get_current_project
from app.cache.chat_integration import (
    store_non_streaming_completion,
    try_cached_non_streaming_completion,
)
from app.db.models.project import Project
from app.config import settings
from app.errors import GatewayHTTPException, map_openai_provider_error
from app.observability.request_log import RequestLogCreate, persist_request_log
from app.observability.sse_usage import parse_sse_usage
from app.providers.base import ChatMessage, CompletionRequest
from app.providers.fallback import complete_with_fallback, stream_with_fallback
from app.providers.exceptions import AnthropicProviderError, OpenAIProviderError
from app.security.pii import PiiRedactionConfig, detokenize_text, redact_messages
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


def _pii_redaction_config() -> PiiRedactionConfig:
    return PiiRedactionConfig(
        redact_email=settings.pii_redact_email,
        redact_phone=settings.pii_redact_phone,
        redact_credit_card=settings.pii_redact_credit_card,
        redact_iban=settings.pii_redact_iban,
    )


def _build_completion_request(
    body: ChatCompletionRequest,
) -> tuple[CompletionRequest, dict[str, str]]:
    """Build provider request; redact PII for non-streaming when enabled."""
    if settings.pii_redaction_enabled and not body.stream:
        message_dicts = [{"role": m.role, "content": m.content} for m in body.messages]
        redacted, token_map = redact_messages(message_dicts, _pii_redaction_config())
        return (
            CompletionRequest(
                model=body.model,
                messages=[
                    ChatMessage(role=message["role"], content=message["content"])
                    for message in redacted
                ],
                temperature=body.temperature,
                max_tokens=body.max_tokens,
            ),
            token_map,
        )

    return _to_completion_request(body), {}


def _latency_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


async def _schedule_request_log(
    background_tasks: BackgroundTasks,
    data: RequestLogCreate,
) -> None:
    if settings.request_log_async:
        background_tasks.add_task(persist_request_log, data)
    else:
        await persist_request_log(data)


async def _log_error(
    background_tasks: BackgroundTasks,
    project: Project,
    model: str,
    started_at: float,
    error_reason: str,
) -> None:
    await _schedule_request_log(
        background_tasks,
        RequestLogCreate(
            project_id=project.id,
            model=model,
            status="error",
            latency_ms=_latency_ms(started_at),
            error_reason=error_reason[:512],
        ),
    )


async def _sse_event_generator(
    http_request: Request,
    project: Project,
    stream_iter: AsyncIterator[str],
    first_chunk: str | None,
    model: str,
    started_at: float,
) -> AsyncIterator[str]:
    """Forward SSE events and cancel upstream when the client disconnects."""
    saw_done = False
    input_tokens = 0
    output_tokens = 0
    client_disconnected = False
    provider_error: str | None = None

    try:
        if first_chunk is not None:
            if await http_request.is_disconnected():
                logger.info(
                    "Client disconnected before stream delivery project_id=%s",
                    project.id,
                )
                client_disconnected = True
                return

            usage = parse_sse_usage(first_chunk)
            if usage:
                input_tokens, output_tokens = usage
            if first_chunk.strip() == "data: [DONE]":
                saw_done = True
            yield first_chunk

        async for sse_event in stream_iter:
            if await http_request.is_disconnected():
                logger.info(
                    "Client disconnected mid-stream, cancelling upstream project_id=%s",
                    project.id,
                )
                client_disconnected = True
                break

            usage = parse_sse_usage(sse_event)
            if usage:
                input_tokens, output_tokens = usage
            if sse_event.strip() == "data: [DONE]":
                saw_done = True
            yield sse_event
    except (OpenAIProviderError, AnthropicProviderError) as exc:
        provider_error = exc.message
        logger.warning(
            "Provider stream interrupted for project_id=%s: %s",
            project.id,
            exc.message,
        )
    except asyncio.CancelledError:
        logger.info("Stream task cancelled for project_id=%s", project.id)
        raise
    finally:
        await stream_iter.aclose()

        if provider_error:
            status = "error"
            error_reason = provider_error
        elif client_disconnected:
            status = "error"
            error_reason = "client_disconnected"
        elif saw_done:
            status = "success"
            error_reason = None
        else:
            status = "error"
            error_reason = "stream_incomplete"

        await persist_request_log(
            RequestLogCreate(
                project_id=project.id,
                model=model,
                status=status,
                latency_ms=_latency_ms(started_at),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                error_reason=error_reason[:512] if error_reason else None,
            )
        )


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    body: ChatCompletionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    project: Annotated[Project, Depends(get_current_project)],
) -> ChatCompletionResponse | StreamingResponse:
    """Proxy a chat completion to the configured LLM provider (JSON or SSE)."""
    router = request.app.state.provider_router
    try:
        router.get_provider(body.model)
    except GatewayHTTPException:
        raise

    completion_request, pii_token_map = _build_completion_request(body)
    started_at = time.perf_counter()

    logger.info(
        "Chat completion project_id=%s model=%s messages=%d stream=%s",
        project.id,
        body.model,
        len(body.messages),
        body.stream,
    )

    if body.stream:
        try:
            stream_iter, first_chunk = await stream_with_fallback(
                router,
                body.model,
                completion_request,
                max_retries=settings.provider_max_retries,
                backoff_s=settings.provider_retry_backoff_s,
            )
        except (OpenAIProviderError, AnthropicProviderError) as exc:
            logger.warning("Provider stream error for project_id=%s: %s", project.id, exc.message)
            await _log_error(background_tasks, project, body.model, started_at, exc.message)
            raise map_openai_provider_error(exc) from exc

        return StreamingResponse(
            _sse_event_generator(
                request,
                project,
                stream_iter,
                first_chunk,
                body.model,
                started_at,
            ),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    latency_before_provider = _latency_ms(started_at)
    cache_check = await try_cached_non_streaming_completion(
        request,
        project,
        body,
        completion_request.messages,
        started_at,
        latency_before_provider,
    )
    if cache_check.cached_response is not None:
        return cache_check.cached_response

    try:
        result = await complete_with_fallback(
            router,
            body.model,
            completion_request,
            max_retries=settings.provider_max_retries,
            backoff_s=settings.provider_retry_backoff_s,
        )
    except (OpenAIProviderError, AnthropicProviderError) as exc:
        logger.warning("Provider error for project_id=%s: %s", project.id, exc.message)
        await _log_error(background_tasks, project, body.model, started_at, exc.message)
        raise map_openai_provider_error(exc) from exc

    await store_non_streaming_completion(
        request,
        project,
        body.model,
        completion_request.messages,
        result,
        embedding=cache_check.embedding,
    )

    await _schedule_request_log(
        background_tasks,
        RequestLogCreate(
            project_id=project.id,
            model=result.model,
            status="success",
            latency_ms=_latency_ms(started_at),
            input_tokens=result.prompt_tokens,
            output_tokens=result.completion_tokens,
        ),
    )

    response_content = result.content
    if pii_token_map and settings.pii_detokenize_responses:
        response_content = detokenize_text(response_content, pii_token_map)

    return ChatCompletionResponse(
        id=result.id,
        created=result.created,
        model=result.model,
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessageResponse(content=response_content),
                finish_reason=result.finish_reason,
            )
        ],
        usage=Usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
        ),
    )
